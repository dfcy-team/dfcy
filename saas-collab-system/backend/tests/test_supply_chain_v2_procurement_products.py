from datetime import date
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.products.models import ProductSKU, ProductSPU
from apps.supply_chain import services
from apps.supply_chain.models import SupplierProductPrice, domain_write
from apps.tenants.models import Tenant
from tests.test_supply_chain_v2_foundation import internal_user, po_payload, world

BASE = "/api/internal/supply-chain/v2/"


def client(user=None):
    api = APIClient()
    if user:
        api.force_authenticate(user=user)
    return api


@pytest.mark.django_db
def test_purchase_mutations_keep_product_details_and_saved_price(world):
    buyer = internal_user(world)
    sku = world['sku']
    sku.legacy_sku_code, sku.specification = 'OLD-ROUNDTRIP', '本次下单规格'
    sku.save()
    api = client(buyer)
    body = po_payload(world, key='product-roundtrip')
    body['lines'][0]['unit_price'] = '7.5000'
    response = api.post(BASE + 'purchase-orders/', body, format='json', HTTP_IDEMPOTENCY_KEY='product-roundtrip')
    assert response.status_code == 201, response.data
    data = response.data['data']
    line = data['lines'][0]
    assert line['unit_price'] == '7.5000' and line['legacy_sku_code'] == 'OLD-ROUNDTRIP'
    assert line['product_details']['specification'] == '本次下单规格'
    assert line['image_preview_url'].startswith('/api/internal/')
    label = api.get(line['label_pdf_url'])
    assert label.status_code == 200 and b''.join(label.streaming_content).startswith(b'%PDF')
    assert api.get(BASE + f"purchase-orders/{data['id']}/skus/{world['sku_b'].pk}/labels/").status_code == 404
    response = api.patch(BASE + f"purchase-orders/{data['id']}/", {**body, 'expected_version': data['version']},
                         format='json', HTTP_IDEMPOTENCY_KEY='product-roundtrip-save')
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['lines'][0]['product_details']['specification'] == '本次下单规格'
    response = api.post(BASE + f"purchase-orders/{data['id']}/confirm/", {'expected_version': data['version']},
                        format='json', HTTP_IDEMPOTENCY_KEY='product-roundtrip-confirm')
    assert response.status_code == 200, response.data
    data = response.data['data']
    assert data['lines'][0]['product_details_source'] == 'confirmation'
    sku.specification = '后续档案规格'
    sku.save()
    response = api.patch(BASE + f"purchase-orders/{data['id']}/metadata/", {'expected_version': data['version'], 'reference_number': '', 'notes': '只改备注'},
                         format='json', HTTP_IDEMPOTENCY_KEY='product-roundtrip-metadata')
    assert response.status_code == 200, response.data
    assert response.data['data']['lines'][0]['product_details']['specification'] == '本次下单规格'


@pytest.mark.django_db
def test_sku_options_search_legacy_and_new_codes_with_reference_prices(world):
    buyer = internal_user(world)
    sku = world["sku"]
    sku.sku_code = "NEW-SC2-001"
    sku.legacy_sku_code = "OLD-SC2-001"
    sku.purchase_price = Decimal("3.2500")
    sku.specification = "15L"
    sku.spec_values = {"Capacity": "15L"}
    sku.material = "PP"
    sku.save()
    with domain_write():
        SupplierProductPrice.objects.create(tenant=world["tenant"], created_by=buyer,
            supplier=world["supplier"], sku=sku, unit_price=Decimal("4.5000"),
            effective_date=date(2026, 10, 14), source_kind="manual")
    api = client(buyer)

    old_match = api.get(BASE + "options/", {"kind": "skus", "search": "OLD-SC2-001", "supplier_id": world["supplier"].pk, "limit": 1, "offset": 0})
    assert old_match.status_code == 200
    assert old_match.data["count"] == 1 and len(old_match.data["data"]) == 1
    row = old_match.data["data"][0]
    assert (row["sku"], row["legacy_sku_code"]) == (sku.sku_code, "OLD-SC2-001")
    assert row["product_reference_price"] == "3.2500"
    assert row["supplier_reference_price"] == "4.5000"
    assert row["product_details"]["specification"] == "15L"
    assert row["product_details"]["spec_values"] == {"Capacity": "15L"}

    new_match = api.get(BASE + "options/", {"kind": "skus", "search": sku.sku_code})
    assert new_match.status_code == 200 and new_match.data["count"] == 1


@pytest.mark.django_db
def test_bulk_sku_resolver_exact_codes_tenant_product_rules_and_cap(world):
    buyer = internal_user(world)
    sku = world["sku"]
    sku.sku_code, sku.legacy_sku_code = "EXACT-NEW", "EXACT-OLD"
    sku.save()
    api = client(buyer)
    response = api.post(BASE + "options/", {"codes": ["EXACT-NEW", "EXACT-OLD", "not-exact"]}, format="json")
    assert response.status_code == 200, response.data
    rows = response.data["data"]
    assert rows[0]["item"]["id"] == sku.pk and rows[1]["item"]["id"] == sku.pk
    assert rows[2]["item"] is None and rows[2]["error"]
    too_many = api.post(BASE + "options/", {"codes": ["x"] * 501}, format="json")
    assert too_many.status_code == 400

    virtual = ProductSPU.objects.create(tenant=world["tenant"], spu_code="VIRTUAL-BULK", product_type="virtual")
    virtual_sku = ProductSKU.objects.create(tenant=world["tenant"], spu=virtual, sku_code="VIRTUAL-BULK-SKU")
    response = api.post(BASE + "options/", {"codes": ["VIRTUAL-BULK-SKU"]}, format="json")
    assert response.status_code == 200 and response.data["data"][0]["item"] is None


@pytest.mark.django_db
def test_purchase_detail_and_order_image_use_frozen_product_details(world, monkeypatch):
    buyer = internal_user(world)
    sku = world["sku"]
    sku.legacy_sku_code = "OLD-FROZEN"
    sku.specification, sku.material, sku.color_code = "首发规格", "PP", "蓝色"
    sku.image_url = f"/media/product-images/tenant-{world['tenant'].pk}/frozen.png"
    sku.spec_values = {"Capacity": "15L"}
    sku.save()
    order = services.create_purchase_order(buyer, po_payload(world, key="product-detail"), idempotency_key="product-detail")
    services.confirm_purchase_order(buyer, order.pk, expected_version=order.version, idempotency_key="confirm-product-detail")
    sku.specification = "后续修改"
    sku.image_url = f"/media/product-images/tenant-{world['tenant'].pk}/current.png"
    sku.save()

    response = client(buyer).get(BASE + f"purchase-orders/{order.pk}/")
    assert response.status_code == 200
    line = response.data["data"]["lines"][0]
    assert line["legacy_sku_code"] == "OLD-FROZEN"
    assert line["product_details"]["specification"] == "首发规格"
    assert line["product_details"]["spec_values"] == {"Capacity": "15L"}
    assert line["product_details_source"] == "confirmation"

    image_requests = []
    def images(snapshot, tenant_id):
        image_requests.append((snapshot, tenant_id))
        return {sku.pk: {"body": b"order-image", "status": "available"}}
    monkeypatch.setattr("apps.supply_chain.internal_product_images.load_product_images", images)
    image = client(buyer).get(BASE + f"purchase-orders/{order.pk}/skus/{sku.pk}/image/")
    assert image.status_code == 200
    assert b"".join(image.streaming_content) == b"order-image"
    assert image_requests[0][0]["lines"][0]["product_details"]["image_url"].endswith("/frozen.png")
    assert client(buyer).get(BASE + f"purchase-orders/{order.pk}/skus/{world['sku_b'].pk}/image/").status_code == 404
    assert len(image_requests) == 1


@pytest.mark.django_db
def test_internal_sku_image_is_tenant_and_active_scoped(world, monkeypatch):
    buyer = internal_user(world)
    sku = world["sku"]
    sku.image_url = f"/media/product-images/tenant-{world['tenant'].pk}/sku.png"
    sku.save()
    url = BASE + f"options/skus/{sku.pk}/image/"
    calls = []

    def images(snapshot, tenant_id):
        calls.append((snapshot, tenant_id))
        return {sku.pk: {"body": b"safe-jpeg", "status": "available"}}

    monkeypatch.setattr("apps.supply_chain.internal_product_images.load_product_images", images)
    api = client(buyer)
    response = api.get(url)
    assert response.status_code == 200, getattr(response, "data", None)
    assert b"".join(response.streaming_content) == b"safe-jpeg"
    assert response["Content-Type"] == "image/jpeg"
    assert response["Cache-Control"] == "private, no-store"
    assert calls[0][0]["lines"][0]["product_details"]["image_url"].endswith("/sku.png")
    assert calls[0][1] == world["tenant"].pk

    sku.is_active = False
    sku.save()
    calls.clear()
    assert api.get(url).status_code == 404
    assert calls == []
    assert client().get(url).status_code == 401

    foreign_tenant = Tenant.objects.create(name="Other tenant", code="sc2-other-tenant")
    foreign_spu = ProductSPU.objects.create(tenant=foreign_tenant, spu_code="OTHER-SPU", product_name="Other")
    foreign_sku = ProductSKU.objects.create(tenant=foreign_tenant, spu=foreign_spu, sku_code="OTHER-SKU")
    assert api.get(BASE + f"options/skus/{foreign_sku.pk}/image/").status_code == 404
