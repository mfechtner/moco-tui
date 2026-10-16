"""Small MOCO API client."""

from __future__ import annotations

import time

import requests


class MocoError(RuntimeError):
    pass


class Moco:
    def __init__(self, domain: str, api_key: str, session: requests.Session | None = None):
        self.base = f"https://{domain}.mocoapp.com/api/v1"
        self.s = session or requests.Session()
        self.s.headers.update(
            {
                "Authorization": f"Token token={api_key}",
                "Content-Type": "application/json",
            }
        )

    def call(self, method: str, path: str, **kw) -> requests.Response:
        """Request with retry on rate limit (429)."""
        for _ in range(5):
            r = self.s.request(method, self.base + path, timeout=30, **kw)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", 5)))
                continue
            if r.status_code >= 400:
                raise MocoError(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
            return r
        raise MocoError(f"{method} {path} -> still rate limited")

    def get_all(self, path: str, params: dict | None = None) -> list[dict]:
        """GET with pagination."""
        params = dict(params or {}, page=1)
        out: list[dict] = []
        while True:
            r = self.call("GET", path, params=params)
            out += r.json()
            if 'rel="next"' not in r.headers.get("Link", ""):
                return out
            params["page"] += 1

    # ---- endpoints ----
    def profile(self) -> dict:
        return self.call("GET", "/profile").json()

    def offers(self, status: str) -> list[dict]:
        return self.get_all("/offers", {"status": status})

    def offer(self, offer_id: int) -> dict:
        return self.call("GET", f"/offers/{offer_id}").json()

    def activities(self, project_id: int, date_from: str, date_to: str) -> list[dict]:
        return self.get_all(
            "/activities", {"project_id": project_id, "from": date_from, "to": date_to}
        )

    def invoices_with_tag(self, tag: str) -> list[dict]:
        return self.get_all("/invoices", {"tags": tag, "include_disregarded": "true"})

    def invoices(self, status: str | None = None) -> list[dict]:
        return self.get_all("/invoices", {"status": status} if status else {})

    def invoice(self, invoice_id: int) -> dict:
        return self.call("GET", f"/invoices/{invoice_id}").json()

    def invoice_timesheet(self, invoice_id: int) -> list[dict]:
        return self.call("GET", f"/invoices/{invoice_id}/timesheet").json()

    def delete_invoice(self, invoice_id: int, reason: str | None = None) -> None:
        """Drafts: no reason needed. Final invoices: MOCO requires a reason."""
        self.call("DELETE", f"/invoices/{invoice_id}", json={"reason": reason} if reason else None)

    def create_invoice(self, payload: dict) -> dict:
        return self.call("POST", "/invoices", json=payload).json()

    def set_offer_status(self, offer_id: int, status: str) -> None:
        self.call("PUT", f"/offers/{offer_id}/update_status", json={"status": status})

    # ---- offer actions
    def send_offer_email(self, offer_id: int, **mail) -> dict:
        """mail: subject, text, emails_to, emails_cc, emails_bcc (empty -> MOCO defaults)."""
        return self.call("POST", f"/offers/{offer_id}/send_email", json=clean(mail)).json()

    def offer_pdf(self, offer_id: int) -> bytes:
        return self.call("GET", f"/offers/{offer_id}.pdf").content

    # ---- invoice actions
    def set_invoice_status(self, invoice_id: int, status: str) -> None:
        """created, sent, overdue, ignored. Not possible for drafts."""
        self.call("PUT", f"/invoices/{invoice_id}/update_status", json={"status": status})

    def send_invoice_email(self, invoice_id: int, **mail) -> dict:
        return self.call("POST", f"/invoices/{invoice_id}/send_email", json=clean(mail)).json()

    def invoice_pdf(self, invoice_id: int) -> bytes:
        return self.call("GET", f"/invoices/{invoice_id}.pdf").content

    def invoice_timesheet_pdf(self, invoice_id: int) -> bytes:
        return self.call("GET", f"/invoices/{invoice_id}/timesheet.pdf").content

    def create_payment(
        self, invoice_id: int, date: str, paid_total: float, description: str = ""
    ) -> dict:
        body = {"invoice_id": invoice_id, "date": date, "paid_total": paid_total}
        if description:
            body["description"] = description
        return self.call("POST", "/invoices/payments", json=body).json()

    def create_reminder(self, invoice_id: int, **fields) -> dict:
        """fields: title, text, fee, date, due_date (empty -> MOCO defaults)."""
        body = {"invoice_id": invoice_id, **clean(fields)}
        return self.call("POST", "/invoice_reminders", json=body).json()


def clean(d: dict) -> dict:
    """Drop empty values so MOCO uses its defaults."""
    return {k: v for k, v in d.items() if v not in (None, "", [])}
