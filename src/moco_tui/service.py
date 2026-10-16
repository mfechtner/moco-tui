"""Offer -> invoice draft logic. No UI here."""

from __future__ import annotations

from datetime import date, timedelta

from moco_tui.api import Moco
from moco_tui.store import Settings, Store

# offer state keys
READY, HAS_DRAFT, INVOICED, NO_CUSTOMER = "ready", "draft", "linked", "nocust"


def map_item(it: dict, include_optional: bool) -> dict | None:
    """Offer item -> invoice item. None = skip."""
    t = it.get("type")
    if it.get("optional") and not include_optional:
        return None
    if t == "subtotal":
        st = it.get("subtotal_type") or "sub_total"
        if st.startswith("optional_"):
            if not include_optional:
                return None
            st = st.removeprefix("optional_")
        return {"type": "subtotal", "subtotal_type": st, "title": it.get("title")}
    if t in ("separator", "page-break"):
        return {"type": t}
    if t == "title":
        return {"type": "title", "title": it.get("title")}
    if t == "description":
        return {"type": "description", "description": it.get("description")}
    if t == "item":
        new = {"type": "item", "title": it.get("title")}
        if it.get("description"):
            new["description"] = it["description"]
        if it.get("unit_price") and it.get("quantity"):
            new.update(quantity=it["quantity"], unit=it.get("unit"), unit_price=it["unit_price"])
        else:
            new["net_total"] = it.get("net_total") or 0
        if it.get("service_type") == "expense":
            new["additional"] = True
        if it.get("optional"):
            new["optional"] = True
        if it.get("revenue_category"):
            new["revenue_category_id"] = it["revenue_category"]["id"]
        return new
    return None


def tag_for(offer: dict, cfg: Settings) -> str:
    return f"{cfg.tag_prefix} {offer['identifier']}"


def build_invoice(offer: dict, cfg: Settings, today: date | None = None) -> dict:
    today = today or date.today()
    company = offer.get("company") or {}
    project = offer.get("project") or {}
    vat = offer.get("vat") or {}
    items = [i for i in (map_item(x, cfg.include_optional) for x in offer.get("items", [])) if i]
    payload = {
        "status": "draft",
        "customer_id": company.get("id"),
        "recipient_address": offer.get("recipient_address"),
        "date": today.isoformat(),
        "due_date": (today + timedelta(days=cfg.due_days)).isoformat(),
        "title": f"{cfg.title_prefix} – {offer.get('title')}",
        "tax": vat.get("tax", offer.get("tax")),
        "currency": offer.get("currency"),
        "discount": offer.get("discount") or 0,
        "tags": [tag_for(offer, cfg)],
        "items": items,
    }
    if project.get("id"):
        payload["project_id"] = project["id"]
    return payload


class Service:
    def __init__(self, api: Moco, store: Store, cfg: Settings):
        self.api, self.store, self.cfg = api, store, cfg

    def check(self, offer: dict) -> str:
        """State of an offer. Local DB first, then MOCO (tag search)."""
        if offer.get("invoice_id"):
            return INVOICED
        if not (offer.get("company") or {}).get("id"):
            return NO_CUSTOMER
        if self.store.has_draft(offer["id"]):
            return HAS_DRAFT
        if self.api.invoices_with_tag(tag_for(offer, self.cfg)):
            return HAS_DRAFT
        return READY

    def web_url(self, kind: str, obj_id: int) -> str:
        """Link to MOCO web app, kind = 'offers' or 'invoices'."""
        return f"https://{self.cfg.domain}.mocoapp.com/{kind}/{obj_id}"

    def create_draft(self, offer_id: int, dry_run: bool = False) -> dict | None:
        """Create one draft. Returns the invoice (or payload on dry run), None if skipped."""
        offer = self.api.offer(offer_id)
        if self.check(offer) != READY:
            return None
        payload = build_invoice(offer, self.cfg)
        if dry_run:
            return payload
        inv = self.api.create_invoice(payload)
        self.store.add_draft(offer, inv["id"])
        if self.cfg.mark_offer_billed:
            self.api.set_offer_status(offer_id, "billed")
        return inv
