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
| `enter` | Open offer details (tabs: overview, items, time, draft) |
| `space` | Select / unselect offer         |
| `a`     | Select all ready offers         |
| `n`     | Select none                     |
| `c`     | Create drafts                   |
| `d`     | Toggle dry run (nothing is sent)|
| `g`     | AI suggestions for the offer    |
| `/`     | Filter by no., customer, title  |
| `o`     | Open offer in MOCO              |
| `t`     | Change offer status             |
| `i`     | Invoices (list, details, edit drafts) |
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

## Invoices (`i`)

- List by status: draft, created, sent, overdue, partially paid, paid, ignored
- `enter` → details: overview, items, texts, payments
- `e` → **edit a draft**

### Actions

| Key | Offers (in details)        | Invoices (in details)                         |
| --- | -------------------------- | --------------------------------------------- |
| `t` | Status: created · sent · accepted · partially billed · billed · archived | Status: created · sent · overdue · ignored (not drafts) |
| `m` | Send by email              | Send by email (not drafts)                    |
| `p` | Download PDF               | Download PDF                                  |
| `P` | –                          | Download timesheet PDF                        |
| `b` | –                          | Record payment (default: open amount)         |
| `r` | –                          | Create payment reminder                       |
| `x` | –                          | Delete (draft: confirm · final: reason required) |
| `e` | –                          | Edit draft                                    |

- Email: empty "To" = default recipients set in MOCO
- PDFs go to your Downloads folder, never overwriting
- "paid" is set by MOCO when payments cover the total
- Keys that don't apply are hidden

### Edit a draft

| Tab              | What you can change                                 |
| ---------------- | --------------------------------------------------- |
| 1 Header & texts | title, dates, service period, discount, address, intro, footer |
| 2 Items          | `a` add · `e`/`enter` edit · `d` delete · `shift+↑↓` move |

`ctrl+s` saves. MOCO's API cannot update invoices, so saving:

1. creates a **new draft** with your changes
2. deletes the old draft

New first → if anything fails, nothing is lost.

**Read-only:**

- Final invoices (only a reversal may change them)
- Drafts with linked time entries or expenses (recreating would drop the links → edit in MOCO)

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

Settings (`s`) → AI → pick a **provider**, paste the key, set the model.
Endpoint URL can stay empty (provider default).

| Provider        | Format                 | Key   | Model example        |
| --------------- | ---------------------- | ----- | -------------------- |
| Anthropic       | native Messages API    | yes   | `claude-sonnet-5-5`  |
| OpenAI          | chat/completions       | yes   | your model           |
| Google Gemini   | OpenAI-compatible      | yes   | your model           |
| Mistral         | OpenAI-compatible      | yes   | your model           |
| OpenRouter      | OpenAI-compatible      | yes   | `vendor/model`       |
| Groq            | OpenAI-compatible      | yes   | your model           |
| Ollama          | local                  | no    | `llama3.1`           |
| LM Studio       | local                  | no    | loaded model         |
| Custom          | any OpenAI-compatible  | opt.  | –                    |

- No `temperature` is sent (newer models reject it).
- If a provider rejects an optional parameter, the request is retried without it.
- Anthropic's OpenAI-compatible endpoint also works via **Custom**.

Env vars override: `MOCO_TUI_AI_PROVIDER`, `MOCO_TUI_AI_BASE_URL`,
`MOCO_TUI_AI_API_KEY`, `MOCO_TUI_AI_MODEL`.

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
| `list_invoices` / `get_invoice` | Invoices by status / full invoice      |
| `set_offer_status` / `set_invoice_status` | Change status                |
| `send_offer_email` / `send_invoice_email` | Send by email                |
| `record_payment` / `create_reminder` | Payments and reminders            |

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
