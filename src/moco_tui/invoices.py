"""Invoices: read, and edit drafts.

MOCO's REST API cannot update an invoice. Drafts can be deleted, so an edit is:
create a new draft with the changed data, then delete the old draft.
Create first: if anything fails, the old draft is still there.

Not editable here:
- final invoices (only a reversal may change them)
- drafts with linked time entries or expenses (recreating would drop the links)
"""

from __future__ import annotations

from dataclasses import dataclass

from moco_tui.ai import strip_html, to_html
from moco_tui.api import Moco
from moco_tui.store import Store

INVOICE_STATUSES = ["draft", "created", "sent", "overdue", "partially_paid", "paid", "ignored"]

# fields copied 1:1 when a draft is recreated
HEADER_FIELDS = [
    "customer_id",
    "project_id",
    "recipient_address",
    "date",
    "due_date",
    "service_period_from",
    "service_period_to",
    "title",
    "tax",
    "currency",
    "discount",
    "cash_discount",
    "cash_discount_days",
    "salutation",
    "footer",
    "tags",
    "custom_properties",
]

ITEM_TYPES = ["item", "title", "description", "subtotal", "separator", "page-break"]


@dataclass
class Editability:
    ok: bool
    reason: str = ""


def item_to_payload(it: dict) -> dict:
    """Invoice item (as returned by GET) -> item for POST /invoices."""
    t = it.get("type") or "item"
    if t in ("separator", "page-break"):
        return {"type": t}
    if t == "title":
        return {"type": "title", "title": it.get("title") or ""}
    if t == "description":
        return {"type": "description", "description": it.get("description") or ""}
    if t == "subtotal":
        return {
            "type": "subtotal",
            "subtotal_type": it.get("subtotal_type") or "sub_total",
            "title": it.get("title"),
        }
    out = {"type": "item", "title": it.get("title") or ""}
    if it.get("description"):
        out["description"] = it["description"]
    if it.get("unit_price") is not None and it.get("quantity") is not None:
        out.update(quantity=it["quantity"], unit=it.get("unit"), unit_price=it["unit_price"])
    else:
        out["net_total"] = it.get("net_total") or 0
    if it.get("additional") or it.get("service_type") == "expense":
        out["additional"] = True
    if it.get("optional"):
        out["optional"] = True
    rc = it.get("revenue_category")
    if isinstance(rc, dict) and rc.get("id"):
        out["revenue_category_id"] = rc["id"]
    elif it.get("revenue_category_id"):
        out["revenue_category_id"] = it["revenue_category_id"]
    return out


def invoice_to_payload(inv: dict) -> dict:
    payload = {k: inv[k] for k in HEADER_FIELDS if inv.get(k) not in (None, "", [], {})}
    if "customer_id" not in payload and (inv.get("customer") or {}).get("id"):
        payload["customer_id"] = inv["customer"]["id"]
    if "project_id" not in payload and (inv.get("project") or {}).get("id"):
        payload["project_id"] = inv["project"]["id"]
    if "tax" not in payload and isinstance(inv.get("vat"), dict):
        payload["tax"] = inv["vat"].get("tax")
    payload["status"] = "draft"
    payload["items"] = [item_to_payload(i) for i in inv.get("items", [])]
    return payload


def item_amount(it: dict) -> float:
    if it.get("type") != "item" or it.get("optional"):
        return 0.0
    if it.get("unit_price") is not None and it.get("quantity") is not None:
        return float(it["quantity"]) * float(it["unit_price"])
    return float(it.get("net_total") or 0)


def net_total(items: list[dict]) -> float:
    return round(sum(item_amount(i) for i in items), 2)


def plain(html: str | None) -> str:
    return strip_html(html)


def rich(text: str) -> str:
    return to_html(text)


class InvoiceService:
    def __init__(self, api: Moco, store: Store, domain: str):
        self.api, self.store, self.domain = api, store, domain

    def web_url(self, invoice_id: int) -> str:
        return f"https://{self.domain}.mocoapp.com/invoices/{invoice_id}"

    def editability(self, inv: dict) -> Editability:
        if inv.get("status") != "draft":
            return Editability(False, "Only drafts can be edited. Final invoices need a reversal.")
        if any(i.get("expense_ids") for i in inv.get("items", [])):
            return Editability(False, "Draft has linked expenses. Edit it in MOCO.")
        try:
            if self.api.invoice_timesheet(inv["id"]):
                return Editability(False, "Draft has linked time entries. Edit it in MOCO.")
        except Exception:  # noqa: BLE001  (no timesheet endpoint result = treat as none)
            pass
        return Editability(True)

    def replace_draft(self, old: dict, edited: dict) -> tuple[dict, str | None]:
        """Create the edited draft, then delete the old one.
        Returns (new invoice, warning). Warning is set if the old draft could not be deleted."""
        if old.get("status") != "draft":
            raise ValueError("Only drafts can be replaced.")
        new = self.api.create_invoice(invoice_to_payload(edited))
        warning = None
        try:
            self.api.delete_invoice(old["id"])
        except Exception as e:  # noqa: BLE001
            warning = (
                f"New draft {new.get('id')} created, but old draft {old['id']} not deleted: {e}"
            )
        self.store.remap_draft(old["id"], new["id"])
        return new, warning
