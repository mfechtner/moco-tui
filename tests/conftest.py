import pytest

from moco_tui.store import Settings, Store

OFFERS = [
    {
        "id": 1,
        "identifier": "A2610-001",
        "title": "Website Relaunch",
        "company": {"id": 10, "name": "Acme GmbH"},
        "net_total": 3600,
        "currency": "EUR",
        "invoice_id": None,
    },
    {
        "id": 2,
        "identifier": "A2610-002",
        "title": "Hosting",
        "company": {"id": 11, "name": "Beta AG"},
        "net_total": 900,
        "currency": "EUR",
        "invoice_id": None,
    },
    {
        "id": 3,
        "identifier": "A2610-003",
        "title": "No customer",
        "company": None,
        "net_total": 100,
        "currency": "EUR",
    },
    {
        "id": 4,
        "identifier": "A2610-004",
        "title": "Old",
        "company": {"id": 12, "name": "Gamma"},
        "net_total": 50,
        "currency": "EUR",
        "invoice_id": 99,
    },
]

ITEMS = [
    {"type": "title", "title": "Phase 1"},
    {
        "type": "item",
        "title": "Design",
        "quantity": 3,
        "unit": "d",
        "unit_price": 1200,
        "net_total": 3600,
        "service_type": "service",
        "revenue_category": {"id": 5},
    },
    {"type": "item", "title": "Extra", "optional": True, "net_total": 500},
    {"type": "subtotal", "subtotal_type": "optional_part_total"},
    {"type": "item", "title": "Licence", "net_total": 400, "service_type": "expense"},
]


class FakeMoco:
    """In-memory stand-in for moco_tui.api.Moco."""

    def __init__(self):
        self.posted: list[dict] = []
        self.status_updates: list[tuple] = []
        self.existing_tags = {"Angebot A2610-002"}

    def profile(self):
        return {"firstname": "Test", "lastname": "User"}

    def offers(self, status):
        return [dict(o) for o in OFFERS]

    def offer(self, offer_id):
        o = next(o for o in OFFERS if o["id"] == offer_id)
        return dict(o, vat={"tax": 19.0}, recipient_address="Addr", items=ITEMS)

    def invoices_with_tag(self, tag):
        return [{"id": 1}] if tag in self.existing_tags else []

    def create_invoice(self, payload):
        self.posted.append(payload)
        self.existing_tags.update(payload["tags"])
        return {"id": 500 + len(self.posted)}

    def set_offer_status(self, offer_id, status):
        self.status_updates.append((offer_id, status))


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "test.db")


@pytest.fixture
def cfg():
    return Settings(domain="acme", api_key="key")


@pytest.fixture
def fake():
    return FakeMoco()
