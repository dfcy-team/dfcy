"""New/old code consistency must hold outside the CSV importer as well."""

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.product_mapping_service import auto_associate_product_mapping, create_product_mapping
from apps.listings.models import PlatformProductDetail
from apps.products.models import ProductSKU
from tests.test_platform_product_details import fixture_data, _grant_detail_manage
from tests.test_mapping_consolidation import _fixture as mapping_fixture


pytestmark = pytest.mark.django_db


def _setup():
    tenant, platform, store, sku = fixture_data()
    user = CustomUser.objects.get(tenant=tenant)
    _grant_detail_manage(user, tenant)
    other = ProductSKU.objects.create(
        tenant=tenant, spu=sku.spu, sku_code="NEW-2", legacy_sku_code="OLD-2", purchase_price=1,
    )
    detail = PlatformProductDetail.objects.create(
        tenant=tenant, platform=platform, store=store,
        platform_product_id="P-1", platform_variant_id="V-1",
        internal_sku=sku, source_old_sku_code="OLD-1",
    )
    client = APIClient()
    client.force_authenticate(user)
    return client, detail, sku, other


@pytest.mark.parametrize("payload", [
    {"new_sku_code": "NEW-1", "source_old_sku_code": "OLD-2"},
    {"new_sku_code": "NEW-1", "source_old_sku_code": "missing-old"},
])
def test_patch_rejects_inconsistent_dual_codes_without_writing(payload):
    client, detail, sku, _ = _setup()
    response = client.patch(f"/api/internal/listings/product-details/{detail.pk}/", payload, format="json")
    assert response.status_code == 400, response.data
    detail.refresh_from_db()
    assert detail.internal_sku_id == sku.pk
    assert detail.source_old_sku_code == "OLD-1"


def test_internal_id_does_not_bypass_new_or_legacy_code_assertion():
    client, detail, sku, other = _setup()
    for payload in (
        {"internal_sku": other.pk, "source_old_sku_code": "OLD-1"},
        {"internal_sku": other.pk, "new_sku_code": "NEW-1", "source_old_sku_code": "OLD-1"},
    ):
        response = client.patch(f"/api/internal/listings/product-details/{detail.pk}/", payload, format="json")
        assert response.status_code == 400, response.data
    detail.refresh_from_db()
    assert detail.internal_sku_id == sku.pk


def test_patch_accepts_consistent_pair_and_api_pending_title_edit():
    client, detail, _, other = _setup()
    response = client.patch(f"/api/internal/listings/product-details/{detail.pk}/", {
        "new_sku_code": "NEW-2", "source_old_sku_code": "OLD-2",
    }, format="json")
    assert response.status_code == 200, response.data
    detail.refresh_from_db()
    assert detail.internal_sku_id == other.pk
    detail.internal_sku = None
    detail.source_old_sku_code = ""
    detail.source = "api"
    detail.save()
    response = client.patch(f"/api/internal/listings/product-details/{detail.pk}/", {"title": "Reviewed"}, format="json")
    assert response.status_code == 200, response.data
    detail.refresh_from_db()
    assert detail.internal_sku_id is None and detail.title == "Reviewed"


def test_bulk_rejects_mismatched_new_old_codes_before_writing():
    client, detail, sku, _ = _setup()
    response = client.post("/api/internal/listings/product-details/bulk-update/", {
        "match_type": "new_spu", "spu_code": sku.spu.spu_code, "ids": [detail.id],
        "fields": {"new_sku_code": "NEW-1", "source_old_sku_code": "OLD-2"},
    }, format="json")
    assert response.status_code == 400, response.data
    detail.refresh_from_db()
    assert detail.source_old_sku_code == "OLD-1"


def test_bulk_accepts_same_new_code_alias_for_mapped_detail_and_updates_title():
    context = mapping_fixture()
    user = context["user"]
    _grant_detail_manage(user, context["tenant"])
    detail = context["detail"]
    detail.internal_sku = context["sku_old"]
    detail.save(update_fields=["internal_sku"])
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=user,
        store_mapping=context["store_mapping"],
        platform_detail=detail,
    )
    auto_associate_product_mapping(mapping, actor=user, sku=context["sku_old"])

    client = APIClient()
    client.force_authenticate(user)
    response = client.post("/api/internal/listings/product-details/bulk-update/", {
        "match_type": "new_spu",
        "spu_code": context["sku_old"].spu.spu_code,
        "ids": [detail.id],
        "fields": {"new_sku_code": context["sku_old"].sku_code, "title": "Bulk reviewed"},
    }, format="json")

    assert response.status_code == 200, response.data
    assert response.data["data"]["updated"] == 1
    assert response.data["data"]["unchanged"] == 0
    assert response.data["data"]["errors"] == []
    detail.refresh_from_db()
    assert detail.title == "Bulk reviewed"
    assert detail.internal_sku_id == context["sku_old"].id
