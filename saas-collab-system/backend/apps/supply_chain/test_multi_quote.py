from datetime import date
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError

from apps.supply_chain import services
from apps.supply_chain.freight_channels import batch_freight_values, channel_data, current_quotes
from apps.supply_chain.freight_models import FreightChannel, FreightQuote
from apps.supply_chain.models import domain_write
from tests.test_supply_chain_v2_foundation import (
    confirmed_order, freight as make_freight, internal_user, po_payload,
    shipment_payload, world as foundation_world,
)


@pytest.fixture
def world(db):
    return foundation_world.__wrapped__(db)


def add_quote(actor, channel, sequence, *, basis='cbm', container_type='', fee='10', start='2026-01-01', end=None):
    return FreightQuote.objects.create(
        tenant=actor.tenant, created_by=actor, channel=channel, sequence=sequence,
        effective_from=date.fromisoformat(start),
        effective_to=date.fromisoformat(end) if end else None,
        billing_basis=basis, fee_per_cbm=Decimal(fee) if basis == 'cbm' else None,
        container_fee=Decimal(fee) if basis == 'container' else None,
        container_type=container_type, reason=f'quote {sequence}',
    )


@pytest.mark.django_db
def test_channel_keeps_current_quotes_per_scheme_and_freezes_the_selected_quote(world):
    actor = internal_user(world, 'multi-quote-buyer')
    carrier = make_freight(world)
    with domain_write():
        channel = FreightChannel.objects.create(
            tenant=world['tenant'], created_by=actor, company=carrier, country=world['country'],
            code='multi', name='Multi', origin='Shanghai', cargo_type='general', transport_mode='sea',
        )
        old_cbm = add_quote(actor, channel, 1, fee='8')
        cbm = add_quote(actor, channel, 2, fee='9')
        hq = add_quote(actor, channel, 3, basis='container', container_type='40HQ', fee='1800')
        gp = add_quote(actor, channel, 4, basis='container', container_type='20GP', fee='1000')
        hq_new = add_quote(actor, channel, 5, basis='container', container_type='40hq', fee='1850')

    with patch('apps.supply_chain.freight_channels.business_date', return_value=date(2026, 10, 16)):
        active = current_quotes(channel)
        assert {q.pk for q in active} == {cbm.pk, gp.pk, hq_new.pk}
        data = channel_data(channel)
        assert data['current_quote'] is None  # legacy field cannot imply a scheme choice
        assert {q['id'] for q in data['current_quotes']} == {cbm.pk, gp.pk, hq_new.pk}
        selected = batch_freight_values(actor, carrier, 'US', channel.pk, gp.pk)
        assert selected['freight_quote'].pk == gp.pk
        assert selected['freight_quote_snapshot']['quote']['id'] == gp.pk
        assert selected['freight_quote_snapshot']['quote']['container_type'] == '20GP'
        assert 'current_quotes' not in selected['freight_quote_snapshot']
        assert selected['fee_per_cbm_snapshot'] is None
        for rejected in (old_cbm.pk, hq.pk):
            with pytest.raises(ValidationError):
                batch_freight_values(actor, carrier, 'US', channel.pk, rejected)

        order = confirmed_order(world, actor, key='multi-quote-order',
                                payload=po_payload(world, number='PO-MULTI-QUOTE'))
        shipment = services.create_supplier_shipment(
            actor, shipment_payload(world, order, 'multi-quote-shipment'),
            idempotency_key='multi-quote-shipment',
        )
        batch = services.create_dispatch_batch(actor, {
            'number': 'DB-MULTI-QUOTE', 'shipment_ids': [shipment.pk],
            'freight_company_id': carrier.pk, 'freight_number': 'F-MULTI-QUOTE',
            'freight_channel_id': channel.pk, 'freight_quote_id': gp.pk,
            'container_count': 1,
        }, idempotency_key='multi-quote-dispatch')
        assert batch.freight_quote_snapshot['quote']['id'] == gp.pk
        assert 'current_quotes' not in batch.freight_quote_snapshot


@pytest.mark.django_db
def test_expired_latest_quote_does_not_fall_back_and_future_quotes_are_not_current(world):
    actor = internal_user(world, 'multi-quote-dates')
    carrier = make_freight(world)
    with domain_write():
        channel = FreightChannel.objects.create(
            tenant=world['tenant'], created_by=actor, company=carrier, country=world['country'],
            code='dated', name='Dated', origin='Shanghai', cargo_type='general', transport_mode='sea',
        )
        add_quote(actor, channel, 1, fee='8')
        expired_latest = add_quote(actor, channel, 2, fee='9', end='2026-10-15')
        future = add_quote(actor, channel, 3, basis='container', container_type='40HQ', fee='1800', start='2026-10-17')

    with patch('apps.supply_chain.freight_channels.business_date', return_value=date(2026, 10, 16)):
        assert current_quotes(channel) == []
        assert channel_data(channel)['current_quotes'] == []
        with pytest.raises(ValidationError):
            batch_freight_values(actor, carrier, 'US', channel.pk, expired_latest.pk)
        with pytest.raises(ValidationError):
            batch_freight_values(actor, carrier, 'US', channel.pk, future.pk)
