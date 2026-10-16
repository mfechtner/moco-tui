"""AI suggestions per invoice position.

Works with any OpenAI-compatible endpoint (POST {base_url}/chat/completions):
OpenAI, Ollama (http://localhost:11434/v1), LM Studio, OpenRouter, Azure, vLLM …

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


# --------------------------------------------------------------------------- client
class AIClient:
    def __init__(self, base_url: str, api_key: str, model: str, timeout: int = 120):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.timeout = timeout
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = f"Bearer {api_key}"

    def chat(self, system: str, user: str) -> str:
        body = {
            "model": self.model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        try:
            r = requests.post(self.url, json=body, headers=self.headers, timeout=self.timeout)
        except requests.RequestException as e:
            raise AIError(f"AI endpoint not reachable: {e}") from e
        if r.status_code >= 400:
            raise AIError(f"AI endpoint {r.status_code}: {r.text[:300]}")
        try:
            return r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise AIError(f"Unexpected AI response: {r.text[:300]}") from e


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
