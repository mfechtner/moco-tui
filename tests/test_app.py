"""Headless TUI tests with a fake MOCO API."""

import pytest
from conftest import FakeMoco

import moco_tui.app as app_mod
from moco_tui.app import MocoApp, SettingsScreen
from moco_tui.store import Settings


@pytest.fixture
def patched(monkeypatch):
    fake = FakeMoco()
    monkeypatch.setattr(app_mod, "Moco", lambda *a, **k: fake)
    monkeypatch.delenv("MOCO_DOMAIN", raising=False)
    monkeypatch.delenv("MOCO_API_KEY", raising=False)
    return fake


async def wait_loaded(app, pilot):
    for _ in range(50):
        await pilot.pause(0.05)
        if app.state and "checking" not in app.state.values():
            return


async def test_first_run_shows_setup(store, patched):
    app = MocoApp(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SettingsScreen)


async def test_select_and_create(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await wait_loaded(app, pilot)
        assert app.state == {1: "ready", 2: "draft", 3: "nocust", 4: "linked"}
        await pilot.press("a")
        assert app.selected == {1}
        await pilot.press("c")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause(0.3)
        assert len(patched.posted) == 1
        assert app.state[1] == "created"
        assert store.has_draft(1)


async def test_dry_run(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("d", "a", "c")
        await pilot.pause(0.3)
        assert patched.posted == []
        assert not store.has_draft(1)


async def test_filter(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("slash", *"beta", "enter")
        await pilot.pause()
        assert app.query_one("#offers").row_count == 1


async def test_history_screen(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    store.add_draft({"id": 1, "identifier": "A1", "title": "T"}, 42)
    app = MocoApp(store)
    async with app.run_test(size=(140, 40)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("h")
        await pilot.pause()
        assert app.screen.query_one("#hist").row_count == 1


async def test_ai_review_flow(store, patched, monkeypatch):
    from conftest import FakeAI

    import moco_tui.service as service_mod
    from moco_tui.app import AIReviewScreen

    monkeypatch.setattr(service_mod.ai, "AIClient", lambda *a, **k: FakeAI())
    store.save_settings(
        Settings(domain="acme", api_key="k", ai_base_url="http://x/v1", ai_model="m")
    )
    app = MocoApp(store)
    async with app.run_test(size=(160, 45)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("g")
        for _ in range(40):
            await pilot.pause(0.05)
            if isinstance(app.screen, AIReviewScreen):
                break
        assert isinstance(app.screen, AIReviewScreen)
        await pilot.press("u")  # use booked quantity for Design
        await pilot.press("ctrl+s")
        await pilot.pause(0.2)
        ov = store.load_overrides(1)
        assert ov[1]["title"] == "Design umgesetzt" and ov[1]["use_quantity"]
        await pilot.press("a", "c", "y")
        await pilot.pause(0.4)
        design = next(i for i in patched.posted[0]["items"] if i.get("title") == "Design umgesetzt")
        assert design["quantity"] == 3.5


async def test_enter_opens_offer_details(store, patched):
    from textual.widgets import TabbedContent

    from moco_tui.app import OfferScreen

    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("enter")
        await pilot.pause(0.4)
        assert isinstance(app.screen, OfferScreen)
        assert len(app.screen_stack) == 2  # opened once, not twice
        assert app.screen.query_one("#o_items").row_count == 5
        await pilot.press("3")
        await pilot.pause(0.2)
        assert app.screen.query_one(TabbedContent).active == "t_time"
        assert "28 h" in str(app.screen.query_one("#o_time").render())
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, OfferScreen)


async def test_offer_details_create(store, patched):
    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("enter")
        await pilot.pause(0.3)
        await pilot.press("c")
        await pilot.pause(0.2)
        await pilot.press("y")
        await pilot.pause(0.4)
        assert len(patched.posted) == 1


async def test_invoice_edit_flow(store, patched):
    from textual.widgets import Input

    from moco_tui.invoice_screens import (
        DraftEditor,
        InvoiceScreen,
        InvoicesScreen,
        ItemEditor,
    )

    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("i")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InvoicesScreen)
        assert app.screen.query_one("#invoices").row_count == 2  # drafts only
        await pilot.press("enter")
        await pilot.pause(0.3)
        assert isinstance(app.screen, InvoiceScreen)
        await pilot.press("e")
        await pilot.pause(0.2)
        assert isinstance(app.screen, DraftEditor)
        await pilot.press("down", "enter")  # edit item 1 (Beratung)
        await pilot.pause(0.2)
        assert isinstance(app.screen, ItemEditor)
        app.screen.query_one("#t_qty", Input).value = "3"
        await pilot.press("ctrl+s")
        await pilot.pause(0.1)
        await pilot.press("d")  # delete Beratung? cursor is on item 1 -> deletes it
        await pilot.pause(0.1)
        assert len(app.screen.items) == 2
        await pilot.press("ctrl+s")
        await pilot.pause(0.1)
        await pilot.press("y")
        await pilot.pause(0.5)
        assert patched.deleted == [900]
        assert [i.get("title") for i in patched.posted[-1]["items"]] == ["Leistungen", "Pauschale"]


async def test_final_invoice_read_only(store, patched):
    from textual.widgets import Select

    from moco_tui.invoice_screens import DraftEditor

    store.save_settings(Settings(domain="acme", api_key="k"))
    app = MocoApp(store)
    async with app.run_test(size=(150, 45)) as pilot:
        await wait_loaded(app, pilot)
        await pilot.press("i")
        await pilot.pause(0.3)
        app.screen.query_one("#istatus", Select).value = "sent"
        await pilot.pause(0.3)
        await pilot.press("enter")
        await pilot.pause(0.3)
        await pilot.press("e")
        await pilot.pause(0.2)
        assert not isinstance(app.screen, DraftEditor)
