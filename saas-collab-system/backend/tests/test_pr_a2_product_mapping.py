import pytest
from django.core.exceptions import ValidationError

from apps.common.exceptions import StateConflict
from apps.integrations.admin import MarketplaceProductMappingAdmin
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceProductMapping,
    MarketplaceStoreMapping,
)
from apps.integrations.product_mapping_service import (
    confirm_product_mapping,
    create_product_mapping,
    deactivate_mappings_for_sku,
    deactivate_product_mapping,
    sku_candidates_for_mapping,
    suggest_product_mapping,
)
from apps.integrations.store_mapping_service import (
    create_store_mapping,
    update_store_mapping,
)
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant
from tests.test_pr_a2_store_mapping import client_for, create_user, grant, mapping_context


MAPPINGS_URL = "/api/internal/integrations/product-mappings/"


def sku_for(tenant, code):
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code=f"spu-{code}",
        product_name=f"Product {code}",
    )
    return ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code=f"sku-{code}")


def base_mapping(code):
    tenant, user, store, _config, authorization = mapping_context(code)
    store_mapping = create_store_mapping(tenant=tenant, actor=user, store=store, authorization=authorization)
    return tenant, user, store_mapping


@pytest.mark.django_db
def test_product_mapping_write_bypasses_are_blocked():
    tenant, user, store_mapping = base_mapping("prod-guard")
    mapping = create_product_mapping(
        tenant=tenant,
        actor=user,
        store_mapping=store_mapping,
        platform_product_id="p-1",
        platform_variant_id="v-guard",
    )

    direct = MarketplaceProductMapping(
        tenant=tenant,
        platform="shopee",
        store_mapping=store_mapping,
        platform_product_id="p-1",
        platform_variant_id="v-guard-direct",
        mapping_source="manual",
        created_by=user,
        updated_by=user,
    )
    with pytest.raises(ValidationError, match="service layer"):
        direct.save()
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceProductMapping.objects.filter(pk=mapping.pk).update(status="inactive")
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceProductMapping.objects.bulk_create([direct])
    mapping.platform_sku = "forged"
    with pytest.raises(ValidationError, match="service layer"):
        MarketplaceProductMapping.objects.bulk_update([mapping], ["platform_sku"])
    with pytest.raises(ValidationError, match="cannot be deleted"):
        MarketplaceProductMapping.objects.filter(pk=mapping.pk).delete()
    with pytest.raises(ValidationError, match="cannot be deleted"):
        mapping.delete()

    mapping.refresh_from_db()
    assert mapping.platform_sku == ""
    assert mapping.status == MarketplaceProductMapping.Status.UNMAPPED
    assert MarketplaceProductMappingAdmin.has_add_permission(None, None) is False
    assert MarketplaceProductMappingAdmin.has_change_permission(None, None) is False
    assert MarketplaceProductMappingAdmin.has_delete_permission(None, None) is False


@pytest.mark.django_db
def test_create_product_mapping_validates_context():
    tenant, user, store_mapping = base_mapping("prod-create")
    mapping = create_product_mapping(
        tenant=tenant,
        actor=user,
        store_mapping=store_mapping,
        platform_product_id="p-1",
        platform_variant_id="v-1",
        platform_sku="synthetic-platform-sku",
    )
    assert mapping.status == MarketplaceProductMapping.Status.UNMAPPED
    assert mapping.platform == store_mapping.platform
    assert mapping.sku_id is None
    assert mapping.manually_confirmed is False
    assert mapping.last_verified_at is not None
    assert IntegrationAuditLog.objects.filter(tenant=tenant, action="product_mapping_create").exists()

    with pytest.raises(StateConflict):
        create_product_mapping(
            tenant=tenant,
            actor=user,
            store_mapping=store_mapping,
            platform_product_id="p-2",
            platform_variant_id="v-1",
        )
    with pytest.raises(ValidationError, match="identifier"):
        create_product_mapping(
            tenant=tenant,
            actor=user,
            store_mapping=store_mapping,
            platform_product_id="",
            platform_variant_id="v-2",
        )

    inactive = update_store_mapping(store_mapping, actor=user, status=MarketplaceStoreMapping.Status.INACTIVE)
    with pytest.raises(ValidationError, match="active store mapping"):
        create_product_mapping(
            tenant=tenant,
            actor=user,
            store_mapping=inactive,
            platform_product_id="p-3",
            platform_variant_id="v-3",
        )

    other_tenant = Tenant.objects.create(name="Tenant prod-intruder", code="prod-intruder")
    intruder = create_user(other_tenant, "user-prod-intruder")
    with pytest.raises(ValidationError, match="actor"):
        create_product_mapping(
            tenant=tenant,
            actor=intruder,
            store_mapping=store_mapping,
            platform_product_id="p-4",
            platform_variant_id="v-4",
        )


@pytest.mark.django_db
def test_suggest_validates_sku_tenant_and_confidence():
    tenant, user, store_mapping = base_mapping("prod-suggest")
    mapping = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-1", platform_variant_id="v-suggest",
    )
    sku = sku_for(tenant, "prod-suggest")

    other_tenant = Tenant.objects.create(name="Tenant prod-other", code="prod-other")
    foreign_sku = sku_for(other_tenant, "prod-foreign")
    with pytest.raises(ValidationError, match="tenant"):
        suggest_product_mapping(mapping, actor=user, sku=foreign_sku, confidence=90)
    with pytest.raises(ValidationError, match="Confidence"):
        suggest_product_mapping(mapping, actor=user, sku=sku, confidence=True)
    with pytest.raises(ValidationError, match="Confidence"):
        suggest_product_mapping(mapping, actor=user, sku=sku, confidence=120)

    suggested = suggest_product_mapping(mapping, actor=user, sku=sku, confidence=87)
    assert suggested.status == MarketplaceProductMapping.Status.SUGGESTED
    assert suggested.sku_id == sku.id
    assert suggested.product_id == sku.spu_id
    assert suggested.confidence == 87
    assert suggested.manually_confirmed is False
    assert IntegrationAuditLog.objects.filter(tenant=tenant, action="product_mapping_suggest").exists()

    previous_verified = suggested.last_verified_at
    refreshed = suggest_product_mapping(suggested, actor=user, sku=sku, confidence=95)
    assert refreshed.confidence == 95

    conflicted = confirm_product_mapping(refreshed, actor=user, manually_confirmed=True)
    same_sku = suggest_product_mapping(conflicted, actor=user, sku=sku, confidence=50)
    assert same_sku.status == MarketplaceProductMapping.Status.MAPPED
    assert same_sku.last_verified_at >= previous_verified

    deactivate_product_mapping(same_sku, actor=user)
    same_sku.refresh_from_db()
    with pytest.raises(StateConflict):
        suggest_product_mapping(same_sku, actor=user, sku=sku, confidence=50)


@pytest.mark.django_db
def test_suggest_conflict_keeps_previous_mapping():
    tenant, user, store_mapping = base_mapping("prod-conflict")
    mapping = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-1", platform_variant_id="v-conflict",
    )
    sku_a = sku_for(tenant, "prod-conflict-a")
    sku_b = sku_for(tenant, "prod-conflict-b")
    mapping = suggest_product_mapping(mapping, actor=user, sku=sku_a, confidence=92)
    mapping = confirm_product_mapping(mapping, actor=user, manually_confirmed=True)

    conflicted = suggest_product_mapping(mapping, actor=user, sku=sku_b, confidence=60)
    assert conflicted.status == MarketplaceProductMapping.Status.CONFLICT
    assert conflicted.sku_id == sku_a.id
    assert conflicted.result_code == "MAPPING_CONFLICT"
    audit = IntegrationAuditLog.objects.get(tenant=tenant, action="product_mapping_conflict")
    assert audit.masked_detail["kept_sku_id"] == sku_a.id
    assert audit.masked_detail["conflicting_sku_id"] == sku_b.id


@pytest.mark.django_db
def test_confirm_requires_manual_approval_and_unique_sku():
    tenant, user, store_mapping = base_mapping("prod-confirm")
    sku = sku_for(tenant, "prod-confirm")
    mapping = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-1", platform_variant_id="v-confirm",
    )

    with pytest.raises(ValidationError, match="manual approval"):
        confirm_product_mapping(mapping, actor=user, sku=sku)

    mapping = suggest_product_mapping(mapping, actor=user, sku=sku, confidence=80)
    confirmed = confirm_product_mapping(mapping, actor=user, manually_confirmed=True)
    assert confirmed.status == MarketplaceProductMapping.Status.MAPPED
    assert confirmed.manually_confirmed is True
    assert confirmed.product_id == sku.spu_id
    assert confirmed.result_code == ""
    assert IntegrationAuditLog.objects.filter(tenant=tenant, action="product_mapping_confirm").exists()

    # Idempotent re-confirmation with the same SKU.
    again = confirm_product_mapping(confirmed, actor=user, manually_confirmed=True)
    assert again.status == MarketplaceProductMapping.Status.MAPPED

    # The same SKU cannot be mapped to a second variant in the same store.
    second = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-2", platform_variant_id="v-confirm-2",
    )
    second = suggest_product_mapping(second, actor=user, sku=sku, confidence=77)
    with pytest.raises(StateConflict, match="already mapped"):
        confirm_product_mapping(second, actor=user, manually_confirmed=True)

    # Conflict records can be resolved back to mapped with a chosen SKU.
    other_sku = sku_for(tenant, "prod-confirm-other")
    conflicted = suggest_product_mapping(confirmed, actor=user, sku=other_sku, confidence=55)
    assert conflicted.status == MarketplaceProductMapping.Status.CONFLICT
    resolved = confirm_product_mapping(conflicted, actor=user, sku=other_sku, manually_confirmed=True)
    assert resolved.status == MarketplaceProductMapping.Status.MAPPED
    assert resolved.sku_id == other_sku.id

    # Unmapped records cannot be confirmed directly.
    fresh = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-3", platform_variant_id="v-confirm-3",
    )
    with pytest.raises(StateConflict):
        confirm_product_mapping(fresh, actor=user, sku=other_sku, manually_confirmed=True)


@pytest.mark.django_db
def test_deactivate_and_sku_invalidation():
    tenant, user, store_mapping = base_mapping("prod-deactivate")
    sku = sku_for(tenant, "prod-deactivate")
    mapping = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-1", platform_variant_id="v-deactivate",
    )
    mapping = suggest_product_mapping(mapping, actor=user, sku=sku, confidence=80)

    with pytest.raises(ValidationError, match="controlled"):
        deactivate_product_mapping(mapping, actor=user, result_code="lower-case")

    deactivated = deactivate_product_mapping(mapping, actor=user)
    assert deactivated.status == MarketplaceProductMapping.Status.INACTIVE
    assert deactivated.result_code == "MANUAL_DEACTIVATED"
    assert deactivate_product_mapping(deactivated, actor=user).status == MarketplaceProductMapping.Status.INACTIVE
    audit = IntegrationAuditLog.objects.filter(tenant=tenant, action="product_mapping_deactivate").latest("id")
    assert audit.masked_detail["result_code"] == "MANUAL_DEACTIVATED"

    # Controlled SKU invalidation moves every live mapping to inactive; nothing is deleted.
    second = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-2", platform_variant_id="v-deactivate-2",
    )
    second = suggest_product_mapping(second, actor=user, sku=sku, confidence=70)
    second = confirm_product_mapping(second, actor=user, manually_confirmed=True)

    invalidated = deactivate_mappings_for_sku(sku, actor=user)
    assert {record.id for record in invalidated} == {second.id}
    second.refresh_from_db()
    assert second.status == MarketplaceProductMapping.Status.INACTIVE
    assert second.result_code == "SKU_INVALIDATED"
    assert MarketplaceProductMapping.objects.filter(sku=sku).count() == 2

    candidates = sku_candidates_for_mapping(second)
    assert list(candidates) == [sku]
    assert foreign_sku_not_leaked(candidates, tenant)


def foreign_sku_not_leaked(candidates, tenant):
    return all(candidate.tenant_id == tenant.id for candidate in candidates)


@pytest.mark.django_db
def test_product_mapping_api_permission_and_create():
    tenant, user, store_mapping = base_mapping("prod-api-perm")
    client = client_for(user)
    payload = {
        "store_mapping_id": store_mapping.id,
        "platform_product_id": "p-api",
        "platform_variant_id": "v-api",
        "platform_sku": "synthetic-api-sku",
    }

    assert client.post(MAPPINGS_URL, payload, format="json").status_code == 403
    grant(user, "integrations.store.view")
    assert client.post(MAPPINGS_URL, payload, format="json").status_code == 403

    grant(user, "integrations.store.authorize")
    response = client.post(MAPPINGS_URL, payload, format="json")
    assert response.status_code == 201
    data = response.json()["data"]
    assert data["status"] == "unmapped"
    assert data["platform"] == "shopee"
    assert data["sku_id"] is None
    assert data["manually_confirmed"] is False
    assert data["mapping_source"] == "manual"

    duplicate = client.post(MAPPINGS_URL, payload, format="json")
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "STATE_CONFLICT"

    cross_store = client.post(
        MAPPINGS_URL,
        {**payload, "store_mapping_id": 999999, "platform_variant_id": "v-api-missing"},
        format="json",
    )
    assert cross_store.status_code == 404
    assert cross_store.json()["code"] == "RESOURCE_NOT_FOUND"


@pytest.mark.django_db
def test_product_mapping_api_rejects_forbidden_fields_and_raw_credentials():
    tenant, user, store_mapping = base_mapping("prod-api-forbid")
    grant(user, "integrations.store.authorize")
    client = client_for(user)
    base_payload = {
        "store_mapping_id": store_mapping.id,
        "platform_product_id": "p-forbid",
        "platform_variant_id": "v-forbid",
    }

    for forbidden_field, value in [
        ("status", "mapped"),
        ("sku_id", 1),
        ("manually_confirmed", True),
        ("confidence", 99),
        ("tenant_id", 999),
    ]:
        response = client.post(MAPPINGS_URL, {**base_payload, forbidden_field: value}, format="json")
        assert response.status_code == 400, forbidden_field
        assert response.json()["code"] == "VALIDATION_ERROR"

    raw = client.post(MAPPINGS_URL, {**base_payload, "access_token": "raw"}, format="json")
    assert raw.status_code == 422
    assert raw.json()["code"] == "BUSINESS_RULE_VIOLATION"
    assert not MarketplaceProductMapping.objects.filter(tenant=tenant).exists()


@pytest.mark.django_db
def test_product_mapping_api_patch_dispatch():
    tenant, user, store_mapping = base_mapping("prod-api-patch")
    sku = sku_for(tenant, "prod-api-patch")
    mapping = create_product_mapping(
        tenant=tenant, actor=user, store_mapping=store_mapping,
        platform_product_id="p-patch", platform_variant_id="v-patch",
    )
    grant(user, "integrations.store.authorize")
    grant(user, "integrations.store.view")
    client = client_for(user)
    url = f"{MAPPINGS_URL}{mapping.id}/"

    assert client.patch(url, {}, format="json").status_code == 400
    assert client.patch(url, {"sku_id": sku.id}, format="json").status_code == 400

    suggested = client.patch(url, {"sku_id": sku.id, "confidence": 84}, format="json")
    assert suggested.status_code == 200
    assert suggested.json()["data"]["status"] == "suggested"
    assert suggested.json()["data"]["sku_code"] == sku.sku_code

    confirmed = client.patch(url, {"manually_confirmed": True}, format="json")
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "mapped"
    assert confirmed.json()["data"]["manually_confirmed"] is True

    deactivated = client.patch(url, {"status": "inactive"}, format="json")
    assert deactivated.status_code == 200
    assert deactivated.json()["data"]["status"] == "inactive"
    assert deactivated.json()["data"]["result_code"] == "MANUAL_DEACTIVATED"

    raw = client.patch(url, {"status": "inactive", "refresh_token": "raw"}, format="json")
    assert raw.status_code == 422

    foreign_tenant = Tenant.objects.create(name="Tenant prod-patch-other", code="prod-patch-other")
    foreign_sku = sku_for(foreign_tenant, "prod-patch-foreign")
    foreign = client.patch(url, {"sku_id": foreign_sku.id, "confidence": 50}, format="json")
    assert foreign.status_code == 404


@pytest.mark.django_db
def test_product_mapping_query_filters_and_cross_tenant_hidden():
    tenant, owner, store_mapping = base_mapping("prod-api-query")
    create_product_mapping(
        tenant=tenant, actor=owner, store_mapping=store_mapping,
        platform_product_id="p-q", platform_variant_id="v-q",
    )

    other_tenant = Tenant.objects.create(name="Tenant prod-api-intruder", code="prod-api-intruder")
    intruder = create_user(other_tenant, "user-prod-api-intruder")
    grant(intruder, "integrations.store.view")
    grant(intruder, "integrations.store.authorize")
    intruder_client = client_for(intruder)
    listing = intruder_client.get(MAPPINGS_URL)
    assert listing.status_code == 200
    assert listing.json()["data"]["count"] == 0

    mapping_id = MarketplaceProductMapping.objects.get(tenant=tenant).id
    assert intruder_client.get(f"{MAPPINGS_URL}{mapping_id}/").status_code == 404
    assert (
        intruder_client.patch(f"{MAPPINGS_URL}{mapping_id}/", {"status": "inactive"}, format="json").status_code
        == 404
    )

    grant(owner, "integrations.store.view")
    client = client_for(owner)
    assert client.get(MAPPINGS_URL + "?unknown=1").status_code == 400
    assert client.get(MAPPINGS_URL + "?platform=bigseller").status_code == 400
    assert client.get(MAPPINGS_URL + "?status=weird").status_code == 400

    filtered = client.get(f"{MAPPINGS_URL}?platform=shopee&status=unmapped&store_mapping_id={store_mapping.id}")
    assert filtered.status_code == 200
    assert filtered.json()["data"]["count"] == 1
