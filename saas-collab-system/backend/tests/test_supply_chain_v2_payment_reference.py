from datetime import datetime, time, timedelta, timezone

import pytest
from rest_framework.test import APIClient

from apps.supply_chain import services
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import PurchaseOrder, domain_write
from tests.test_supply_chain_v2_foundation import (
    confirmed_order, freight, internal_user, po_payload, shipment_payload, world,
)

BASE = "/api/internal/supply-chain/v2/"


def terms_context(user, shipment):
    client = APIClient()
    client.force_authenticate(user=user)
    response = client.get(BASE + f"costs/shipment/{shipment.pk}/")
    assert response.status_code == 200, response.data
    return response.data["data"]["settlement"]["payment_terms"]


@pytest.mark.django_db
@pytest.mark.parametrize("po_start", ["shipment_date", "collection_arrival", "warehouse_arrival", "reconciliation_date"])
def test_shipment_terms_are_frozen_from_supplier_archive_and_start_on_shipment_date(world, po_start):
    buyer = internal_user(world, f"terms-{po_start}")
    supplier = world["supplier"]
    today = business_date()
    supplier.payment_term_days = 0
    supplier.payment_term_start = po_start
    supplier.save(update_fields=["payment_term_days", "payment_term_start"])
    order = confirmed_order(world, buyer, key=f"terms-order-{po_start}", payload=po_payload(
        world, number=f"PO-TERMS-{po_start}", order_date=today,
    ))

    assert order.supplier_terms_snapshot == {}

    shipment = services.create_supplier_shipment(buyer, shipment_payload(
        world, order, f"terms-shipment-{po_start}", number=f"SH-TERMS-{po_start}", shipment_date=today,
    ), idempotency_key=f"terms-shipment-{po_start}")
    supplier.payment_term_days = 37
    supplier.payment_term_start = "unspecified"
    supplier.save(update_fields=["payment_term_days", "payment_term_start"])

    terms = terms_context(buyer, shipment)
    assert terms["state"] == "adjusted"
    assert terms["days"] == 0 and terms["start"] == "shipment_date"
    assert terms["anchor_date"] == today.isoformat()
    assert terms["due_date"] == today.isoformat(), "zero-day terms mature on the shipment date"


@pytest.mark.django_db
def test_shipment_terms_do_not_fall_back_to_historical_po_snapshot(world):
    buyer = internal_user(world, "terms-historical")
    supplier = world["supplier"]
    supplier.payment_term_days = 30
    supplier.payment_term_start = "shipment_date"
    supplier.save(update_fields=["payment_term_days", "payment_term_start"])
    today = business_date()
    order = confirmed_order(world, buyer, key="terms-historical-order", payload=po_payload(
        world, number="PO-TERMS-HISTORICAL", order_date=today,
    ))
    # Model a legacy confirmation created before snapshots were introduced.
    with domain_write():
        order.supplier_terms_snapshot = {}
        order.save(update_fields=["supplier_terms_snapshot"])
    shipment = services.create_supplier_shipment(buyer, shipment_payload(
        world, order, "terms-historical-shipment", shipment_date=today,
    ), idempotency_key="terms-historical-shipment")

    terms = terms_context(buyer, shipment)
    assert terms["state"] == "adjusted"
    assert terms["days"] == 30 and terms["start"] == "shipment_date"
    assert terms["anchor_date"] == today.isoformat()
    assert terms["due_date"] == (today + timedelta(days=30)).isoformat()


@pytest.mark.parametrize('days', [60, None])
def test_historical_shipment_terms_override_is_consistent_with_due_reminders(world, days):
    from apps.supply_chain.payment_terms import save_terms, terms_data
    buyer = internal_user(world, 'terms-import-override')
    order = confirmed_order(world, buyer)
    with domain_write():
        order.supplier_terms_snapshot = {}
        order.save(update_fields=['supplier_terms_snapshot'])
    today = business_date()
    shipment = services.create_supplier_shipment(buyer,
        shipment_payload(world, order, 'override-shipment', shipment_date=today),
        idempotency_key='override-shipment')
    save_terms(buyer, 'shipment', shipment.pk, {'expected_version': 1, 'days': days,
        'start': 'shipment_date', 'reminder_days': 7, 'reconciliation_date': None,
        'due_date_override': None, 'reason': '历史源表账期从供应商发货日起算'}, 'override-terms')
    reference = terms_context(buyer, shipment)
    panel = terms_data(buyer, 'shipment', shipment.pk)
    assert reference['state'] == 'adjusted'
    assert reference['anchor_date'] == panel['anchor_date'] == today.isoformat()
    assert reference['due_date'] == panel['due_date'] == ((today + timedelta(days=days)).isoformat() if days is not None else None)
