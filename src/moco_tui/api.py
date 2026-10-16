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

    def invoices_with_tag(self, tag: str) -> list[dict]:
        return self.get_all("/invoices", {"tags": tag, "include_disregarded": "true"})

    def create_invoice(self, payload: dict) -> dict:
        return self.call("POST", "/invoices", json=payload).json()

    def set_offer_status(self, offer_id: int, status: str) -> None:
        self.call("PUT", f"/offers/{offer_id}/update_status", json={"status": status})
