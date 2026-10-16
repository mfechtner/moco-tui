"""Command line entry point.

moco-tui                  open the TUI
moco-tui run [--dry-run]  headless: create drafts for all ready offers (cron / CI)
moco-tui where            print path of the SQLite store
moco-tui mcp              run local MCP server (stdio) for Claude Desktop / Code
"""

from __future__ import annotations

import argparse
import sys

from moco_tui import __version__
from moco_tui.store import Store


def _run(store: Store, dry_run: bool, status: str | None) -> int:
    from moco_tui.api import Moco
    from moco_tui.service import READY, Service

    cfg = store.load_settings()
    if not cfg.complete:
        print(
            "Not configured. Start `moco-tui` once, or set MOCO_DOMAIN + MOCO_API_KEY.",
            file=sys.stderr,
        )
        return 2
    svc = Service(Moco(cfg.domain, cfg.api_key), store, cfg)
    offers = svc.api.offers(status or cfg.offer_status)
    print(f"{len(offers)} offer(s) found.")
    errors = 0
    for o in offers:
        label = f"{o.get('identifier')} ({o.get('title')})"
        try:
            state = svc.check(o)
            if state != READY:
                print(f"SKIP  {label}: {state}")
                continue
            res = svc.create_draft(o["id"], dry_run=dry_run)
            if dry_run:
                print(f"DRY   {label}: {len(res['items'])} items")
            elif res:
                print(f"OK    {label} -> draft {res['id']}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"FAIL  {label}: {e}", file=sys.stderr)
    return 1 if errors else 0


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="moco-tui", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--version", action="version", version=f"moco-tui {__version__}")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="create drafts without UI")
    r.add_argument("--dry-run", action="store_true", help="show, don't create")
    r.add_argument("--status", help="offer status (default: from settings)")
    sub.add_parser("where", help="print path of the SQLite store")
    sub.add_parser("mcp", help="run local MCP server (stdio)")
    args = ap.parse_args(argv)

    if args.cmd == "mcp":
        from moco_tui.mcp_server import main as mcp_main

        mcp_main()
        return
    store = Store()
    if args.cmd == "where":
        print(store.path)
    elif args.cmd == "run":
        sys.exit(_run(store, args.dry_run, args.status))
    else:
        from moco_tui.app import MocoApp

        MocoApp(store).run()


if __name__ == "__main__":
    main()
