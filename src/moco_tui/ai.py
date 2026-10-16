"""AI suggestions per invoice position.

Providers: Anthropic (native Messages API), OpenAI, Google Gemini, Mistral,
OpenRouter, Groq, Ollama, LM Studio, or any OpenAI-compatible endpoint.

Per item the AI returns:
- description  written from booked time entries, in invoice wording
- title        polished (offer wording -> invoice wording)
- quantity     suggestion based on booked hours (only for hour/day units)
- note         short reason / warning (e.g. "booked 30 h, offered 24 h")
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from dataclasses import asdict, dataclass

import requests

HOURS_PER_DAY = 8.0
HOUR_UNITS = {"h", "std", "std.", "stunde", "stunden", "hour", "hours"}
DAY_UNITS = {"d", "t", "tag", "tage", "pt", "day", "days", "personentag", "personentage"}


class AIError(RuntimeError):
    pass


@dataclass
class Suggestion:
    index: int  # index in offer["items"]
    title: str
    description: str
    quantity: float | None  # None = keep offered quantity
    offered_quantity: float | None
    unit: str | None
    booked_hours: float | None
    note: str = ""
    accepted: bool = True
    use_quantity: bool = False  # quantity change is opt-in

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- providers
@dataclass(frozen=True)
class Provider:
    key: str
    label: str
    wire: str  # "anthropic" or "openai" (chat/completions format)
    base_url: str
    model_hint: str
    needs_key: bool = True


PROVIDERS: dict[str, Provider] = {
    p.key: p
    for p in [
        Provider(
            "anthropic",
            "Anthropic (Claude)",
            "anthropic",
            "https://api.anthropic.com/v1",
            "claude-sonnet-5-5",
        ),
        Provider("openai", "OpenAI", "openai", "https://api.openai.com/v1", "model name"),
        Provider(
            "google",
            "Google Gemini",
            "openai",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "model name",
        ),
        Provider("mistral", "Mistral", "openai", "https://api.mistral.ai/v1", "model name"),
        Provider(
            "openrouter", "OpenRouter", "openai", "https://openrouter.ai/api/v1", "vendor/model"
        ),
        Provider("groq", "Groq", "openai", "https://api.groq.com/openai/v1", "model name"),
        Provider(
            "ollama",
            "Ollama (local)",
            "openai",
            "http://localhost:11434/v1",
            "llama3.1",
            needs_key=False,
        ),
        Provider(
            "lmstudio",
            "LM Studio (local)",
            "openai",
            "http://localhost:1234/v1",
            "loaded model",
            needs_key=False,
        ),
        Provider(
            "custom", "Custom (OpenAI-compatible)", "openai", "", "model name", needs_key=False
        ),
    ]
}


def detect_provider(provider: str, base_url: str, model: str) -> str:
    """Pick a provider for old settings that only have URL + model."""
    if provider in PROVIDERS:
        return provider
    url, m = (base_url or "").lower(), (model or "").lower()
    if "anthropic.com" in url or (m.startswith("claude") and not url):
        return "anthropic"
    for p in PROVIDERS.values():
        if p.base_url and url.startswith(p.base_url.lower()):
            return p.key
    if m.startswith("claude") and "openrouter" not in url:
        return "anthropic"
    return "custom" if url else ""


# --------------------------------------------------------------------------- client
class AIClient:
    """One client for all providers. No temperature is sent: newer models reject it."""

    MAX_TOKENS = 4096

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        timeout: int = 120,
        provider: str = "",
    ):
        self.provider = (
            PROVIDERS.get(detect_provider(provider, base_url, model)) or PROVIDERS["custom"]
        )
        self.base = (base_url or self.provider.base_url).rstrip("/")
        if not self.base:
            raise AIError("No endpoint URL set.")
        if self.provider.needs_key and not api_key:
            raise AIError(f"{self.provider.label} needs an API key.")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    # ---- public
    def chat(self, system: str, user: str) -> str:
        if self.provider.wire == "anthropic":
            return self._anthropic(system, user)
        return self._openai(system, user)

    # ---- wire formats
    def _anthropic(self, system: str, user: str) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        body = {
            "model": self.model,
            "max_tokens": self.MAX_TOKENS,
            "system": system,
            "messages": [{"role": "user", "content": user}],
        }
        data = self._post(self.base + "/messages", headers, body)
        try:
            return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text")
        except (KeyError, TypeError) as e:
            raise AIError(f"Unexpected Anthropic response: {str(data)[:300]}") from e

    def _openai(self, system: str, user: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        data = self._post(self.base + "/chat/completions", headers, body)
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise AIError(f"Unexpected AI response: {str(data)[:300]}") from e
        if isinstance(content, list):  # some providers return content parts
            content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
        return content or ""

    def _post(self, url: str, headers: dict, body: dict) -> dict:
        """POST; if the provider rejects an optional parameter, retry once without it."""
        for _ in range(3):
            try:
                r = requests.post(url, json=body, headers=headers, timeout=self.timeout)
            except requests.RequestException as e:
                raise AIError(f"{self.provider.label} not reachable: {e}") from e
            if r.status_code < 400:
                try:
                    return r.json()
                except ValueError as e:
                    raise AIError(f"Invalid JSON from {self.provider.label}") from e
            bad = rejected_param(r.text, body)
            if r.status_code == 400 and bad:
                body = {k: v for k, v in body.items() if k != bad}
                continue
            raise AIError(f"{self.provider.label} {r.status_code}: {error_text(r)}")
        raise AIError(f"{self.provider.label}: request rejected")


OPTIONAL_PARAMS = ("temperature", "top_p", "max_tokens", "max_completion_tokens")


def rejected_param(text: str, body: dict) -> str | None:
    t = (text or "").lower()
    for p in OPTIONAL_PARAMS:
        if (
            p in body
            and p in t
            and (
                "unsupported" in t
                or "not supported" in t
                or "deprecated" in t
                or "invalid" in t
                or "not allowed" in t
                or "does not support" in t
            )
        ):
            # never drop max_tokens for Anthropic (required there)
            if p == "max_tokens" and "anthropic-version" in t:
                return None
            return p
    return None


def error_text(r: requests.Response) -> str:
    """Short, readable provider error."""
    try:
        d = r.json()
        err = d.get("error", d)
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        if isinstance(d, list) and d:  # Gemini sometimes returns a list
            return str(d[0].get("error", {}).get("message", d[0]))[:300]
        return str(err)[:300]
    except ValueError:
        return r.text[:300]


def parse_json(text: str) -> dict:
    """Lenient: accepts ```json fences and text around the object."""
    text = re.sub(r"```(?:json)?", "", text)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        raise AIError("AI did not return JSON.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise AIError(f"AI returned invalid JSON: {e}") from e


# --------------------------------------------------------------------------- data prep
def unit_kind(unit: str | None) -> str | None:
    u = (unit or "").strip().lower()
    if u in HOUR_UNITS:
        return "h"
    if u in DAY_UNITS:
        return "d"
    return None


def summarize_activities(activities: list[dict], max_lines: int = 40) -> list[dict]:
    """Group billable, not yet billed activities by task."""
    groups: dict[str, dict] = defaultdict(lambda: {"hours": 0.0, "notes": []})
    for a in activities:
        if not a.get("billable", True) or a.get("billed"):
            continue
        task = (a.get("task") or {}).get("name") or "Ohne Aufgabe"
        g = groups[task]
        g["hours"] += float(a.get("hours") or 0)
        d = (a.get("description") or "").strip()
        if d and d not in g["notes"] and len(g["notes"]) < max_lines:
            g["notes"].append(d)
    return [
        {"task": t, "hours": round(g["hours"], 2), "notes": g["notes"]} for t, g in groups.items()
    ]


def billable_items(offer: dict, include_optional: bool) -> list[tuple[int, dict]]:
    return [
        (i, it)
        for i, it in enumerate(offer.get("items", []))
        if it.get("type") == "item" and (include_optional or not it.get("optional"))
    ]


SYSTEM = """You write invoice line items for a service company.
Rules:
- Language: {lang}. Professional, concise, past tense ("Umgesetzt", "Delivered").
- Title: rewrite offer wording into invoice wording. Keep it short. Keep meaning.
- Description: 1-3 short bullet lines from the time entries that belong to this item.
  Only use facts from the time entries or the offer. Never invent work.
  If no time entries match, rewrite the offer description, or return "".
- Map time entries to items by task name and content. Give booked_hours per item
  (sum of matched hours, null if nothing matches).
- note: one short line for the accountant, e.g. hours above/below offer. "" if nothing.
Return ONLY JSON: {{"items":[{{"index":int,"title":str,"description":str,
"booked_hours":number|null,"note":str}}]}}"""


def build_prompt(offer: dict, items: list[tuple[int, dict]], activity_groups: list[dict]) -> str:
    return json.dumps(
        {
            "offer": {
                "title": offer.get("title"),
                "customer": (offer.get("company") or {}).get("name"),
            },
            "items": [
                {
                    "index": i,
                    "title": it.get("title"),
                    "description": strip_html(it.get("description")),
                    "quantity": it.get("quantity"),
                    "unit": it.get("unit"),
                }
                for i, it in items
            ],
            "time_entries_by_task": activity_groups,
        },
        ensure_ascii=False,
        indent=1,
    )


def strip_html(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<br\s*/?>|</div>|</p>|</li>", "\n", s, flags=re.I)
    return re.sub(r"<[^>]+>", "", s).strip()


def to_html(text: str) -> str:
    """Plain text with line breaks -> MOCO rich text."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return "<div>" + "<br>".join(lines) + "</div>" if lines else ""


# --------------------------------------------------------------------------- main entry
def suggest(
    client: AIClient,
    offer: dict,
    activities: list[dict],
    include_optional: bool = False,
    language: str = "Deutsch",
) -> list[Suggestion]:
    items = billable_items(offer, include_optional)
    if not items:
        return []
    groups = summarize_activities(activities)
    raw = parse_json(client.chat(SYSTEM.format(lang=language), build_prompt(offer, items, groups)))
    by_index = {r.get("index"): r for r in raw.get("items", []) if isinstance(r, dict)}

    out = []
    for i, it in items:
        r = by_index.get(i, {})
        booked = r.get("booked_hours")
        booked = float(booked) if isinstance(booked, (int, float)) else None
        kind = unit_kind(it.get("unit"))
        qty = None
        if booked is not None and kind:
            qty = round(booked if kind == "h" else booked / HOURS_PER_DAY, 2)
        note = (r.get("note") or "").strip()
        offered = it.get("quantity")
        if qty is not None and offered and abs(qty - float(offered)) > 0.01 and not note:
            note = f"Booked {qty:g} {it.get('unit')}, offered {offered:g}"
        out.append(
            Suggestion(
                index=i,
                title=(r.get("title") or it.get("title") or "").strip(),
                description=(r.get("description") or "").strip(),
                quantity=qty,
                offered_quantity=offered,
                unit=it.get("unit"),
                booked_hours=booked,
                note=note,
            )
        )
    return out


def apply(items: list[dict], overrides: dict[int, dict]) -> list[dict]:
    """Return offer items with accepted AI overrides applied (by original index)."""
    out = []
    for i, it in enumerate(items):
        o = overrides.get(i)
        if o and o.get("accepted"):
            it = dict(it)
            if o.get("title"):
                it["title"] = o["title"]
            if o.get("description"):
                it["description"] = to_html(o["description"])
            if o.get("use_quantity") and o.get("quantity") is not None and it.get("unit_price"):
                it["quantity"] = o["quantity"]
                it["net_total"] = round(o["quantity"] * it["unit_price"], 2)
        out.append(it)
    return out
