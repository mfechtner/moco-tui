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
