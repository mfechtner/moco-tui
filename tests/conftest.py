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

ACTIVITIES = [
    {
        "hours": 10,
        "description": "Wireframes",
        "billable": True,
        "billed": False,
        "task": {"name": "Design"},
    },
    {
        "hours": 18,
        "description": "Screen design",
        "billable": True,
        "billed": False,
        "task": {"name": "Design"},
    },
    {
        "hours": 5,
        "description": "Old work",
        "billable": True,
        "billed": True,
        "task": {"name": "Design"},
    },
    {
        "hours": 2,
        "description": "Internal",
        "billable": False,
        "billed": False,
        "task": {"name": "Meeting"},
    },
]


class FakeAI:
    """Stands in for ai.AIClient. Returns a fixed JSON answer."""

    def __init__(self, reply: str | None = None):
        self.calls: list[tuple[str, str]] = []
        self.reply = reply or (
            '```json\n{"items":[{"index":1,"title":"Design umgesetzt",'
            '"description":"Wireframes erstellt\\nScreendesign erstellt",'
            '"booked_hours":28,"note":""}]}\n```'
        )

    def chat(self, system, user):
        self.calls.append((system, user))
        return self.reply


def make_invoices():
    base = {
        "customer_id": 10,
        "customer": {"id": 10, "name": "Acme GmbH"},
        "project_id": 77,
        "recipient_address": "Acme GmbH\r\nStr. 1",
        "date": "2026-10-01",
        "due_date": "2026-10-15",
        "tax": 19.0,
        "currency": "EUR",
        "discount": 0,
        "salutation": "<div>Hallo</div>",
        "footer": "<div>Danke</div>",
        "tags": ["Angebot A2610-009"],
    }
    items = [
        {"id": 1, "type": "title", "title": "Leistungen"},
        {
            "id": 2,
            "type": "item",
            "title": "Beratung",
            "quantity": 2,
            "unit": "h",
            "unit_price": 100,
            "net_total": 200,
            "description": "<div>Workshop</div>",
            "revenue_category": {"id": 5},
        },
        {"id": 3, "type": "item", "title": "Pauschale", "net_total": 50},
    ]
    return {
        900: dict(
            base,
            id=900,
            identifier=None,
            title="Entwurf A",
            status="draft",
            net_total=250,
            items=[dict(i) for i in items],
        ),
        901: dict(
            base,
            id=901,
            identifier=None,
            title="Entwurf mit Zeiten",
            status="draft",
            net_total=250,
            items=[dict(i) for i in items],
        ),
        902: dict(
            base,
            id=902,
            identifier="R2610-001",
            title="Final",
            status="sent",
            net_total=250,
            items=[dict(i) for i in items],
        ),
    }


class FakeMoco:
    """In-memory stand-in for moco_tui.api.Moco."""

    def __init__(self):
        self.invoices_db = make_invoices()
        self.deleted: list[int] = []
        self.posted: list[dict] = []
        self.status_updates: list[tuple] = []
        self.existing_tags = {"Angebot A2610-002"}
        self.activity_calls: list[tuple] = []

    def profile(self):
        return {"firstname": "Test", "lastname": "User"}

    def offers(self, status):
        return [dict(o) for o in OFFERS]

    def offer(self, offer_id):
        o = next(o for o in OFFERS if o["id"] == offer_id)
        return dict(
            o,
            vat={"tax": 19.0},
            recipient_address="Addr",
            items=ITEMS,
            project={"id": 77, "name": "Relaunch"},
            date="2026-09-01",
        )

    def activities(self, project_id, date_from, date_to):
        self.activity_calls.append((project_id, date_from, date_to))
        return ACTIVITIES

    def invoices_with_tag(self, tag):
        return [{"id": 1}] if tag in self.existing_tags else []

    def invoices(self, status=None):
        return [
            {k: v for k, v in i.items() if k != "items"}
            for i in self.invoices_db.values()
            if not status or i["status"] == status
        ]

    def invoice(self, invoice_id):
        return self.invoices_db[invoice_id]

    def invoice_timesheet(self, invoice_id):
        return [{"id": 1, "hours": 2}] if invoice_id == 901 else []

    def delete_invoice(self, invoice_id):
        self.deleted.append(invoice_id)
        self.invoices_db.pop(invoice_id)

    def create_invoice(self, payload):
        self.posted.append(payload)
        new_id = 500 + len(self.posted)
        self.invoices_db[new_id] = dict(
            payload,
            id=new_id,
            identifier=None,
            customer={"id": payload.get("customer_id"), "name": "Acme GmbH"},
        )
        self.existing_tags.update(payload["tags"])
        return {"id": new_id}

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
