from datetime import date, datetime
from types import SimpleNamespace

from django.utils import timezone

from apps.supply_chain.document_time import document_time


def test_purchase_source_date_is_validated_and_falls_back_to_order_date():
    obj = SimpleNamespace(creation_key='PHHIST20261103:po:1', reference_number='PHCG261102001', order_date=date(2026, 10, 31), created_at=timezone.now())
    assert document_time('purchase', obj) == '2026-11-02'
    obj.reference_number = 'PHCG261332001'
    assert document_time('purchase', obj) == '2026-10-31'


def test_historical_inbound_timestamp_requires_historical_key_and_valid_source_number():
    obj = SimpleNamespace(creation_key='PHHIST20261103:batch:1',
        notes='import row\n{"入库单号":"PO20261102153045"} appended note', departed_at=None)
    assert document_time('batch', obj) == '2026-11-02T15:30:45+08:00'
    obj.creation_key = 'random-batch-20261103'
    assert document_time('batch', obj) is None
    obj.creation_key = 'PHSUP20261103:batch:1'
    obj.notes = 'import row\n{"入库单号":"PO20261302153045"}'
    assert document_time('batch', obj) is None


def test_inbound_uses_source_identity_from_batch_without_created_at_fallback():
    batch = SimpleNamespace(creation_key='PHSUP20261103:batch:1',
        notes='history\n{"入库单号":"PO20251008112208"}', arrived_warehouse_at=None)
    inbound = SimpleNamespace(batch=batch, confirmed_at=None, created_at=timezone.now())
    assert document_time('inbound', inbound) == '2025-10-08T11:22:08+08:00'
    batch.notes = 'history\n{"入库单号":"POST9J014071"}'
    assert document_time('inbound', inbound) is None


def test_source_number_does_not_override_normal_purchase_business_date():
    obj = SimpleNamespace(creation_key='manual:1', reference_number='PHCG261102001', order_date=date(2026, 10, 31))
    assert document_time('purchase', obj) == '2026-10-31'


def test_nonhistorical_business_fields_and_missing_dates_do_not_use_created_at():
    shipment = SimpleNamespace(shipment_date=date(2026, 10, 30), created_at=timezone.now())
    assert document_time('shipment', shipment) == '2026-10-30'
    batch = SimpleNamespace(departed_at=None, created_at=timezone.now())
    assert document_time('batch', batch) is None
    inbound = SimpleNamespace(creation_key='regular', notes='', confirmed_at=None,
        batch=SimpleNamespace(arrived_warehouse_at=datetime(2026, 11, 1, 1, 2, 3, tzinfo=timezone.get_current_timezone())))
    assert document_time('clearance', inbound) == '2026-11-01T09:02:03+08:00'
