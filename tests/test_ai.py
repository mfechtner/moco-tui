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
