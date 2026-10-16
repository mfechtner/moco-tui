import json

import pytest
from conftest import ACTIVITIES, FakeAI

from moco_tui import ai
from moco_tui.service import Service, build_invoice


def test_summarize_skips_billed_and_unbillable():
    groups = ai.summarize_activities(ACTIVITIES)
    assert groups == [{"task": "Design", "hours": 28.0, "notes": ["Wireframes", "Screen design"]}]


def test_parse_json_lenient():
    assert ai.parse_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(ai.AIError):
        ai.parse_json("no json here")


def test_suggest_maps_hours_to_days(fake):
    sugg = ai.suggest(FakeAI(), fake.offer(1), ACTIVITIES)
    # items: Design (index 1, unit d) and Licence (index 4); optional "Extra" skipped
    assert [s.index for s in sugg] == [1, 4]
    design = sugg[0]
    assert design.title == "Design umgesetzt"
    assert design.booked_hours == 28
    assert design.quantity == 3.5  # 28 h / 8 h per day
    assert "3.5" in design.note and "offered 3" in design.note
    assert not design.use_quantity  # quantity change is opt-in
    licence = sugg[1]
    assert licence.title == "Licence"  # AI gave nothing -> keep original
    assert licence.quantity is None


def test_prompt_contains_only_billable_time(fake):
    client = FakeAI()
    ai.suggest(client, fake.offer(1), ACTIVITIES)
    payload = json.loads(client.calls[0][1])
    assert payload["time_entries_by_task"][0]["hours"] == 28.0
    assert "Old work" not in client.calls[0][1]


def test_apply_overrides(fake, cfg):
    s = ai.suggest(FakeAI(), fake.offer(1), ACTIVITIES)[0]
    s.use_quantity = True
    inv = build_invoice(fake.offer(1), cfg, overrides={1: s.to_dict()})
    design = next(i for i in inv["items"] if i.get("title") == "Design umgesetzt")
    assert design["quantity"] == 3.5
    assert design["description"] == "<div>Wireframes erstellt<br>Screendesign erstellt</div>"


def test_rejected_override_ignored(fake, cfg):
    s = ai.suggest(FakeAI(), fake.offer(1), ACTIVITIES)[0]
    s.accepted = False
    inv = build_invoice(fake.offer(1), cfg, overrides={1: s.to_dict()})
    assert any(i.get("title") == "Design" for i in inv["items"])


def test_service_uses_stored_overrides(fake, store, cfg):
    svc = Service(fake, store, cfg)
    sugg = ai.suggest(FakeAI(), fake.offer(1), ACTIVITIES)
    store.save_overrides(1, [x.to_dict() for x in sugg])
    payload = svc.create_draft(1, dry_run=True)
    assert any(i.get("title") == "Design umgesetzt" for i in payload["items"])


def test_activities_from_offer_date(fake, store, cfg):
    Service(fake, store, cfg).activities_for(fake.offer(1))
    assert fake.activity_calls[0][:2] == (77, "2026-09-01")


def test_ai_not_configured(fake, store, cfg):
    with pytest.raises(ai.AIError):
        Service(fake, store, cfg).ai_client()


def test_client_sends_openai_format(monkeypatch):
    sent = {}

    class R:
        status_code = 200

        def json(self):
            return {"choices": [{"message": {"content": "OK"}}]}

    def post(url, json, headers, timeout):
        sent.update(url=url, json=json, headers=headers)
        return R()

    monkeypatch.setattr(ai.requests, "post", post)
    out = ai.AIClient("http://localhost:11434/v1/", "", "llama3.1").chat("sys", "hi")
    assert out == "OK"
    assert sent["url"] == "http://localhost:11434/v1/chat/completions"
    assert sent["json"]["model"] == "llama3.1"
    assert "Authorization" not in sent["headers"]  # no key for local models


# ---------------------------------------------------------------- providers
class Resp:
    def __init__(self, status, data):
        self.status_code, self._data = status, data
        self.text = data if isinstance(data, str) else json.dumps(data)

    def json(self):
        if isinstance(self._data, str):
            raise ValueError
        return self._data


def record(monkeypatch, *responses):
    sent = []
    queue = list(responses)

    def post(url, json, headers, timeout):
        sent.append({"url": url, "json": json, "headers": headers})
        return queue.pop(0)

    monkeypatch.setattr(ai.requests, "post", post)
    return sent


def test_anthropic_native(monkeypatch):
    sent = record(monkeypatch, Resp(200, {"content": [{"type": "text", "text": "OK"}]}))
    out = ai.AIClient("", "sk-ant", "claude-sonnet-5-5", provider="anthropic").chat("sys", "hi")
    assert out == "OK"
    req = sent[0]
    assert req["url"] == "https://api.anthropic.com/v1/messages"
    assert req["headers"]["x-api-key"] == "sk-ant"
    assert req["headers"]["anthropic-version"] == "2023-06-01"
    assert req["json"]["system"] == "sys"
    assert req["json"]["max_tokens"] > 0
    assert "temperature" not in req["json"]


def test_no_temperature_anywhere(monkeypatch):
    sent = record(monkeypatch, Resp(200, {"choices": [{"message": {"content": "OK"}}]}))
    ai.AIClient("", "sk", "some-model", provider="openai").chat("s", "u")
    assert "temperature" not in sent[0]["json"]
    assert sent[0]["url"] == "https://api.openai.com/v1/chat/completions"


def test_retries_without_rejected_param(monkeypatch):
    sent = record(
        monkeypatch,
        Resp(400, {"error": {"message": "Unsupported parameter: 'top_p' is not supported"}}),
        Resp(200, {"choices": [{"message": {"content": "OK"}}]}),
    )
    c = ai.AIClient("", "sk", "m", provider="openai")
    data = c._post("https://x/chat/completions", {}, {"model": "m", "top_p": 0.5})
    assert data["choices"][0]["message"]["content"] == "OK"
    assert "top_p" in sent[0]["json"] and "top_p" not in sent[1]["json"]


def test_readable_error(monkeypatch):
    record(monkeypatch, Resp(401, {"error": {"type": "auth", "message": "invalid x-api-key"}}))
    with pytest.raises(ai.AIError, match="Anthropic \\(Claude\\) 401: invalid x-api-key"):
        ai.AIClient("", "bad", "claude-sonnet-5-5", provider="anthropic").chat("s", "u")


def test_key_required_for_cloud():
    with pytest.raises(ai.AIError, match="needs an API key"):
        ai.AIClient("", "", "claude-sonnet-5-5", provider="anthropic")


@pytest.mark.parametrize(
    "provider,url,model,expected",
    [
        ("", "https://api.anthropic.com/v1", "claude-sonnet-5-5", "anthropic"),
        ("", "https://api.anthropic.com/v1/", "claude-sonnet-5-5", "anthropic"),
        ("", "", "claude-sonnet-5-5", "anthropic"),
        ("", "https://openrouter.ai/api/v1", "anthropic/claude-sonnet-5-5", "openrouter"),
        ("", "http://localhost:11434/v1", "llama3.1", "ollama"),
        ("", "https://my.proxy/v1", "x", "custom"),
        ("google", "", "x", "google"),
    ],
)
def test_detect_provider(provider, url, model, expected):
    assert ai.detect_provider(provider, url, model) == expected


def test_settings_ai_ready_with_provider_default():
    from moco_tui.store import Settings

    assert Settings(ai_provider="anthropic", ai_model="claude-sonnet-5-5").ai_ready
    assert not Settings(ai_provider="anthropic").ai_ready
    assert not Settings(ai_provider="custom", ai_model="m").ai_ready  # custom needs URL
