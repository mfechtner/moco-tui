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

- Holds settings, API key and draft history
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
