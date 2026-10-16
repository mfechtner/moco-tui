"""SQLite store in the OS config folder.

Linux:   ~/.config/moco-tui/moco-tui.db
macOS:   ~/Library/Application Support/moco-tui/moco-tui.db
Windows: %APPDATA%\\moco-tui\\moco-tui.db

Override with env MOCO_TUI_DB=/path/to/file.db
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path

from platformdirs import user_config_dir

APP = "moco-tui"

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS drafts (
    offer_id         INTEGER PRIMARY KEY,
    offer_identifier TEXT NOT NULL,
    offer_title      TEXT,
    customer         TEXT,
    invoice_id       INTEGER NOT NULL,
    net_total        REAL,
    currency         TEXT,
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ai_overrides (
    offer_id   INTEGER NOT NULL,
    item_index INTEGER NOT NULL,
    data       TEXT NOT NULL,          -- JSON of ai.Suggestion
    updated_at TEXT NOT NULL,
    PRIMARY KEY (offer_id, item_index)
);
"""


@dataclass
class Settings:
    domain: str = ""
    api_key: str = ""
    offer_status: str = "accepted"
    due_days: int = 14
    include_optional: bool = False
    mark_offer_billed: bool = False
    title_prefix: str = "Rechnung"
    tag_prefix: str = "Angebot"
    # AI (OpenAI-compatible endpoint)
    ai_base_url: str = ""
    ai_api_key: str = ""
    ai_model: str = ""
    ai_language: str = "Deutsch"
    ai_lookback_days: int = 365

    @property
    def ai_ready(self) -> bool:
        return bool(self.ai_base_url and self.ai_model)

    @property
    def complete(self) -> bool:
        return bool(self.domain and self.api_key)


def db_path() -> Path:
    if env := os.environ.get("MOCO_TUI_DB"):
        return Path(env)
    return Path(user_config_dir(APP, appauthor=False)) / f"{APP}.db"


class Store:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists()
        self.con = sqlite3.connect(self.path, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.con.executescript(SCHEMA)
        if new and os.name == "posix":
            os.chmod(self.path, 0o600)  # holds the API key

    # ---- settings ----
    def load_settings(self) -> Settings:
        raw = dict(self.con.execute("SELECT key, value FROM settings").fetchall())
        s = Settings()
        for f in fields(Settings):
            if f.name in raw:
                v = raw[f.name]
                if f.type in ("bool", bool):
                    v = v == "1"
                elif f.type in ("int", int):
                    v = int(v)
                setattr(s, f.name, v)
        # env vars win (handy for CI / cron)
        s.domain = os.environ.get("MOCO_DOMAIN", s.domain)
        s.api_key = os.environ.get("MOCO_API_KEY", s.api_key)
        s.ai_base_url = os.environ.get("MOCO_TUI_AI_BASE_URL", s.ai_base_url)
        s.ai_api_key = os.environ.get("MOCO_TUI_AI_API_KEY", s.ai_api_key)
        s.ai_model = os.environ.get("MOCO_TUI_AI_MODEL", s.ai_model)
        return s

    def save_settings(self, s: Settings) -> None:
        rows = []
        for k, v in asdict(s).items():
            if isinstance(v, bool):
                v = "1" if v else "0"
            rows.append((k, str(v)))
        with self.con:
            self.con.executemany(
                "INSERT INTO settings(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                rows,
            )

    # ---- draft history ----
    def has_draft(self, offer_id: int) -> bool:
        return (
            self.con.execute("SELECT 1 FROM drafts WHERE offer_id = ?", (offer_id,)).fetchone()
            is not None
        )

    def add_draft(self, offer: dict, invoice_id: int) -> None:
        with self.con:
            self.con.execute(
                "INSERT OR REPLACE INTO drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    offer["id"],
                    offer.get("identifier", ""),
                    offer.get("title"),
                    (offer.get("company") or {}).get("name"),
                    invoice_id,
                    offer.get("net_total"),
                    offer.get("currency"),
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )

    def history(self, limit: int = 200) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM drafts ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()

    # ---- AI overrides (accepted suggestions per offer item) ----
    def save_overrides(self, offer_id: int, suggestions: list[dict]) -> None:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self.con:
            self.con.execute("DELETE FROM ai_overrides WHERE offer_id = ?", (offer_id,))
            self.con.executemany(
                "INSERT INTO ai_overrides VALUES (?, ?, ?, ?)",
                [
                    (offer_id, s["index"], json.dumps(s, ensure_ascii=False), now)
                    for s in suggestions
                ],
            )

    def load_overrides(self, offer_id: int) -> dict[int, dict]:
        rows = self.con.execute(
            "SELECT item_index, data FROM ai_overrides WHERE offer_id = ?", (offer_id,)
        ).fetchall()
        return {r["item_index"]: json.loads(r["data"]) for r in rows}

    def clear_overrides(self, offer_id: int) -> None:
        with self.con:
            self.con.execute("DELETE FROM ai_overrides WHERE offer_id = ?", (offer_id,))
