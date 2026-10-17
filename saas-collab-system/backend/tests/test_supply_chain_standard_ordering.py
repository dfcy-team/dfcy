from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from openpyxl import Workbook
from apps.supply_chain import services
from apps.supply_chain.documents import IMPORT_HEADERS, IMPORT_SHEET
from apps.supply_chain.imports import commit_import, create_import
from apps.supply_chain.models import BusinessEvent, PurchaseOrder
from tests.test_supply_chain_v2_foundation import world, internal_user, po_payload
from tests.test_operating_orders_v2 import operator, client, write, OPS, SUPPLY


def bundle(world):
    spu = world['sku'].spu
    spu.product_type = 'bundle'
    spu.save()


def import_excel(world):
    book = Workbook()
    sheet = book.active
    sheet.title = IMPORT_SHEET
    sheet.append(IMPORT_HEADERS)
    sheet.append(['group-1', world['supplier'].code, world['country'].code,
                  world['sku'].sku_code, 2, '1.25', '', '', ''])
    output = BytesIO()
    book.save(output)
    return output.getvalue()


def test_excel_import_rejects_bundle_before_preview_commit(world):
    buyer = internal_user(world)
    bundle(world)
    job = create_import(buyer, 'bundle.xlsx', import_excel(world), idempotency_key='bundle-import')

    assert not job.preview['valid']
    assert '组合商品不能参与订货' in job.preview['errors'][0]['message']
    with pytest.raises(ValidationError, match='修正预览错误'):
        commit_import(buyer, job.pk, expected_version=1, idempotency_key='bundle-commit')
    assert not PurchaseOrder.objects.exists()


def test_excel_import_rolls_back_if_sku_becomes_bundle_after_preview(world):
    buyer = internal_user(world)
    job = create_import(buyer, 'standard.xlsx', import_excel(world), idempotency_key='standard-import')
    assert job.preview['valid']

    bundle(world)
    orders_before = PurchaseOrder.objects.count()
    events_before = BusinessEvent.objects.count()
    with pytest.raises(ValidationError, match='普通商品'):
        commit_import(buyer, job.pk, expected_version=1, idempotency_key='bundle-after-preview')

    job.refresh_from_db()
    assert PurchaseOrder.objects.count() == orders_before
    assert BusinessEvent.objects.count() == events_before
    assert job.version == 1 and job.committed_at is None and job.order_ids == []


def test_bundle_hidden_from_both_selectors_and_rejected_on_save(world):
    buyer, ops = internal_user(world), operator(world)
    bundle(world)
    assert client(buyer).get(SUPPLY+'options/', {'kind':'skus'}).data['count'] == 0
    assert client(ops).get('/api/internal/commerce/operating-options/', {'kind':'skus'}).data['count'] == 0
    with pytest.raises(ValidationError, match='普通商品'):
        services.create_purchase_order(buyer, po_payload(world), idempotency_key='bundle')
    response = write(client(ops), OPS, {'country_id':world['country'].pk, 'source_kind':'new_goods',
        'lines':[{'sku_id':world['sku'].pk,'quantity':10}]}, 'bundle-demand')
    assert response.status_code == 422


def test_draft_cannot_submit_after_product_changes_to_bundle(world):
    buyer, ops = internal_user(world), operator(world)
    order = services.create_purchase_order(buyer, po_payload(world), idempotency_key='normal')
    response = write(client(ops), OPS, {'country_id':world['country'].pk, 'source_kind':'new_goods',
        'lines':[{'sku_id':world['sku'].pk,'quantity':10}]}, 'normal-demand')
    assert response.status_code == 201
    demand = response.data['data']
    bundle(world)
    with pytest.raises(ValidationError, match='普通商品'):
        services.confirm_purchase_order(buyer, order.pk, expected_version=order.version,idempotency_key='confirm')
    response = write(client(ops), OPS+str(demand['id'])+'/submit/', {'expected_version':demand['version']}, 'submit')
    assert response.status_code == 422
