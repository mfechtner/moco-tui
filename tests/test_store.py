import os

from moco_tui.store import Settings, db_path


def test_settings_roundtrip(store, monkeypatch):
    monkeypatch.delenv("MOCO_DOMAIN", raising=False)
    monkeypatch.delenv("MOCO_API_KEY", raising=False)
    assert not store.load_settings().complete
    s = Settings(domain="acme", api_key="k", due_days=30, include_optional=True)
    store.save_settings(s)
    assert store.load_settings() == s


def test_env_overrides(store, monkeypatch):
    store.save_settings(Settings(domain="db", api_key="db"))
    monkeypatch.setenv("MOCO_DOMAIN", "env")
    assert store.load_settings().domain == "env"


def test_history(store):
    offer = {
        "id": 7,
        "identifier": "A1",
        "title": "T",
        "company": {"name": "C"},
        "net_total": 10,
        "currency": "EUR",
    }
    assert not store.has_draft(7)
    store.add_draft(offer, 99)
    assert store.has_draft(7)
    assert store.history()[0]["invoice_id"] == 99


def test_db_in_config_dir(monkeypatch):
    monkeypatch.delenv("MOCO_TUI_DB", raising=False)
    p = db_path()
    assert p.name == "moco-tui.db"
    assert "moco-tui" in p.parent.name


def test_db_file_private(store):
    if os.name == "posix":
        assert oct(store.path.stat().st_mode)[-3:] == "600"
