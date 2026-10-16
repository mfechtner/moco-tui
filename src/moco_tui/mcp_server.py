"""Local MCP server (stdio).

Lets Claude Desktop / Claude Code / any MCP client work with your MOCO offers.
Uses the same settings + SQLite store as the TUI.

The client model can write item texts itself (get_time_entries -> set_item_texts),
so no extra AI endpoint is needed. suggest_items uses the configured endpoint.

Start:  moco-tui mcp
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from moco_tui import __version__, ai
from moco_tui.api import Moco
from moco_tui.service import READY, Service, build_invoice
from moco_tui.store import Store

INSTRUCTIONS = """Turn MOCO offers into invoice drafts.
Typical flow:
1. list_offers -> pick offers with state "ready"
2. get_offer + get_time_entries -> understand the work done
3. set_item_texts -> write invoice titles/descriptions per item (or suggest_items)
4. create_invoice_draft with dry_run=true -> check payload
5. create_invoice_draft with dry_run=false -> creates a DRAFT in MOCO (never a final invoice)
Ask the user before step 5."""


def build_server(store: Store | None = None, api: Moco | None = None) -> MCPServer:
    store = store or Store()

    def svc() -> Service:
        cfg = store.load_settings()  # re-read: TUI may have changed settings
        if not cfg.complete:
            raise ToolError("moco-tui is not configured. Run `moco-tui` once to set it up.")
        return Service(api or Moco(cfg.domain, cfg.api_key), store, cfg)

    server = MCPServer(name="moco-tui", version=__version__, instructions=INSTRUCTIONS)

    @server.tool()
    def list_offers(status: str | None = None) -> list[dict]:
        """List offers with their state (ready / draft / linked / nocust).
        status: accepted, sent, created, partially_billed, billed (default from settings)."""
        s = svc()
        out = []
        for o in s.api.offers(status or s.cfg.offer_status):
            out.append(
                {
                    "id": o["id"],
                    "identifier": o.get("identifier"),
                    "title": o.get("title"),
                    "customer": (o.get("company") or {}).get("name"),
                    "net_total": o.get("net_total"),
                    "currency": o.get("currency"),
                    "state": s.check(o),
                }
            )
        return out

    @server.tool()
    def get_offer(offer_id: int) -> dict:
        """Offer items (with index) plus the invoice draft as it would be created now."""
        s = svc()
        o = s.api.offer(offer_id)
        return {
            "id": o["id"],
            "identifier": o.get("identifier"),
            "title": o.get("title"),
            "customer": (o.get("company") or {}).get("name"),
            "project": (o.get("project") or {}).get("name"),
            "items": [
                {
                    "index": i,
                    "type": it.get("type"),
                    "title": it.get("title"),
                    "description": ai.strip_html(it.get("description")),
                    "quantity": it.get("quantity"),
                    "unit": it.get("unit"),
                    "unit_price": it.get("unit_price"),
                    "optional": it.get("optional", False),
                }
                for i, it in enumerate(o.get("items", []))
            ],
            "saved_item_texts": store.load_overrides(offer_id),
            "draft_preview": build_invoice(o, s.cfg, overrides=store.load_overrides(offer_id)),
        }

    @server.tool()
    def get_time_entries(offer_id: int) -> list[dict]:
        """Billable, not yet billed time entries of the offer's project, grouped by task."""
        s = svc()
        return ai.summarize_activities(s.activities_for(s.api.offer(offer_id)))

    @server.tool()
    def set_item_texts(offer_id: int, items: list[dict]) -> dict:
        """Save invoice texts per offer item. Used when the draft is created.
        items: [{"index": int, "title": str, "description": str,
                 "quantity": float | null (optional, replaces offered quantity)}]"""
        s = svc()
        offer_items = s.api.offer(offer_id).get("items", [])
        saved = []
        for x in items:
            i = int(x["index"])
            if not (0 <= i < len(offer_items)) or offer_items[i].get("type") != "item":
                raise ToolError(f"index {i} is not an item of this offer")
            orig = offer_items[i]
            qty = x.get("quantity")
            saved.append(
                ai.Suggestion(
                    index=i,
                    title=x.get("title") or orig.get("title") or "",
                    description=x.get("description") or "",
                    quantity=qty,
                    offered_quantity=orig.get("quantity"),
                    unit=orig.get("unit"),
                    booked_hours=None,
                    note="set via MCP",
                    use_quantity=qty is not None,
                ).to_dict()
            )
        store.save_overrides(offer_id, saved)
        return {"saved": len(saved)}

    @server.tool()
    def suggest_items(offer_id: int, save: bool = False) -> list[dict]:
        """Generate item texts with the configured AI endpoint (from time entries).
        save=true stores them for the draft."""
        s = svc()
        try:
            sugg = [x.to_dict() for x in s.suggest(offer_id)]
        except ai.AIError as e:
            raise ToolError(str(e)) from e
        if save:
            store.save_overrides(offer_id, sugg)
        return sugg

    @server.tool()
    def create_invoice_draft(offer_id: int, dry_run: bool = True) -> dict:
        """Create an invoice DRAFT in MOCO from an offer. dry_run=true only returns the payload.
        Skips offers that already have a draft or invoice."""
        s = svc()
        state = s.check(s.api.offer(offer_id))
        if state != READY:
            return {"skipped": True, "state": state}
        res = s.create_draft(offer_id, dry_run=dry_run)
        if dry_run:
            return {"dry_run": True, "payload": res}
        return {"created": True, "invoice_id": res["id"], "url": s.web_url("invoices", res["id"])}

    @server.tool()
    def draft_history(limit: int = 20) -> list[dict]:
        """Drafts created with moco-tui (newest first)."""
        return [dict(r) for r in store.history(limit)]

    return server


def main() -> None:
    build_server().run("stdio")
