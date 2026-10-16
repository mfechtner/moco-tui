"""Status changes, email, PDF, payments, reminders, delete."""

import json

import pytest
from conftest import FakeMoco
from textual.widgets import Input

import moco_tui.app as app_mod
import moco_tui.dialogs as dialogs
from moco_tui.api import clean
from moco_tui.app import MocoApp, OfferScreen
from moco_tui.dialogs import EmailDialog, PaymentDialog, StatusPicker, TextPrompt, parse_number
from moco_tui.invoice_screens import InvoiceScreen
from moco_tui.mcp_server import build_server
from moco_tui.store import Settings


@pytest.fixture
def patched(monkeypatch, tmp_path):
    fake = FakeMoco()
    monkeypatch.setattr(app_mod, "Moco", lambda *a, **k: fake)
    monkeypatch.setattr(dialogs, "user_downloads_dir", lambda: str(tmp_path))
    monkeypatch.delenv("MOCO_DOMAIN", raising=False)
    monkeypatch.delenv("MOCO_API_KEY", raising=False)
    return fake


async def settle(pilot, n=6):
    for _ in range(n):
        await pilot.pause(0.05)


async def loaded(app, pilot):
    for _ in range(60):
        await pilot.pause(0.05)
        if app.state and "checking" not in app.state.values():
            return


# ------------------------------------------------------------------ helpers
def test_clean_drops_empty():
    assert clean({"a": "", "b": None, "c": 0, "d": "x"}) == {"c": 0, "d": "x"}


@pytest.mark.parametrize(
    "text,expected", [("1.234,56", 1234.56), ("99,5", 99.5), ("10", 10.0), ("", None)]
)
def test_parse_number(text, expected):
    assert parse_number(text) == expected


def test_save_pdf_never_overwrites(tmp_path, monkeypatch):
    monkeypatch.setattr(dialogs, "user_downloads_dir", lambda: str(tmp_path))
    a = dialogs.save_pdf(b"1", "Rechnung R/1")
    b = dialogs.save_pdf(b"2", "Rechnung R/1")
    assert a.name == "Rechnung_R_1.pdf" and b.name == "Rechnung_R_1-2.pdf"
    assert a.read_bytes() == b"1"


# ------------------------------------------------------------------ offers
async def test_offer_status_email_pdf(store, patched, tmp_path):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await loaded(app, pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(app.screen, OfferScreen)

        await pilot.press("t")
        await settle(pilot, 3)
        assert isinstance(app.screen, StatusPicker)
        await pilot.press("down", "down", "enter")  # accepted -> partially_billed -> billed
        await settle(pilot)
        assert patched.status_updates == [(1, "billed")]

        await pilot.press("m")
        await settle(pilot, 3)
        assert isinstance(app.screen, EmailDialog)
        app.screen.query_one("#m_to", Input).value = "kunde@x.test"
        await pilot.press("ctrl+s")
        await settle(pilot)
        kind, oid, mail = patched.actions[-1]
        assert kind == "offer_email" and mail["emails_to"] == "kunde@x.test"
        assert mail["subject"].startswith("Angebot A2610-001")

        await pilot.press("p")
        await settle(pilot)
        assert (tmp_path / "Angebot_A2610-001.pdf").read_bytes() == b"%PDF-offer"


async def test_offer_status_from_list(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await loaded(app, pilot)
        await pilot.press("t")
        await settle(pilot, 3)
        await pilot.press("down", "enter")
        await settle(pilot)
        assert patched.status_updates == [(1, "partially_billed")]


# ------------------------------------------------------------------ invoices
async def open_invoice(app, pilot, status):
    from textual.widgets import Select

    await loaded(app, pilot)
    await pilot.press("i")
    await settle(pilot)
    app.screen.query_one("#istatus", Select).value = status
    await settle(pilot)
    await pilot.press("enter")
    await settle(pilot, 8)
    assert isinstance(app.screen, InvoiceScreen)


async def test_invoice_payment_reminder_status(store, patched, tmp_path):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await open_invoice(app, pilot, "sent")

        await pilot.press("b")
        await settle(pilot, 3)
        assert isinstance(app.screen, PaymentDialog)
        assert app.screen.query_one("#p_amount", Input).value == "200.00"  # 297.5 - 97.5 paid
        await pilot.press("ctrl+s")
        await settle(pilot, 8)
        assert patched.actions[-1][:1] == ("payment",) and patched.actions[-1][3] == 200.0

        await pilot.press("r")
        await settle(pilot, 3)
        await pilot.press("ctrl+s")
        await settle(pilot, 8)
        assert patched.actions[-1][0] == "reminder"

        await pilot.press("t")
        await settle(pilot, 3)
        await pilot.press("down", "down", "enter")  # sent -> overdue -> ignored
        await settle(pilot, 8)
        assert ("invoice_status", 902, "ignored") in patched.actions

        await pilot.press("P")
        await settle(pilot)
        assert (tmp_path / "Rechnung_R2610-001_Zeiten.pdf").exists()


async def test_delete_final_needs_reason(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await open_invoice(app, pilot, "sent")
        await pilot.press("x")
        await settle(pilot, 3)
        assert isinstance(app.screen, TextPrompt)
        app.screen.query_one("#tp_value", Input).value = "Doppelt erstellt"
        await pilot.press("ctrl+s")
        await settle(pilot, 8)
        assert patched.deleted == [902] and patched.delete_reasons == ["Doppelt erstellt"]
        assert not isinstance(app.screen, InvoiceScreen)


async def test_draft_hides_final_only_actions(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await open_invoice(app, pilot, "draft")
        await pilot.press("b", "t")
        await settle(pilot, 3)
        assert isinstance(app.screen, InvoiceScreen)  # no dialog opened
        await pilot.press("x", "y")
        await settle(pilot, 8)
        assert patched.deleted == [900] and patched.delete_reasons == [None]


# ------------------------------------------------------------------ mcp
async def test_mcp_actions(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    server = build_server(store, api=patched)

    def data(res):
        sc = res.structured_content
        return json.loads(res.content[0].text) if sc is None else sc.get("result", sc)

    res = await server.call_tool("set_offer_status", {"offer_id": 1, "status": "billed"})
    assert data(res) == {"offer_id": 1, "status": "billed"}
    with pytest.raises(Exception, match="must be one of"):
        await server.call_tool("set_invoice_status", {"invoice_id": 902, "status": "paid"})
    await server.call_tool(
        "record_payment", {"invoice_id": 902, "date": "2026-10-16", "paid_total": 200}
    )
    assert patched.actions[-1] == ("payment", 902, "2026-10-16", 200.0)
    inv = data(await server.call_tool("get_invoice", {"invoice_id": 900}))
    assert inv["salutation"] == "Hallo"
    drafts = data(await server.call_tool("list_invoices", {}))
    assert {d["id"] for d in drafts} == {900, 901}
