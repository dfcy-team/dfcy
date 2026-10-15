from decimal import Decimal

import pytest

from apps.supply_chain import logistics, services
from apps.supply_chain.models import BusinessEvent, FreightCompany, domain_write
from tests.test_supply_chain_v2_foundation import world as foundation_world
from tests.test_supply_chain_v2_logistics import setup


@pytest.fixture
def world(db):
    return foundation_world.__wrapped__(db)


@pytest.mark.django_db
def test_dispatch_batch_keeps_carrier_quote_snapshot_when_profile_changes(world):
    buyer, first, _, carrier, _ = setup(world)
    with domain_write():
        carrier.fee_per_cbm = Decimal('18.7500')
        carrier.tax_percent = Decimal('6.25')
        carrier.save(update_fields=['fee_per_cbm', 'tax_percent'])

    batch = services.create_dispatch_batch(
        buyer,
        {'number': 'DB-SNAPSHOT', 'freight_company_id': carrier.pk,
         'freight_number': 'F-SNAPSHOT', 'shipment_ids': [first.pk]},
        idempotency_key='carrier-quote-snapshot',
    )
    with domain_write():
        carrier.fee_per_cbm = Decimal('22.0000')
        carrier.tax_percent = Decimal('9.00')
        carrier.save(update_fields=['fee_per_cbm', 'tax_percent'])
    batch.refresh_from_db()

    assert batch.fee_per_cbm_snapshot == Decimal('18.7500')
    assert batch.tax_percent_snapshot == Decimal('6.25')
    data = logistics.batch_data(batch)
    assert data['fee_per_cbm_snapshot'] == Decimal('18.7500')
    assert data['tax_percent_snapshot'] == Decimal('6.25')


@pytest.mark.django_db
def test_dispatch_batch_without_carrier_quote_keeps_snapshot_unknown(world):
    buyer, first, _, carrier, _ = setup(world)
    batch = services.create_dispatch_batch(
        buyer,
        {'number': 'DB-UNKNOWN-SNAPSHOT', 'freight_company_id': carrier.pk,
         'freight_number': 'F-UNKNOWN', 'shipment_ids': [first.pk]},
        idempotency_key='carrier-quote-unknown-snapshot',
    )

    assert batch.fee_per_cbm_snapshot is None
    assert batch.tax_percent_snapshot == carrier.tax_percent


@pytest.mark.django_db
def test_changing_carrier_refreshes_quote_but_resaving_same_carrier_keeps_snapshot(world):
    buyer, first, _, carrier, _ = setup(world)
    batch = services.create_dispatch_batch(
        buyer,
        {'number': 'DB-CHANGE-CARRIER', 'freight_company_id': carrier.pk,
         'freight_number': 'F-CHANGE', 'shipment_ids': [first.pk]},
        idempotency_key='carrier-change-create',
    )
    with domain_write():
        other = FreightCompany.objects.create(
            tenant=buyer.tenant, created_by=buyer, code='other-carrier', name='Other carrier',
            shipping_marks='NEW-MARK', fee_per_cbm=Decimal('30.5000'), tax_percent=Decimal('7.00'),
        )
    payload = {'expected_version': batch.version, 'freight_company_id': other.pk}
    batch = logistics.update_batch(buyer, batch.pk, payload, 'carrier-change')
    assert batch.freight_company_id == other.pk
    assert batch.shipping_marks_snapshot == 'NEW-MARK'
    assert batch.fee_per_cbm_snapshot == Decimal('30.5000')
    assert batch.tax_percent_snapshot == Decimal('7.00')
    event = BusinessEvent.objects.get(aggregate_type='dispatchbatch', aggregate_id=batch.pk,
                                      action='metadata_updated', request_key='carrier-change')
    assert event.payload['before']['freight_company_id'] == carrier.pk
    assert event.payload['before']['fee_per_cbm_snapshot'] is None
    assert event.payload['after']['fee_per_cbm_snapshot'] == '30.5000'
    assert logistics.update_batch(buyer, batch.pk, payload, 'carrier-change').version == batch.version

    with domain_write():
        other.shipping_marks, other.fee_per_cbm, other.tax_percent = 'CHANGED', Decimal('50'), Decimal('9')
        other.save()
    batch = logistics.update_batch(buyer, batch.pk, {
        'expected_version': batch.version, 'freight_company_id': other.pk, 'notes': '只更新备注',
    }, 'carrier-resave')
    assert batch.shipping_marks_snapshot == 'NEW-MARK'
    assert batch.fee_per_cbm_snapshot == Decimal('30.5000')
    assert batch.tax_percent_snapshot == Decimal('7.00')


@pytest.mark.django_db
def test_resaving_historical_unknown_quote_does_not_backfill_current_profile(world):
    buyer, first, _, carrier, _ = setup(world)
    batch = services.create_dispatch_batch(
        buyer,
        {'number': 'DB-PRESERVE-UNKNOWN', 'freight_company_id': carrier.pk,
         'freight_number': 'F-UNKNOWN', 'shipment_ids': [first.pk]},
        idempotency_key='carrier-preserve-unknown',
    )
    with domain_write():
        carrier.shipping_marks, carrier.fee_per_cbm = 'CHANGED', Decimal('99')
        carrier.save()
    batch = logistics.update_batch(buyer, batch.pk, {
        'expected_version': batch.version, 'freight_company_id': carrier.pk,
    }, 'preserve-unknown')
    assert batch.fee_per_cbm_snapshot is None
    assert batch.shipping_marks_snapshot == 'MARK'
