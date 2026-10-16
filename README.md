# moco-tui

Terminal UI to turn [MOCO](https://www.mocoapp.com) offers into **invoice drafts**.

![CI](https://github.com/mfechtner/moco-tui/actions/workflows/ci.yml/badge.svg)

## Install

```bash
pipx install moco-tui        # or: pip install moco-tui
moco-tui
```

First start opens a setup screen. You need:

- **Domain**: `yourcompany` for `yourcompany.mocoapp.com`
- **API key**: MOCO → Profile → Integrations

## Keys

| Key     | Action                          |
| ------- | ------------------------------- |
| `space` | Select / unselect offer         |
| `a`     | Select all ready offers         |
| `n`     | Select none                     |
| `c`     | Create drafts                   |
| `d`     | Toggle dry run (nothing is sent)|
| `g`     | AI suggestions for the offer    |
| `/`     | Filter by no., customer, title  |
| `o`     | Open offer in MOCO              |
| `h`     | History of created drafts       |
| `s`     | Settings                        |
| `r`     | Reload                          |
| `q`     | Quit                            |

## Offer states

| State          | Meaning                              |
| -------------- | ------------------------------------ |
| ● READY        | Can become a draft                   |
| ✓ has draft    | Draft exists already (skipped)       |
| ✓ invoiced     | Offer is linked to an invoice        |
| ✗ no customer  | Assign a customer in MOCO first      |

## What a draft gets

- Customer, project, address, VAT, currency, discount from the offer
- All items (titles, descriptions, subtotals, expenses, revenue categories)
- Optional items: left out (setting)
- Tag `Angebot <offer no.>` → used to prevent duplicates

## AI per item (optional)

Press `g` on an offer. Per item the AI:

- **Writes the description** from booked time entries (billable, not billed yet)
- **Polishes the title** (offer wording → invoice wording)
- **Checks hours vs. offer** and suggests a quantity (h or days, 8 h = 1 day)

You review everything first:

| Key      | Action                          |
| -------- | ------------------------------- |
| `space`  | Accept / skip item              |
| `u`      | Use the suggested quantity      |
| `e`      | Edit title + description        |
| `g`      | Regenerate                      |
| `x`      | Remove all suggestions          |
| `ctrl+s` | Save (used when the draft is created) |

Quantities never change unless you press `u`.

### Setup

Settings (`s`) → AI section. Any **OpenAI-compatible** endpoint works:

| Provider   | Endpoint URL                     | Key   | Model example   |
| ---------- | -------------------------------- | ----- | --------------- |
| OpenAI     | `https://api.openai.com/v1`      | yes   | `gpt-4o-mini`   |
| Ollama     | `http://localhost:11434/v1`      | empty | `llama3.1`      |
| LM Studio  | `http://localhost:1234/v1`       | empty | your model      |
| OpenRouter | `https://openrouter.ai/api/v1`   | yes   | any             |

Env vars override: `MOCO_TUI_AI_BASE_URL`, `MOCO_TUI_AI_API_KEY`, `MOCO_TUI_AI_MODEL`.

Sent to the AI: offer items, task names, booked hours, time-entry descriptions.
Use a local model if that data must stay on your machine.

## MCP server (Claude Desktop / Claude Code)

```bash
moco-tui mcp
```

Runs a local stdio MCP server. Same settings + SQLite as the TUI.

| Tool                   | Does                                               |
| ---------------------- | -------------------------------------------------- |
| `list_offers`          | Offers + state                                     |
| `get_offer`            | Items (with index) + draft preview                 |
| `get_time_entries`     | Booked hours by task                               |
| `set_item_texts`       | Save titles / descriptions / quantity per item     |
| `suggest_items`        | Use the configured AI endpoint                     |
| `create_invoice_draft` | Dry run by default; creates a **draft** only       |
| `draft_history`        | Drafts created so far                              |

The MCP client's own model can write the texts (`get_time_entries` → `set_item_texts`).
No AI endpoint needed for that.

**Claude Desktop** → `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "moco": { "command": "moco-tui", "args": ["mcp"] }
  }
}
```

**Claude Code:**

```bash
claude mcp add moco -- moco-tui mcp
```

## Headless (cron / CI)

```bash
moco-tui run --dry-run       # preview
moco-tui run                 # create drafts for all ready offers
```

`MOCO_DOMAIN` and `MOCO_API_KEY` env vars override stored settings.

## Data store

SQLite, in the OS config folder:

| OS      | Path                                              |
| ------- | ------------------------------------------------- |
| Linux   | `~/.config/moco-tui/moco-tui.db`                  |
| macOS   | `~/Library/Application Support/moco-tui/moco-tui.db` |
| Windows | `%APPDATA%\moco-tui\moco-tui.db`                  |

- Holds settings, API keys, draft history and saved AI item texts
- File is `chmod 600` on Linux/macOS
- `moco-tui where` prints the path
- `MOCO_TUI_DB=/path/file.db` overrides it

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check .
```

## Releases

Version comes from git tags (`hatch-vcs`). No version in code.

| Step | How | Result |
| ---- | --- | ------ |
| 1. Release candidate | `git tag v0.2.0rc1 && git push --tags` | GitHub pre-release + **TestPyPI** |
| 2. Test it | `pipx install -i https://test.pypi.org/simple/ --pip-args="--extra-index-url https://pypi.org/simple/" moco-tui==0.2.0rc1` | |
| 3. Final release | `git tag v0.2.0 && git push --tags` | GitHub release + TestPyPI |
| 4. Promote | Actions → **Promote to PyPI** → enter `v0.2.0` → approve | **PyPI** |

### One-time setup

1. PyPI + TestPyPI: add a *Trusted Publisher* for this repo
   - workflow `release.yml`, environment `testpypi`
   - workflow `promote.yml`, environment `pypi`
2. GitHub → Settings → Environments: create `testpypi` and `pypi`
   - `pypi`: add yourself as *required reviewer* (= manual approval)

## License

AGPL-3.0-or-later
