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
@pytest.mark.parametrize("start", ["shipment_date", "collection_arrival", "warehouse_arrival", "reconciliation_date"])
def test_confirmed_supplier_terms_are_frozen_and_payment_anchors_are_explicit(world, start):
    buyer = internal_user(world, f"terms-{start}")
    supplier = world["supplier"]
    today = business_date()
    supplier.payment_term_days = 0
    supplier.payment_term_start = start
    supplier.save(update_fields=["payment_term_days", "payment_term_start"])
    order = confirmed_order(world, buyer, key=f"terms-order-{start}", payload=po_payload(
        world, number=f"PO-TERMS-{start}", order_date=today,
    ))

    # Later archive edits may only affect future confirmations.
    supplier.payment_term_days = 37
    supplier.payment_term_start = "unspecified"
    supplier.save(update_fields=["payment_term_days", "payment_term_start"])
    assert order.supplier_terms_snapshot["days"] == 0
    assert order.supplier_terms_snapshot["start"] == start

    shipment = services.create_supplier_shipment(buyer, shipment_payload(
        world, order, f"terms-shipment-{start}", number=f"SH-TERMS-{start}", shipment_date=today,
    ), idempotency_key=f"terms-shipment-{start}")

    if start == "collection_arrival":
        occurred = datetime.combine(today, time(9), tzinfo=timezone.utc)
        services.mark_collection_arrival(buyer, shipment.pk, expected_version=shipment.version,
            occurred_at=occurred, idempotency_key=f"terms-collection-{start}")
    elif start == "warehouse_arrival":
        carrier = freight(world)
        batch = services.create_dispatch_batch(buyer, {
            "number": f"DB-TERMS-{start}", "freight_company_id": carrier.pk,
            "freight_number": f"F-TERMS-{start}", "shipment_ids": [shipment.pk],
        }, idempotency_key=f"terms-batch-{start}")
        for stage, hour in (("departed", 10), ("arrived_port", 11), ("arrived_warehouse", 12)):
            services.mark_logistics_stage(buyer, batch.pk, stage=stage,
                occurred_at=datetime.combine(today, time(hour), tzinfo=timezone.utc),
                expected_version=batch.version, idempotency_key=f"terms-{stage}-{start}")
            batch.refresh_from_db()

    terms = terms_context(buyer, shipment)
    assert terms["state"] == "frozen"
    assert terms["days"] == 0 and terms["start"] == start
    if start == "reconciliation_date":
        assert terms["anchor_date"] is None and terms["due_date"] is None
        assert terms["message"] == "待确认对账日期，暂不推算到期日。"
    else:
        assert terms["anchor_date"] == today.isoformat()
        assert terms["due_date"] == today.isoformat(), "zero-day terms mature on the anchor date"


@pytest.mark.django_db
def test_historical_confirmed_order_without_terms_snapshot_is_reported_as_unrecorded(world):
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
    assert terms["state"] == "unrecorded"
    assert terms["anchor_date"] is None and terms["due_date"] is None
    assert terms["message"] == "历史采购单未记录账期约定。"
