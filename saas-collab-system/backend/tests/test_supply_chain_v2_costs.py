from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.commerce.models import InventorySnapshot
from apps.accounts.models import CustomUser
from apps.masterdata.models import SupplierMaster, WarehouseMaster
from apps.permissions.models import DataScope
from apps.supply_chain import costs, services
from apps.supply_chain.models import (BusinessEvent, CostAdjustment, CostEntry, CostVersion,
    FeeRecord, FeeRevision, InternalStockReceiptLine, SettlementRecord, SettlementRevision, PayeeAccount, domain_write)
from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_foundation import (world, internal_user, supplier_user,
    confirmed_order, po_payload, shipment_payload, freight)
from tests.test_supply_chain_v2_logistics import client, write, create, arrive, generate, checked, BASE


def pilot(world, *, geometry=True):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer, payload=po_payload(world, lines=[
        {'sku_id': world['sku'].pk, 'quantity': 3, 'unit_price': '2.5'}]))
    shipment = services.create_supplier_shipment(buyer, shipment_payload(world, order, 's', lines=[
        {'sku_id': world['sku'].pk, 'quantity': 4},
        {'sku_id': world['sku_b'].pk, 'quantity': 2, 'unit_price': '5'}]), idempotency_key='s')
    if geometry:
        for name, volume in [('sku', '.1'), ('sku_b', '.2')]:
            sku = world[name]; sku.package_volume = Decimal(volume); sku.package_weight = Decimal('1000'); sku.save()
    return buyer, client(buyer), shipment


def get(api, kind, obj):
    pk = obj if isinstance(obj, int) else obj.pk
    response = api.get(BASE + f'costs/{kind}/{pk}/')
    assert response.status_code == 200, response.data
    return response.data['data']


def fee_body(context, amount='0', **extra):
    return {'expected_source_version': context['target']['version'],
        'expected_version': context['fee']['version'] if context['fee'] else 0,
        'amount': amount, 'state': 'confirmed', 'method': 'volume', 'volume_percent': '50',
        'billed_cbm': None, 'notes': '', 'reason': '核对测试费用', **extra}


def fee(api, kind, obj, amount='0', *, key=None, **extra):
    context = get(api, kind, obj)
    body = fee_body(context, amount, **extra)
    response = write(api, f'costs/{kind}/{context["target"]["id"]}/fee/', body,
                     key or f'{kind}-{context["target"]["id"]}-fee-{body["expected_version"]}', 'put')
    assert response.status_code == 200, response.data
    return response.data['data'], body


def calculate(api, kind, obj, *, key=None):
    context = get(api, kind, obj)
    body = {'expected_source_version': context['target']['calculation_version'],
            'expected_input_fingerprint': context['input_fingerprint']}
    calc_kind, pk = context['target']['calculation_kind'], context['target']['calculation_id']
    response = write(api, f'costs/{calc_kind}/{pk}/calculate/', body,
        key or f'cost-{calc_kind}-{pk}-{len(context["cost_history"])}')
    assert response.status_code == 200, response.data
    return response.data['data'], body


def mark(buyer, shipment, key='collection'):
    shipment.refresh_from_db()
    return services.mark_collection_arrival(buyer, shipment.pk, expected_version=shipment.version,
        occurred_at=datetime(2026, 10, 12, tzinfo=timezone.utc), idempotency_key=key)


def received_pilot(world, *, quantities=(3, 2)):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '6')
    shipment.refresh_from_db()
    batch, _ = create(api, [shipment], freight(world))
    batch = arrive(api, batch)
    fee(api, 'batch', batch['id'], '30', billed_cbm='1.500000')
    batch = api.get(BASE + f'dispatch-batches/{batch["id"]}/').data['data']
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='US-COST', name='US cost', country_code='US')
    inbound = generate(api, batch, warehouse)
    inbound, _ = checked(api, inbound, quantities=list(quantities))
    response = write(api, f'inbound-orders/{inbound["id"]}/confirm/', {'expected_version': inbound['version']}, 'receipt')
    assert response.status_code == 200, response.data
    fee(api, 'inbound', inbound['id'], '7' if any(quantities) else '0', billed_cbm='1.200000')
    return buyer, api, shipment, batch['id'], inbound['id']


@pytest.mark.parametrize('method,percent,expected', [
    ('volume', '50', ('5.0000', '5.0000')),
    ('weight', '50', ('6.6667', '3.3333')),
    ('mixed', '60', ('5.6667', '4.3333')),
    ('mixed', '0', ('6.6667', '3.3333')),
    ('mixed', '100', ('5.0000', '5.0000'))])
def test_fee_ratio_exact_conservation_and_source_snapshot(world, method, percent, expected):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    result, body = fee(api, 'shipment', shipment, '10', method=method, volume_percent=percent)
    allocation = result['fee']['allocations']
    assert tuple(row['amount'] for row in allocation) == expected
    assert sum(Decimal(row['amount']) for row in allocation) == Decimal('10')
    assert [row['volume_cbm'] for row in allocation] == ['0.400000', '0.400000']
    assert [row['weight_kg'] for row in allocation] == ['4.000000', '2.000000']
    assert all(row['volume_source'] == 'sku_volume' for row in allocation)
    assert write(api, f'costs/shipment/{shipment.pk}/fee/', body, f'shipment-{shipment.pk}-fee-0', 'put').status_code == 200
    assert FeeRevision.objects.count() == 1
    assert write(api, f'costs/shipment/{shipment.pk}/fee/', {**body, 'amount': '11'}, f'shipment-{shipment.pk}-fee-0', 'put').status_code == 422


def test_missing_measurements_block_positive_fee_zero_is_explicit_and_manual_total_works(world):
    buyer, api, shipment = pilot(world, geometry=False)
    shipment = mark(buyer, shipment)
    context = get(api, 'shipment', shipment)
    body = fee_body(context, '10', method='mixed')
    assert write(api, f'costs/shipment/{shipment.pk}/fee/', body, 'missing', 'put').status_code == 422
    assert not FeeRecord.objects.exists() and not FeeRevision.objects.exists()
    zero, _ = fee(api, 'shipment', shipment)
    assert zero['fee']['amount'] == '0.0000' and zero['fee']['state'] == 'confirmed'
    overrides = [{'shipment_line_id': row['shipment_line_id'], 'volume_cbm': '1', 'weight_kg': '2'}
                 for row in zero['measurements']]
    result, _ = fee(api, 'shipment', shipment, '10', method='mixed', volume_percent='35', measurements=overrides)
    assert all(row['amount'] == '5.0000' and row['volume_source'] == 'manual_total' for row in result['fee']['allocations'])
    assert len(result['fee_history']) == 2


def test_dimension_fallback_ignores_declared_zero_and_tie_break_is_deterministic(world):
    buyer, api, shipment = pilot(world, geometry=False)
    shipment = mark(buyer, shipment)
    for name in ('sku', 'sku_b'):
        sku = world[name]
        sku.package_length_cm = sku.package_width_cm = sku.package_height_cm = Decimal('10')
        sku.save()
    result, _ = fee(api, 'shipment', shipment, '0.0001')
    assert [row['amount'] for row in result['fee']['allocations']] == ['0.0001', '0.0000']
    assert result['fee']['allocations'][0]['volume_source'] == 'sku_dimensions'
    world['sku'].package_volume = Decimal('0'); world['sku'].save()
    body = fee_body(get(api, 'shipment', shipment), '1')
    assert write(api, f'costs/shipment/{shipment.pk}/fee/', body, 'zero-volume', 'put').status_code == 422
    rows = [{'shipment_line_id': pk, 'quantity': 1, 'volume_cbm': '1', 'weight_kg': None} for pk in (8, 3, 12)]
    assert {row['shipment_line_id']: row['amount'] for row in costs.allocate('0.0002', rows, 'volume', '50')} == {8: '0.0001', 3: '0.0001', 12: '0.0000'}


@pytest.mark.parametrize('field,value', [('amount', '-1'), ('amount', '1.00001'), ('volume_percent', '101'),
    ('volume_percent', '-1'), ('method', 'quantity'), ('state', 'paid'), ('reason', ' '), ('billed_cbm', '1')])
def test_fee_typed_validation_and_arrival_guard(world, field, value):
    buyer, api, shipment = pilot(world)
    body = fee_body(get(api, 'shipment', shipment), '1')
    assert write(api, f'costs/shipment/{shipment.pk}/fee/', body, 'early', 'put').status_code == 422
    shipment = mark(buyer, shipment)
    body = {**fee_body(get(api, 'shipment', shipment), '1'), field: value}
    assert write(api, f'costs/shipment/{shipment.pk}/fee/', body, 'bad', 'put').status_code == (422 if field == 'billed_cbm' else 400)
    assert not FeeRevision.objects.exists()


def test_partial_receipt_costs_excess_and_additional_skus_and_settlement_independence(world):
    buyer, api, shipment, batch, inbound = received_pilot(world)
    data, body = calculate(api, 'inbound', inbound)
    assert data['status'] == 'confirmed' and data['stage'] == 'received'
    assert data['summary'] == {'shipped_quantity': 6, 'received_quantity': 5, 'shipped_total': '56.0000',
        'received_total': '56.0000', 'pending_total': '7.0000'}
    assert [row['received_total'] for row in data['entries']] == ['24.0000', '32.0000']
    assert [row['goods_amount'] for row in data['entries']] == ['10.0000', '10.0000']
    assert [row['clearance_fee'] for row in data['entries']] == ['3.0000', '4.0000']
    assert not SettlementRecord.objects.exists() and not data['adjustments']
    assert shipment.lines.get(sku=world['sku_b']).purchase_line_id is None
    assert get(api, 'shipment', shipment)['target']['calculation_allowed'] is False
    replay = write(api, f'costs/batch/{batch}/calculate/', body, f'cost-batch-{batch}-0')
    assert replay.status_code == 200 and replay.data['data']['id'] == data['id'] and CostVersion.objects.count() == 1
    original = api.get(BASE + f'costs/batch/{batch}/versions/1/').data['data']
    assert original['entries'] == data['entries']


def test_late_price_revision_delta_and_settlement_difference_without_quantity_or_stock_change(world):
    buyer, api, shipment, batch, inbound = received_pilot(world)
    baseline, _ = calculate(api, 'batch', batch)
    before = list(InternalStockReceiptLine.objects.values_list('pk', 'received_quantity'))
    stock_count = InventorySnapshot.objects.count()
    settlement_context = get(api, 'shipment', shipment)
    settlement = {'expected_source_version': settlement_context['target']['version'], 'expected_version': 0,
        'recorded_amount': '20', 'reference_number': 'FINANCE-TEST-1', 'date': '2026-10-14',
        'reason': '根据已核对的结算单登记累计额'}
    response = write(api, f'costs/shipment/{shipment.pk}/settlement/', settlement, 'supplier-settlement')
    assert response.status_code == 200 and response.data['data']['settlement']['status'] == 'settled'
    ledger = api.get(BASE + 'product-cost-ledger/?versions=all')
    assert ledger.status_code == 200, ledger.data
    row = next(item for item in ledger.data['data'] if item['shipment_id'] == shipment.pk)
    assert row['goods_settlement_nature'] == 'unclassified'
    assert row['goods_settlement_basis'] == 'current' and row['freight_settlement_basis'] == 'current'
    assert get(api, 'batch', batch)['latest_cost']['status'] == 'confirmed'
    shipment.refresh_from_db()
    price = {'expected_version': shipment.version, 'lines': [{'id': shipment.lines.get(sku=world['sku']).pk, 'unit_price': '3.5'}]}
    assert write(api, f'supplier-shipments/{shipment.pk}/prices/', price, 'no-cause', 'patch').status_code == 422
    assert write(api, f'supplier-shipments/{shipment.pk}/prices/', {**price, 'reason': '供应商结算后价差'}, 'late-price', 'patch').status_code == 200
    assert get(api, 'batch', batch)['latest_cost']['status'] == 'recalculation_required'
    assert get(api, 'shipment', shipment)['settlement']['adjustment_due'] == '4.0000'
    revised, _ = calculate(api, 'batch', batch)
    assert revised['status'] == 'confirmed' and revised['summary']['received_total'] == '59.0000'
    assert revised['summary']['pending_total'] == '8.0000'
    assert len(revised['adjustments']) == 1 and revised['adjustments'][0]['delta'] == '3.0000'
    assert shipment.lines.get(sku=world['sku']).purchase_price_snapshot == Decimal('2.5')
    assert CostVersion.objects.get(sequence=1).summary == baseline['summary']
    assert list(InternalStockReceiptLine.objects.values_list('pk', 'received_quantity')) == before
    assert InventorySnapshot.objects.count() == stock_count and InternalStockReceiptLine.objects.count() == 2
    assert write(api, f'costs/shipment/{shipment.pk}/settlement/', settlement, 'supplier-settlement').status_code == 200
    assert SettlementRevision.objects.count() == 1


def test_fee_revision_after_receipt_creates_delta_preserves_history_and_cbm(world):
    buyer, api, shipment, batch, inbound = received_pilot(world)
    baseline, _ = calculate(api, 'batch', batch)
    updated, _ = fee(api, 'batch', batch, '34', billed_cbm='1.600000', method='mixed', volume_percent='100')
    assert updated['latest_cost']['status'] == 'recalculation_required' and updated['fee']['version'] == 2
    new, _ = calculate(api, 'batch', batch)
    assert sum(Decimal(row['delta']) for row in new['adjustments']) == Decimal('3.5')
    assert new['summary']['received_total'] == '59.5000'
    assert api.get(BASE + f'costs/batch/{batch}/versions/1/').data['data']['summary'] == baseline['summary']
    assert len(updated['fee_history']) == 2
    from apps.supply_chain.models import DispatchBatch, InboundOrder
    assert DispatchBatch.objects.get(pk=batch).billed_cbm == Decimal('1.6')
    assert InboundOrder.objects.get(pk=inbound).clearance_cbm == Decimal('1.2')


def test_missing_price_and_fees_remain_estimated_no_false_zero(world):
    buyer, api, shipment = pilot(world)
    incomplete, _ = calculate(api, 'shipment', shipment, key='missing-fees')
    assert incomplete['summary']['shipped_total'] is None
    assert incomplete['entries'][0]['goods_amount'] == '10.0000'
    assert incomplete['entries'][0]['collection_fee'] is None
    shipment.refresh_from_db()
    line = shipment.lines.get(sku=world['sku_b'])
    response = write(api, f'supplier-shipments/{shipment.pk}/prices/', {'expected_version': shipment.version,
        'lines': [{'id': line.pk, 'unit_price': None}]}, 'price-null', 'patch')
    assert response.status_code == 200
    data, _ = calculate(api, 'shipment', shipment)
    assert data['status'] == 'estimated' and data['summary']['shipped_total'] is None
    assert any('价格未填写' in issue for issue in data['issues']) and any('未维护' in issue for issue in data['issues'])
    assert data['entries'][1]['goods_amount'] is None and data['entries'][1]['shipped_total'] is None
    assert get(api, 'shipment', shipment)['settlement']['current_amount'] is None


def test_carrier_cumulative_settlement_and_amount_difference_are_independent(world):
    buyer, api, shipment, batch, inbound = received_pilot(world)
    first, _ = calculate(api, 'batch', batch)
    context = get(api, 'batch', batch)
    body = {'expected_source_version': context['target']['version'], 'expected_version': 0,
        'recorded_amount': '15', 'reference_number': 'TEST-CARRIER-1', 'date': '2026-10-14', 'reason': '部分结算'}
    response = write(api, f'costs/batch/{batch}/settlement/', body, 'carrier-settle')
    assert response.status_code == 200, response.data
    assert response.data['data']['settlement']['unsettled_amount'] == '15.0000'
    assert get(api, 'batch', batch)['latest_cost']['status'] == 'confirmed'
    fee(api, 'batch', batch, '10')
    current = get(api, 'batch', batch)
    assert current['settlement']['over_recorded_amount'] == '5.0000'
    assert current['settlement']['adjustment_due'] == '-20.0000'
    body.update(expected_source_version=current['target']['version'], expected_version=1,
        recorded_amount='10', reference_number='TEST-REFUND-1', reason='退款后更正累计结算金额')
    response = write(api, f'costs/batch/{batch}/settlement/', body, 'carrier-revise')
    assert response.status_code == 200 and response.data['data']['settlement']['status'] == 'settled'
    assert response.data['data']['settlement']['adjustment_due'] == '0.0000'
    assert len(response.data['data']['settlement_history']) == 2
    assert CostVersion.objects.get(pk=first['id']).summary == first['summary']
    with domain_write(), pytest.raises(ValidationError):
        SettlementRevision.objects.first().save()


def test_payee_allocation_snapshot_mixed_total_idempotency_and_inactive_account_rules(world):
    buyer, api, shipment = pilot(world)
    account_url = BASE + f'costs/shipment/{shipment.pk}/payee-accounts/'
    first = {'nature': 'corporate', 'account_name': '公司基本户', 'account_holder': '甲公司',
        'bank_name': '测试银行', 'account_number': '6222000000001111', 'active': True}
    second = {**first, 'nature': 'personal', 'account_name': '备用收款户',
        'account_holder': '李某', 'account_number': '6222000000002222'}
    a = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', first, 'payee-a')
    b = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', second, 'payee-b')
    assert a.status_code == 201 and b.status_code == 201
    # A successful creation replay still resolves after the 100-account boundary check.
    assert write(api, f'costs/shipment/{shipment.pk}/payee-accounts/', first, 'payee-a').data['data']['account']['id'] == a.data['data']['account']['id']
    account_a, account_b = a.data['data']['account'], b.data['data']['account']
    # View-only users can list options with a masked number but cannot mutate the archive.
    viewer = internal_user(world, 'cost-viewer', codes=(costs.VIEW,))
    viewer_api = client(viewer)
    options = viewer_api.get(account_url)
    assert options.status_code == 200
    assert options.data['data']['accounts'][0]['account_number'].endswith('1111')
    assert '*' in options.data['data']['accounts'][0]['account_number']
    assert write(viewer_api, f'costs/shipment/{shipment.pk}/payee-accounts/', first, 'viewer-create').status_code == 403
    context = get(api, 'shipment', shipment)
    body = {'expected_source_version': context['target']['version'], 'expected_version': 0,
        'recorded_amount': '10.0000', 'reference_number': 'PAYEE-1', 'date': '2026-10-14',
        'reason': '混合账户累计登记', 'payee_allocations': [
            {'account_id': account_a['id'], 'amount': '4.0000'},
            {'account_id': account_b['id'], 'amount': '6.0000'}]}
    url = f'costs/shipment/{shipment.pk}/settlement/'
    duplicate = {**body, 'payee_allocations': [
        {'account_id': account_a['id'], 'amount': '5.0000'},
        {'account_id': account_a['id'], 'amount': '5.0000'}]}
    assert write(api, url, duplicate, 'payee-duplicate').status_code == 422
    wrong_total = {**body, 'payee_allocations': [{'account_id': account_a['id'], 'amount': '9.0000'}]}
    assert write(api, url, wrong_total, 'payee-wrong-total').status_code == 422
    saved = write(api, url, body, 'payee-settlement-1')
    assert saved.status_code == 200, saved.data
    settlement = saved.data['data']['settlement']
    assert settlement['settlement_nature'] == 'mixed' and settlement['unclassified_amount'] == '0.0000'
    assert [row['account_snapshot']['nature'] for row in settlement['allocations']] == ['corporate', 'personal']

    # Editing the master profile cannot change the immutable allocation snapshot.
    changed = {**first, 'nature': 'personal', 'expected_version': 1}
    assert write(api, f'costs/shipment/{shipment.pk}/payee-accounts/{account_a["id"]}/', changed,
        'payee-a-edit', 'put').status_code == 200
    disabled = {**second, 'active': False, 'expected_version': 1}
    disabled_response = write(api, f'costs/shipment/{shipment.pk}/payee-accounts/{account_b["id"]}/', disabled,
        'payee-b-disable', 'put')
    assert disabled_response.status_code == 200 and disabled_response.data['data']['account']['active'] is False
    current = get(api, 'shipment', shipment)
    revise = {**body, 'expected_source_version': current['target']['version'], 'expected_version': 1,
        'reference_number': 'PAYEE-2'}
    retained = write(api, url, revise, 'payee-settlement-2')
    assert retained.status_code == 200, retained.data
    history = retained.data['data']['settlement_history']
    assert history[0]['allocations'][0]['account_snapshot']['nature'] == 'corporate'
    assert history[1]['allocations'][0]['account_snapshot']['nature'] == 'corporate'
    assert history[1]['allocations'][0]['account_snapshot']['account_number'].endswith('1111')
    assert history[1]['allocations'][1]['account_snapshot']['account_number'].endswith('2222')

    # Disabled accounts can carry forward the prior cumulative allocation, but cannot increase it.
    current = get(api, 'shipment', shipment)
    increased_disabled = {**revise, 'expected_source_version': current['target']['version'], 'expected_version': 2,
        'recorded_amount': '11.0000', 'reference_number': 'PAYEE-3', 'payee_allocations': [
            {'account_id': account_a['id'], 'amount': '4.0000'},
            {'account_id': account_b['id'], 'amount': '7.0000'}]}
    assert write(api, url, increased_disabled, 'payee-settlement-3').status_code == 422
    assert SettlementRevision.objects.filter(settlement__shipment=shipment).count() == 2

    # A supplier account cannot be assigned to a different supplier's shipment.
    other_order = confirmed_order(world, buyer, key='other-supplier-order', payload=po_payload(
        world, number='PO-OTHER-SUPPLIER', supplier=world['supplier_b']))
    other_shipment = services.create_supplier_shipment(buyer, shipment_payload(
        world, other_order, 'other-supplier-shipment', number='SH-OTHER-SUPPLIER'),
        idempotency_key='other-supplier-shipment')
    other_context = get(api, 'shipment', other_shipment)
    cross_supplier = {'expected_source_version': other_context['target']['version'], 'expected_version': 0,
        'recorded_amount': '1.0000', 'reference_number': 'CROSS-SUPPLIER', 'date': '2026-10-14',
        'reason': '验证账户业务边界', 'payee_allocations': [{'account_id': account_a['id'], 'amount': '1.0000'}]}
    response = write(api, f'costs/shipment/{other_shipment.pk}/settlement/', cross_supplier, 'cross-supplier')
    assert response.status_code == 422 and '账户' in str(response.data)

    foreign_tenant = Tenant.objects.create(name='Foreign tenant', code='foreign-tenant')
    foreign_user = CustomUser.objects.create_user(username='foreign-payee-owner', tenant=foreign_tenant,
        user_type=CustomUser.UserType.INTERNAL)
    foreign_supplier = SupplierMaster.objects.create(tenant=foreign_tenant, code='foreign-supplier', name='Foreign supplier')
    with domain_write():
        foreign_account = PayeeAccount.objects.create(tenant=foreign_tenant, created_by=foreign_user,
            supplier=foreign_supplier, nature='corporate', account_name='Foreign account',
            account_holder='Foreign holder', bank_name='Foreign bank', account_number='999900001234', active=True)
    cross_tenant = {**cross_supplier, 'payee_allocations': [
        {'account_id': foreign_account.pk, 'amount': '1.0000'}]}
    response = write(api, f'costs/shipment/{other_shipment.pk}/settlement/', cross_tenant, 'cross-tenant')
    assert response.status_code == 422 and '账户' in str(response.data)


@pytest.mark.parametrize('quantities', [(0, 0), (5, 2)])
def test_zero_and_excess_received_are_not_invented_supplier_goods(world, quantities):
    buyer, api, shipment, batch, inbound = received_pilot(world, quantities=quantities)
    data, _ = calculate(api, 'batch', batch)
    if not any(quantities):
        assert data['status'] == 'confirmed' and data['summary']['received_total'] == '0.0000'
        assert data['summary']['pending_total'] == '56.0000'
        assert all(row['received_unit_cost'] is None for row in data['entries'])
        body = fee_body(get(api, 'inbound', inbound), '1')
        assert write(api, f'costs/inbound/{inbound}/fee/', body, 'no-received', 'put').status_code == 422
    else:
        assert data['status'] == 'estimated' and any('实收超发货' in issue for issue in data['issues'])
        assert data['entries'][0]['received_goods_amount'] == '10.0000'
        assert data['summary']['pending_total'] == '0.0000'


def test_stale_nested_inputs_and_versions_and_atomic_cost_rollback(world):
    buyer, api, shipment, batch, inbound = received_pilot(world)
    context = get(api, 'batch', batch)
    old = {'expected_source_version': context['target']['version'], 'expected_input_fingerprint': context['input_fingerprint']}
    fee(api, 'shipment', shipment, '8')  # batch version unchanged; nested fingerprint must detect it
    assert write(api, f'costs/batch/{batch}/calculate/', old, 'stale-input').status_code == 422
    fresh = get(api, 'batch', batch)
    assert fresh['target']['version'] == context['target']['version']
    body = {'expected_source_version': fresh['target']['version'], 'expected_input_fingerprint': fresh['input_fingerprint']}
    with patch('apps.supply_chain.costs.CostEntry.objects.create', side_effect=RuntimeError('test rollback')):
        with pytest.raises(RuntimeError):
            costs.calculate(buyer, 'batch', batch, body, 'rollback')
    assert not CostVersion.objects.exists() and not CostEntry.objects.exists()
    assert not BusinessEvent.objects.filter(action='cost_calculated').exists()
    calculate(api, 'batch', batch)
    body = fee_body(get(api, 'shipment', shipment), '9'); body['expected_source_version'] -= 1
    assert write(api, f'costs/shipment/{shipment.pk}/fee/', body, 'stale-fee', 'put').status_code == 422


def test_cost_scope_supplier_deny_and_cross_tenant_and_view_only(world):
    buyer, api, shipment = pilot(world)
    contact = supplier_user(world, world['supplier'], 'supplier-cost')
    other = internal_user(world, 'other-scope', DataScope.ScopeType.CUSTOM, {'supplier_ids': [world['supplier_b'].pk]})
    viewer = internal_user(world, 'read-cost', codes=('supply.v2.view',))
    for actor, expected in [(contact, 403), (other, 404)]:
        assert client(actor).get(BASE + f'costs/shipment/{shipment.pk}/').status_code == expected
        assert client(actor).get(BASE + 'cost-targets/?kind=shipment').status_code in (200, 403)
    read_context = get(client(viewer), 'shipment', shipment)
    assert read_context['target']['fee_editable'] is False and read_context['target']['calculation_allowed'] is False
    assert write(client(viewer), f'costs/shipment/{shipment.pk}/fee/', fee_body(read_context), 'forbidden', 'put').status_code == 403
    from apps.tenants.models import Tenant
    from apps.accounts.models import CustomUser
    foreign = CustomUser.objects.create_user(username='foreign-cost', tenant=Tenant.objects.create(name='other', code='other-cost'), user_type='internal')
    foreign.is_superuser = True; foreign.save()
    assert client(foreign).get(BASE + f'costs/shipment/{shipment.pk}/').status_code == 404


def test_batch_with_denied_historical_member_cannot_leak_costs(world):
    from tests.test_supply_chain_v2_logistics import setup
    buyer, one, two, carrier, warehouse = setup(world, mixed_suppliers=True)
    api = client(buyer)
    batch, _ = create(api, [one, two], carrier)
    limited = internal_user(world, 'limited', DataScope.ScopeType.CUSTOM, {'supplier_ids': [world['supplier'].pk]})
    restricted = client(limited)
    context = get(restricted, 'shipment', one)
    assert context['latest_cost'] is None and context['cost_history'] == [] and context['input_fingerprint'] is None
    assert context['target']['calculation_allowed'] is False
    assert restricted.get(BASE + f'costs/batch/{batch["id"]}/').status_code == 404
    assert restricted.get(BASE + 'cost-targets/?kind=batch').data['data'] == []


def test_fee_quantity_change_requires_reallocation_and_append_only_history(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment); fee(api, 'shipment', shipment, '0')
    shipment.refresh_from_db(); batch, _ = create(api, [shipment], freight(world)); batch = arrive(api, batch)
    warehouse = WarehouseMaster.objects.create(tenant=world['tenant'], code='US-Q', name='US', country_code='US')
    inbound = generate(api, batch, warehouse); inbound, _ = checked(api, inbound, quantities=[3, 2])
    fee(api, 'inbound', inbound['id'], '4')
    inbound = api.get(BASE + f'inbound-orders/{inbound["id"]}/').data['data']
    body = {'expected_version': inbound['version'], 'lines': [
        {'id': row['id'], 'received_quantity': 2, 'difference_note': '再次核对'} for row in inbound['lines']]}
    assert write(api, f'inbound-orders/{inbound["id"]}/', body, 'recheck', 'patch').status_code == 200
    context = get(api, 'batch', batch['id'])
    assert write(api, f'costs/batch/{batch["id"]}/calculate/', {'expected_source_version': context['target']['version'],
        'expected_input_fingerprint': context['input_fingerprint']}, 'needs-reallocate').status_code == 422
    fee(api, 'inbound', inbound['id'], '4')
    data, _ = calculate(api, 'batch', batch['id'])
    assert data['status'] == 'estimated'
    for model in (FeeRevision, CostVersion, CostEntry):
        row = model.objects.first()
        with domain_write(), pytest.raises(ValidationError):
            row.save()
        with pytest.raises(ValidationError):
            model.objects.all().update(version=9)
        with pytest.raises(ValidationError):
            row.delete()


@pytest.mark.django_db
def test_cost_targets_country_name_comes_from_master_without_row_queries(world, django_assert_num_queries):
    buyer, api, shipment = pilot(world)
    from apps.supply_chain.models import PurchaseOrder
    country = PurchaseOrder.objects.select_related('country').get(pk=shipment.order_id).country
    country.name = 'Master country label'
    country.save(update_fields=['name'])
    query = costs.targets(buyer, 'shipment')
    # Load the page once and carrier membership labels once.
    with django_assert_num_queries(2):
        rows = list(query)
        costs.prepare_target_parties('shipment', rows)
        result = [costs.target_data('shipment', obj) for obj in rows]
    assert result and all(row['country_name'] == country.name for row in result)


@pytest.mark.django_db
def test_manual_purchase_link_uses_configured_public_origin_without_notification_preparation(world, settings):
    buyer, api, shipment = pilot(world)
    settings.SUPPLY_NOTIFICATION_PUBLIC_BASE_URL = 'https://supplier-public.example'
    response = api.get(BASE + f'purchase-orders/{shipment.order_id}/')
    assert response.status_code == 200
    assert response.data['data']['supplier_url'] == f'https://supplier-public.example/supplier/orders/{shipment.order_id}'
    settings.SUPPLY_NOTIFICATION_PUBLIC_BASE_URL = 'http://invalid.example'
    response = api.get(BASE + f'purchase-orders/{shipment.order_id}/')
    assert response.status_code == 200
    assert response.data['data']['supplier_url'] == ''
