import json

import pytest

from moco_tui.mcp_server import build_server
from moco_tui.store import Settings


@pytest.fixture
def server(store, fake, monkeypatch):
    monkeypatch.delenv("MOCO_DOMAIN", raising=False)
    monkeypatch.delenv("MOCO_API_KEY", raising=False)
    store.save_settings(Settings(domain="acme", api_key="k"))
    return build_server(store, api=fake)


async def call(server, name, **args):
    res = await server.call_tool(name, args)
    return res


async def test_tools_listed(server):
    names = {t.name for t in await server.list_tools()}
    assert {
        "list_offers",
        "get_offer",
        "get_time_entries",
        "set_item_texts",
        "suggest_items",
        "create_invoice_draft",
        "draft_history",
    } <= names


def data(res):
    """Structured result of a tool call."""
    sc = res.structured_content
    if sc is None:  # dict results come back as JSON text
        return json.loads(res.content[0].text)
    return sc.get("result", sc) if isinstance(sc, dict) else sc


async def test_list_offers_states(server):
    offers = data(await call(server, "list_offers"))
    assert {o["identifier"]: o["state"] for o in offers} == {
        "A2610-001": "ready",
        "A2610-002": "draft",
        "A2610-003": "nocust",
        "A2610-004": "linked",
    }


async def test_client_writes_texts_then_creates(server, fake, store):
    entries = data(await call(server, "get_time_entries", offer_id=1))
    assert entries[0]["hours"] == 28.0

    await call(
        server,
        "set_item_texts",
        offer_id=1,
        items=[
            {"index": 1, "title": "Design erstellt", "description": "Wireframes", "quantity": 3.5}
        ],
    )
    dry = data(await call(server, "create_invoice_draft", offer_id=1))
    item = next(i for i in dry["payload"]["items"] if i.get("title") == "Design erstellt")
    assert item["quantity"] == 3.5
    assert fake.posted == []

    real = data(await call(server, "create_invoice_draft", offer_id=1, dry_run=False))
    assert real["created"] and real["url"].endswith(f"/invoices/{real['invoice_id']}")
    again = data(await call(server, "create_invoice_draft", offer_id=1, dry_run=False))
    assert again == {"skipped": True, "state": "draft"}
    assert len(data(await call(server, "draft_history"))) == 1


async def test_set_item_texts_rejects_non_item(server):
    with pytest.raises(Exception, match="not an item"):
        await call(server, "set_item_texts", offer_id=1, items=[{"index": 0, "title": "x"}])
