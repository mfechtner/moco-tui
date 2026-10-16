from datetime import date

from conftest import ITEMS, OFFERS

from moco_tui.service import (
    HAS_DRAFT,
    INVOICED,
    NO_CUSTOMER,
    READY,
    Service,
    build_invoice,
    map_item,
)


def test_build_invoice(fake, cfg):
    inv = build_invoice(fake.offer(1), cfg, today=date(2026, 10, 16))
    assert inv["status"] == "draft"
    assert inv["customer_id"] == 10
    assert inv["due_date"] == "2026-10-30"
    assert inv["tax"] == 19.0
    assert inv["tags"] == ["Angebot A2610-001"]
    titles = [i.get("title") for i in inv["items"]]
    assert "Extra" not in titles  # optional dropped
    design = next(i for i in inv["items"] if i.get("title") == "Design")
    assert design["revenue_category_id"] == 5
    licence = next(i for i in inv["items"] if i.get("title") == "Licence")
    assert licence == {"type": "item", "title": "Licence", "net_total": 400, "additional": True}


def test_optional_included(cfg):
    cfg.include_optional = True
    mapped = [map_item(i, True) for i in ITEMS]
    assert {"type": "subtotal", "subtotal_type": "part_total", "title": None} in mapped
    assert any(m and m.get("optional") for m in mapped)


def test_check_states(fake, store, cfg):
    svc = Service(fake, store, cfg)
    states = {o["id"]: svc.check(o) for o in OFFERS}
    assert states == {1: READY, 2: HAS_DRAFT, 3: NO_CUSTOMER, 4: INVOICED}


def test_create_and_no_duplicate(fake, store, cfg):
    svc = Service(fake, store, cfg)
    inv = svc.create_draft(1)
    assert inv["id"] == 501
    assert store.has_draft(1)
    assert svc.create_draft(1) is None
    assert len(fake.posted) == 1


def test_dry_run_creates_nothing(fake, store, cfg):
    svc = Service(fake, store, cfg)
    payload = svc.create_draft(1, dry_run=True)
    assert payload["status"] == "draft"
    assert fake.posted == []
    assert not store.has_draft(1)


def test_mark_billed(fake, store, cfg):
    cfg.mark_offer_billed = True
    Service(fake, store, cfg).create_draft(1)
    assert fake.status_updates == [(1, "billed")]
