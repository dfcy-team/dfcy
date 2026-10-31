from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.supply_chain import services, logistics
from apps.supply_chain.models import PaymentRecord, CostVersion, PaymentItem, FreightCompany, PayeeAccount, domain_write
from tests.test_supply_chain_v2_costs import pilot, get, mark, fee, calculate
from tests.test_supply_chain_v2_logistics import BASE, write
from tests.test_supply_chain_v2_foundation import world, confirmed_order, po_payload, shipment_payload
from tests.test_supply_chain_v2_foundation import freight
from tests.test_supply_chain_v2_costs import received_pilot, fee_body


def account(api, kind, obj, *, owner_supplier_id=None):
    pk = obj.pk if hasattr(obj, 'pk') else obj
    data = {'nature': 'corporate', 'account_name': 'Supplier account', 'account_holder': 'Supplier',
            'bank_name': 'Bank', 'account_number': '9988776655', 'active': True}
    response = write(api, f'costs/{kind}/{pk}/payee-accounts/', data, f'account-{kind}-{pk}')
    assert response.status_code == 201, response.data
    return response.data['data']['account']['id']


@pytest.mark.django_db(transaction=True)
def test_payment_replay_partial_prepayment_reversal_and_cost_is_unchanged(world):
    buyer, api, shipment = pilot(world)
    order = shipment.order
    account_id = account(api, 'purchase', order)
    before_costs = (shipment.lines.count(), PaymentRecord.objects.count())
    url = f'costs/purchase/{order.pk}/payments/'
    body = {'amount': '1.0000', 'date': '2026-10-14', 'payee_account_id': account_id,
            'expected_version': 0, 'notes': '预付款'}
    first = write(api, url, body, 'purchase-prepay')
    assert first.status_code == 201, first.data
    replay = write(api, url, body, 'purchase-prepay')
    assert replay.status_code == 201 and replay.data['data']['version'] == 1
    assert PaymentRecord.objects.filter(purchase_order=order).count() == 1
    prepayment_id = first.data['data']['entries'][0]['id']
    assert first.data['data']['entries'][0]['account_snapshot']['account_number'].endswith('6655')

    shipment = mark(buyer, shipment)
    # A partial application reduces the remaining available amount and can be reversed immutably.
    apply_url = f'costs/shipment/{shipment.pk}/prepayment-applications/'
    application = write(api, apply_url, {'payment_id': prepayment_id, 'amount': '0.4000',
        'date': '2026-10-15', 'expected_version': 0}, 'apply-part')
    assert application.status_code == 201, application.data
    assert application.data['data']['summary']['applied_amount'] == '0.4000'
    app_row = next(row for row in application.data['data']['entries'] if row['entry_type'] == 'application')
    assert app_row['related_href'] == ''  # shipment view retains source purchase link
    assert app_row['source_kind'] == 'purchase'
    assert app_row['source_id'] == order.pk
    assert app_row['cash_change'] == '0.0000'
    purchase_process = api.get(BASE + url).data['data']
    purchase_app = next(row for row in purchase_process['entries'] if row['entry_type'] == 'application')
    assert purchase_app['related_href'] == f'/supply-chain/costs?kind=shipment&id={shipment.pk}'
    assert purchase_app['available_after'] == '0.6000'
    purchase_summary = api.get(BASE + url).data['data']['summary']
    assert purchase_summary['applied_amount'] == '0.4000'
    assert purchase_summary['paid_amount'] == '1.0000'
    assert purchase_summary['available_prepayment'] == '0.6000'
    current_context = get(api, 'shipment', shipment)
    legacy_after_application = write(api, f'costs/shipment/{shipment.pk}/settlement/', {
        'expected_source_version': current_context['target']['version'], 'expected_version': 0,
        'recorded_amount': '0.4000', 'reference_number': 'DUPLICATE-APPLY', 'date': '2026-10-15',
        'reason': '不得重复登记抵扣'}, 'legacy-after-application')
    assert legacy_after_application.status_code == 422
    assert application.data['data']['available_prepayments'][0]['available_amount'] == '0.6000'
    app_id = next(row['id'] for row in application.data['data']['entries'] if row['entry_type'] == 'application')
    blocked = write(api, f'costs/purchase/{order.pk}/payments/{prepayment_id}/reverse/',
        {'reason': '误登', 'expected_version': 1}, 'reverse-prepay-blocked')
    assert blocked.status_code == 422
    app_reverse = write(api, f'costs/shipment/{shipment.pk}/prepayment-applications/{app_id}/reverse/',
        {'reason': '撤销错误抵扣', 'expected_version': 1}, 'reverse-app')
    assert app_reverse.status_code == 200, app_reverse.data
    assert app_reverse.data['data']['summary']['applied_amount'] == '0.0000'
    reversed_payment = write(api, f'costs/purchase/{order.pk}/payments/{prepayment_id}/reverse/',
        {'reason': '冲销错误预付款', 'expected_version': 1}, 'reverse-prepay')
    assert reversed_payment.status_code == 200, reversed_payment.data
    assert reversed_payment.data['data']['summary']['paid_amount'] == '0.0000'
    assert reversed_payment.data['data']['summary']['available_prepayment'] == '0.0000'
    spent_again = write(api, apply_url, {'payment_id': prepayment_id, 'amount': '0.1000',
        'date': '2026-10-16', 'expected_version': 2}, 'apply-reversed-prepay')
    assert spent_again.status_code == 422
    assert before_costs[0] == shipment.lines.count()


@pytest.mark.django_db(transaction=True)
def test_cross_purchase_and_foreign_tenant_payments_are_rejected(world):
    buyer, api, shipment = pilot(world)
    foreign_id = account(api, 'purchase', shipment.order)
    order2 = confirmed_order(world, buyer, key='payment-other-order',
        payload=po_payload(world, number='PO-OTHER-PAYMENT'))
    # A prepayment attached to one order cannot be applied to a different order's shipment.
    body = {'amount': '1.0000', 'date': '2026-10-14', 'payee_account_id': foreign_id, 'expected_version': 0}
    prepayment = write(api, f'costs/purchase/{shipment.order_id}/payments/', body, 'source-prepayment')
    assert prepayment.status_code == 201
    target_shipment = services.create_supplier_shipment(buyer,
        shipment_payload(world, order2, 'other-payment-shipment', number='SH-OTHER-PAYMENT'),
        idempotency_key='other-payment-shipment')
    # Ownership is rejected before payment amount semantics are evaluated.
    rejected = write(api, f'costs/shipment/{target_shipment.pk}/prepayment-applications/', {
        'payment_id': prepayment.data['data']['entries'][0]['id'], 'amount': '0.5000',
        'date': '2026-10-15', 'expected_version': 0}, 'cross-order-apply')
    assert rejected.status_code == 422
    foreign_tenant = world['tenant'].__class__.objects.create(name='Other tenant', code='other-payment-tenant')
    from apps.accounts.models import CustomUser
    user = CustomUser.objects.create_user(username='foreign-payment', tenant=foreign_tenant,
        user_type=CustomUser.UserType.INTERNAL)
    # The target is not visible through the other tenant's cost route.
    foreign_api = api.__class__()
    foreign_api.force_authenticate(user)
    assert foreign_api.get(BASE + f'costs/purchase/{shipment.order_id}/payments/').status_code in (403, 404)


@pytest.mark.django_db(transaction=True)
def test_supplier_and_freight_company_payee_archive_contexts(world):
    buyer, api, shipment = pilot(world)
    supplier_url = f'costs/supplier/{world["supplier"].pk}/payee-accounts/'
    freight_company = freight(world)
    freight_url = f'costs/freight_company/{freight_company.pk}/payee-accounts/'
    body = {'nature': 'corporate', 'account_name': 'Archive account', 'account_holder': 'Holder',
            'bank_name': 'Bank', 'account_number': '1234567890', 'active': True}
    supplier_result = write(api, supplier_url, body, 'supplier-archive-account')
    freight_result = write(api, freight_url, body, 'freight-archive-account')
    assert supplier_result.status_code == freight_result.status_code == 201
    assert api.get(BASE + supplier_url).data['data']['accounts'][0]['account_number'].endswith('7890')
    assert api.get(BASE + freight_url).data['data']['accounts'][0]['account_number'].endswith('7890')


@pytest.mark.django_db(transaction=True)
def test_legacy_cumulative_settlement_becomes_opening_and_cannot_be_overwritten(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    context = get(api, 'shipment', shipment)
    legacy = write(api, f'costs/shipment/{shipment.pk}/settlement/', {
        'expected_source_version': context['target']['version'], 'expected_version': 0,
        'recorded_amount': '1.0000', 'reference_number': 'OLD-1', 'date': '2026-10-13',
        'reason': '旧累计期初'}, 'old-settlement')
    assert legacy.status_code == 200
    account_id = account(api, 'purchase', shipment.order)
    summary = api.get(BASE + f'costs/shipment/{shipment.pk}/payments/').data['data']
    assert summary['summary']['opening_amount'] == '1.0000'
    assert summary['summary']['paid_amount'] == '1.0000'
    assert any(row['entry_type'] == 'opening' for row in summary['entries'])
    payment = write(api, f'costs/shipment/{shipment.pk}/payments/', {
        'amount': '0.5000', 'date': '2026-10-14', 'payee_account_id': account_id,
        'expected_version': 0}, 'new-payment-after-opening')
    assert payment.status_code == 201
    refreshed = get(api, 'shipment', shipment)
    refused = write(api, f'costs/shipment/{shipment.pk}/settlement/', {
        'expected_source_version': refreshed['target']['version'], 'expected_version': 1,
        'recorded_amount': '1.5000', 'reference_number': 'OLD-2', 'date': '2026-10-14',
        'reason': '禁止覆盖期初累计'}, 'old-settlement-overwrite')
    assert refused.status_code == 422


@pytest.mark.django_db(transaction=True)
def test_payment_projection_matches_cost_target_and_cost_ledger_classification(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    fee(api, 'shipment', shipment, '0')
    calculate(api, 'shipment', shipment)
    account_id = account(api, 'purchase', shipment.order)
    before_versions = PaymentRecord.objects.count()
    before_cost_versions = CostVersion.objects.count()
    created = write(api, f'costs/shipment/{shipment.pk}/payments/', {
        'amount': '0.5000', 'date': '2026-10-14', 'payee_account_id': account_id,
        'expected_version': 0}, 'shipment-payment-ledger')
    assert created.status_code == 201, created.data
    projection = api.get(BASE + 'cost-targets/', {'kind': 'shipment'}).data['data']
    owner = next(row for row in projection if row['id'] == shipment.pk)
    assert owner['paid_amount'] == '0.5000' and owner['remaining_amount'] is not None
    ledger = api.get(BASE + 'product-cost-ledger/').data['data']
    rows = [row for row in ledger if row['shipment_id'] == shipment.pk]
    assert rows and all(row['goods_settlement_recorded_amount'] == '0.5000' for row in rows)
    assert all(row['goods_settlement_nature'] == 'corporate' for row in rows)
    assert all(row['goods_payment_amount'] == '0.5000' for row in rows)
    assert get(api, 'shipment', shipment)['target']['paid_amount'] == '0.5000'
    groups = api.get(BASE + 'dashboard/?section=costs').data['data']['groups']
    assert Decimal(groups['supplier']['recorded']) == Decimal('0.5000')
    assert PaymentRecord.objects.count() == before_versions + 1
    assert CostVersion.objects.count() == before_cost_versions
import pytest
from apps.supply_chain.models import DispatchBatch, PaymentItem, PaymentRecord, SettlementRecord, SettlementRevision, domain_write
from tests.test_supply_chain_v2_logistics import create as create_batch, arrive as arrive_batch
from tests.test_supply_chain_v2_costs import fee_body


def itemized_batch(world):
    buyer, api, shipment = pilot(world)
    shipment = mark(buyer, shipment)
    carrier = freight(world)
    batch_data, _ = create_batch(api, [shipment], carrier, 'itemized-batch')
    batch_data = arrive_batch(api, batch_data)
    batch = DispatchBatch.objects.get(pk=batch_data['id'])
    with domain_write():
        profiles = [PaymentItem.objects.create(tenant=world['tenant'], created_by=buyer, name='海运费', party_type='carrier',
            default_nature='corporate', counts_as_cost=True), PaymentItem.objects.create(tenant=world['tenant'], created_by=buyer,
            name='清关费', party_type='both', default_nature='personal', counts_as_cost=True)]
    return buyer, api, batch, carrier, profiles


def save_itemized_fee(api, batch, profiles, total='30.0000', amounts=('20.0000', '10.0000')):
    context = get(api, 'batch', batch)
    body = fee_body(context, total, item_breakdown=[
        {'fee_item_id': profiles[0].pk, 'amount': amounts[0], 'nature': 'corporate'},
        {'fee_item_id': profiles[1].pk, 'amount': amounts[1], 'nature': 'personal'}])
    response = write(api, f'costs/batch/{batch.pk}/fee/', body, 'batch-item-fee', 'put')
    assert response.status_code == 200, response.data
    return response.data['data']


@pytest.mark.django_db(transaction=True)
def test_batch_fee_items_snapshot_total_cost_and_old_client_preserves_breakdown(world):
    buyer, api, batch, carrier, profiles = itemized_batch(world)
    saved = save_itemized_fee(api, batch, profiles)
    assert saved['fee']['amount'] == '30.0000'
    assert sum(Decimal(row['amount']) for row in saved['fee']['allocations']) == Decimal('30.0000')
    assert [row['name'] for row in saved['fee']['item_breakdown']] == ['海运费', '清关费']
    context = get(api, 'batch', batch)
    legacy_body = fee_body(context, '29.0000')
    mismatch = write(api, f'costs/batch/{batch.pk}/fee/', legacy_body, 'legacy-mismatch', 'put')
    assert mismatch.status_code == 422
    context = get(api, 'batch', batch)
    preserve = fee_body(context, '30.0000')
    okay = write(api, f'costs/batch/{batch.pk}/fee/', preserve, 'legacy-preserve', 'put')
    assert okay.status_code == 200 and len(okay.data['data']['fee']['item_breakdown']) == 2


@pytest.mark.django_db(transaction=True)
def test_item_payments_partial_balance_nature_reversal_and_cannot_remove_paid_item(world):
    buyer, api, batch, carrier, profiles = itemized_batch(world)
    save_itemized_fee(api, batch, profiles)
    payee_path = f'costs/freight_company/{carrier.pk}/payee-accounts/'
    corporate = write(api, payee_path, {'nature':'corporate','account_name':'公司账户','account_holder':'公司','bank_name':'银行','account_number':'1234567890','active':True}, 'item-corp').data['data']['account']['id']
    personal = write(api, payee_path, {'nature':'personal','account_name':'个人账户','account_holder':'个人','bank_name':'银行','account_number':'1234567891','active':True}, 'item-personal').data['data']['account']['id']
    url = f'costs/batch/{batch.pk}/payments/'
    state = api.get(BASE+url).data['data']
    bad = write(api, url, {'amount':'5.0000','date':'2026-10-20','payee_account_id':personal,'fee_item_id':profiles[0].pk,'expected_version':state['version']}, 'nature-bad')
    assert bad.status_code == 422
    payment = write(api, url, {'amount':'5.0000','date':'2026-10-20','payee_account_id':corporate,'fee_item_id':profiles[0].pk,'expected_version':state['version']}, 'item-pay-1')
    assert payment.status_code == 201, payment.data
    summary = payment.data['data']
    assert summary['fee_items'][0]['paid_amount'] == '5.0000'
    assert summary['fee_items'][0]['remaining_amount'] == '15.0000'
    context = get(api, 'batch', batch)
    delete_item = fee_body(context, '10.0000', item_breakdown=[{'fee_item_id':profiles[1].pk,'amount':'10.0000','nature':'personal'}])
    refused = write(api, f'costs/batch/{batch.pk}/fee/', delete_item, 'delete-paid-item', 'put')
    assert refused.status_code == 422
    reverse = write(api, f'costs/batch/{batch.pk}/payments/{summary["entries"][0]["id"]}/reverse/', {'reason':'冲销测试','expected_version':summary['version']}, 'item-reversal')
    assert reverse.status_code == 200
    assert reverse.data['data']['fee_items'][0]['paid_amount'] == '0.0000'


@pytest.mark.django_db(transaction=True)
def test_legacy_opening_blocks_itemized_mode_and_reversed_legacy_payment_does_not(world):
    buyer, api, batch, carrier, profiles = itemized_batch(world)
    # Legacy cumulative settlement is an unallocated opening and must block migration to item mode.
    with domain_write():
        settlement = SettlementRecord.objects.create(tenant=world['tenant'], created_by=buyer, batch=batch)
        revision = SettlementRevision.objects.create(tenant=world['tenant'], created_by=buyer, settlement=settlement,
            sequence=1, recorded_amount=Decimal('2.0000'), reference_number='OLD', date='2026-10-01',
            reason='legacy opening', source_snapshot={"legacy": True})
        settlement.current_revision=revision; settlement.version=1; settlement.save()
    context=get(api,'batch',batch)
    body=fee_body(context,'30.0000',item_breakdown=[{'fee_item_id':profiles[0].pk,'amount':'20','nature':'corporate'},{'fee_item_id':profiles[1].pk,'amount':'10','nature':'personal'}])
    blocked=write(api,f'costs/batch/{batch.pk}/fee/',body,'opening-block','put')
    assert blocked.status_code==422




@pytest.mark.django_db(transaction=True)
def test_reversed_unclassified_batch_payment_allows_itemized_mode(world):
    buyer, api, batch, carrier, profiles = itemized_batch(world)
    fee(api, 'batch', batch, '30.0000')
    payee_path=f'costs/freight_company/{carrier.pk}/payee-accounts/'
    account_id=write(api,payee_path,{'nature':'corporate','account_name':'公司账户','account_holder':'公司','bank_name':'银行','account_number':'1234567890','active':True},'legacy-batch-account').data['data']['account']['id']
    url=f'costs/batch/{batch.pk}/payments/'
    state=api.get(BASE+url).data['data']
    legacy=write(api,url,{'amount':'2.0000','date':'2026-10-20','payee_account_id':account_id,'expected_version':state['version']},'unclassified-batch-pay')
    assert legacy.status_code==201,legacy.data
    entry=legacy.data['data']['entries'][0]
    reversed_result=write(api,f'{url}{entry["id"]}/reverse/',{'reason':'纠正历史总额付款','expected_version':legacy.data['data']['version']},'unclassified-batch-reverse')
    assert reversed_result.status_code==200,reversed_result.data
    saved=save_itemized_fee(api,batch,profiles)
    assert len(saved['fee']['item_breakdown'])==2

@pytest.mark.django_db(transaction=True)
def test_inbound_itemized_payments_accounts_vouchers_reversal_and_fee_projection(world):
    buyer, api, _, batch_id, inbound_id = received_pilot(world)
    inbound_context = get(api, 'inbound', inbound_id)
    with domain_write():
        profiles = [PaymentItem.objects.create(tenant=world['tenant'], created_by=buyer, name='Clearance service',
            party_type='carrier', default_nature='corporate', counts_as_cost=True),
            PaymentItem.objects.create(tenant=world['tenant'], created_by=buyer, name='Port fee',
            party_type='both', default_nature='personal', counts_as_cost=True)]
    body = fee_body(inbound_context, '30.0000', item_breakdown=[
        {'fee_item_id': profiles[0].pk, 'amount': '20.0000', 'nature': 'corporate'},
        {'fee_item_id': profiles[1].pk, 'amount': '10.0000', 'nature': 'personal'}])
    saved = write(api, f'costs/inbound/{inbound_id}/fee/', body, 'inbound-itemized-fee', 'put')
    assert saved.status_code == 200, saved.data
    assert [x['name'] for x in saved.data['data']['fee']['item_breakdown']] == ['Clearance service', 'Port fee']

    # Inbound payee account context is tied to the batch freight company.
    accounts_path = f'costs/inbound/{inbound_id}/payee-accounts/'
    wrong = account(api, 'supplier', world['supplier'].pk)
    wrong_pay = write(api, f'costs/inbound/{inbound_id}/payments/', {
        'amount': '1.0000', 'date': '2026-10-20', 'payee_account_id': wrong,
        'expected_version': 0, 'fee_item_id': profiles[0].pk}, 'inbound-wrong-owner')
    assert wrong_pay.status_code == 422

    with domain_write():
        freight_company = FreightCompany.objects.create(tenant=world['tenant'], created_by=buyer,
            code='other-inbound-carrier', name='Other carrier', shipping_marks='OTHER')
        corporate = PayeeAccount.objects.create(tenant=world['tenant'], created_by=buyer,
            freight_company=freight_company, nature='corporate', account_name='Other carrier account',
            account_holder='Other carrier', bank_name='Bank', account_number='1122334455')
    wrong_carrier = write(api, f'costs/inbound/{inbound_id}/payments/', {
        'amount': '1.0000', 'date': '2026-10-20', 'payee_account_id': corporate.pk,
        'expected_version': 0, 'fee_item_id': profiles[0].pk}, 'inbound-wrong-carrier')
    assert wrong_carrier.status_code == 422

    state = api.get(BASE + f'costs/inbound/{inbound_id}/payments/')
    assert state.status_code == 200, state.data
    # Create an account owned by the actual batch carrier through the inbound context.
    account_id = write(api, accounts_path, {'nature': 'corporate', 'account_name': '实际承运商账户',
        'account_holder': '承运商', 'bank_name': '银行', 'account_number': '9988776655', 'active': True},
        'inbound-account').data['data']['account']['id']
    state = api.get(BASE + f'costs/inbound/{inbound_id}/payments/').data['data']
    created = write(api, f'costs/inbound/{inbound_id}/payments/', {
        'amount': '5.0000', 'date': '2026-10-20', 'payee_account_id': account_id,
        'expected_version': state['version'], 'fee_item_id': profiles[0].pk}, 'inbound-partial-payment')
    assert created.status_code == 201, created.data
    payment = next(x for x in created.data['data']['entries'] if x['entry_type'] == 'payment')
    assert created.data['data']['fee_items'][0]['paid_amount'] == '5.0000'
    assert created.data['data']['fee_items'][0]['remaining_amount'] == '15.0000'
    projection = api.get(BASE + 'cost-targets/', {'kind': 'inbound'}).data['data']
    owner = next(x for x in projection if x['id'] == inbound_id)
    assert owner['due_amount'] == '30.0000' and owner['paid_amount'] == '5.0000' and owner['remaining_amount'] == '25.0000'
    # Even if legacy state is restored to an editable stage, an effective inbound payment freezes its carrier owner.
    from apps.supply_chain.models import DispatchBatch
    batch = DispatchBatch.objects.get(pk=batch_id)
    with domain_write():
        batch.stage = 'unmarked'
        batch.save(update_fields=['stage'])
    from django.core.exceptions import ValidationError as DjangoValidationError
    with pytest.raises(DjangoValidationError, match='已有有效付款'):
        logistics.update_batch(buyer, batch.pk, {'expected_version': batch.version,
            'freight_company_id': freight_company.pk}, 'inbound-carrier-change')

    changed = fee_body(get(api, 'inbound', inbound_id), '30.0000', item_breakdown=[
        {'fee_item_id': profiles[0].pk, 'amount': '4.0000', 'nature': 'personal'},
        {'fee_item_id': profiles[1].pk, 'amount': '26.0000', 'nature': 'personal'}])
    refused = write(api, f'costs/inbound/{inbound_id}/fee/', changed, 'inbound-paid-item-edit', 'put')
    assert refused.status_code == 422

    from django.core.files.uploadedfile import SimpleUploadedFile
    endpoint = BASE + f'costs/inbound/{inbound_id}/payments/{payment["id"]}/vouchers/'
    uploaded = api.post(endpoint, {'file': SimpleUploadedFile('inbound.pdf', b'%PDF-1.4\nreceipt\n%%EOF', 'application/pdf')},
        format='multipart', HTTP_IDEMPOTENCY_KEY='inbound-voucher')
    assert uploaded.status_code == 201, uploaded.data
    assert api.get(endpoint).data['data'][0]['id'] == uploaded.data['data']['id']
    assert api.get(endpoint + f'{uploaded.data["data"]["id"]}/download/').status_code == 200

    reversed_state = write(api, f'costs/inbound/{inbound_id}/payments/{payment["id"]}/reverse/', {
        'reason': '撤销入库付款', 'expected_version': created.data['data']['version']}, 'inbound-reverse')
    assert reversed_state.status_code == 200, reversed_state.data
    assert reversed_state.data['data']['fee_items'][0]['paid_amount'] == '0.0000'
