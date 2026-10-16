import pytest

from moco_tui.invoices import InvoiceService, invoice_to_payload, net_total


@pytest.fixture
def isvc(fake, store):
    return InvoiceService(fake, store, "acme")


def test_payload_keeps_everything(fake):
    p = invoice_to_payload(fake.invoice(900))
    assert p["status"] == "draft"
    assert p["customer_id"] == 10 and p["project_id"] == 77
    assert p["salutation"] == "<div>Hallo</div>"
    assert p["tags"] == ["Angebot A2610-009"]
    beratung = p["items"][1]
    assert beratung == {
        "type": "item",
        "title": "Beratung",
        "description": "<div>Workshop</div>",
        "quantity": 2,
        "unit": "h",
        "unit_price": 100,
        "revenue_category_id": 5,
    }
    assert p["items"][2] == {"type": "item", "title": "Pauschale", "net_total": 50}
    assert "id" not in beratung  # ids belong to the old draft


def test_editability(fake, isvc):
    assert isvc.editability(fake.invoice(900)).ok
    assert "time entries" in isvc.editability(fake.invoice(901)).reason
    assert "reversal" in isvc.editability(fake.invoice(902)).reason


def test_replace_creates_first_then_deletes(fake, store, isvc):
    store.add_draft({"id": 1, "identifier": "A1"}, 900)
    old = fake.invoice(900)
    edited = dict(old, title="Neu", items=old["items"][:2])
    new, warning = isvc.replace_draft(old, edited)
    assert warning is None
    assert fake.posted[0]["title"] == "Neu" and len(fake.posted[0]["items"]) == 2
    assert fake.deleted == [900]
    assert store.history()[0]["invoice_id"] == new["id"]


def test_replace_keeps_new_if_delete_fails(fake, isvc, monkeypatch):
    def boom(_):
        raise RuntimeError("nope")

    monkeypatch.setattr(fake, "delete_invoice", boom)
    new, warning = isvc.replace_draft(fake.invoice(900), dict(fake.invoice(900)))
    assert new["id"] in fake.invoices_db and "not deleted" in warning


def test_replace_refuses_final(fake, isvc):
    with pytest.raises(ValueError):
        isvc.replace_draft(fake.invoice(902), fake.invoice(902))


def test_net_total_skips_optional():
    items = [
        {"type": "item", "quantity": 2, "unit_price": 10},
        {"type": "item", "net_total": 5},
        {"type": "item", "net_total": 100, "optional": True},
        {"type": "title", "title": "x"},
    ]
    assert net_total(items) == 25
