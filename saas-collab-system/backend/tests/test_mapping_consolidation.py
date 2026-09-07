from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.integrations.models import (
    IntegrationAuditLog,
    MarketplaceStoreAuthorization,
    MarketplaceStoreMapping,
    PlatformIntegrationConfig,
    authorization_service_write,
    marketplace_identity_key,
    marketplace_store_binding_key,
)
from apps.integrations.product_mapping_service import (
    confirm_product_mapping,
    create_product_mapping,
    suggest_product_mapping,
)
from apps.integrations.serializers import ProductMappingUpdateSerializer
from apps.integrations.store_mapping_service import create_store_mapping, update_store_mapping
from apps.listings.models import PlatformProductDetail
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _fixture():
    tenant = Tenant.objects.create(name="Mapping consolidation", code="mapping-consolidation")
    user = CustomUser.objects.create_user(
        username="mapping-consolidation-user",
        password="test-password",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    other_tenant = Tenant.objects.create(name="Other mapping tenant", code="other-mapping")
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
    )
    other_platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="tiktok",
        name="TikTok",
        platform_type="tiktok",
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="store-my",
        name="Store MY",
        country_code="MY",
        currency="MYR",
    )
    other_store = StoreMaster.objects.create(
        tenant=tenant,
        platform=other_platform,
        code="store-th",
        name="Store TH",
        country_code="TH",
        currency="THB",
    )
    other_tenant_platform = PlatformMaster.objects.create(
        tenant=other_tenant,
        code="shopee",
        name="Shopee",
        platform_type="shopee",
    )
    other_tenant_store = StoreMaster.objects.create(
        tenant=other_tenant,
        platform=other_tenant_platform,
        code="other-store",
        name="Other Store",
        country_code="MY",
        currency="MYR",
    )
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant,
        platform="shopee",
        account_alias="Shopee mapping",
        environment=PlatformIntegrationConfig.Environment.PILOT,
        status=PlatformIntegrationConfig.Status.VERIFIED,
        regions=["MY"],
        created_by=user,
    )
    external_id = "shop-my-1"
    identity = marketplace_identity_key("shopee", "MY", external_id)
    with authorization_service_write():
        authorization = MarketplaceStoreAuthorization.objects.create(
            tenant=tenant,
            integration_config=config,
            store=store,
            platform="shopee",
            region="MY",
            platform_store_id=external_id,
            platform_identity_key=identity,
            active_platform_identity_key=identity,
            active_store_binding_key=marketplace_store_binding_key(tenant.id, "shopee", store.id),
            merchant_subject_id="merchant-my",
            credential_id="credential-ref",
            token_id="token-ref",
            credential_mask={"token": "********"},
            status=MarketplaceStoreAuthorization.Status.ACTIVE,
            authorized_at=timezone.now(),
            created_by=user,
            updated_by=user,
        )
    store_mapping = create_store_mapping(
        tenant=tenant,
        actor=user,
        store=store,
        authorization=authorization,
        store_timezone="Asia/Kuala_Lumpur",
        currency="MYR",
    )
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-MAP", product_name="Mapping product")
    sku_old = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="NEW-OLD",
        legacy_sku_code="OLD-SKU",
        purchase_price=Decimal("1"),
    )
    sku_new = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="NEW-NEW",
        legacy_sku_code="OLD-NEW",
        purchase_price=Decimal("1"),
    )
    detail = PlatformProductDetail.objects.create(
        tenant=tenant,
        platform=platform,
        store=store,
        platform_product_id="P-1",
        platform_variant_id="V-1",
        platform_sku="P-SKU-1",
        source_old_sku_code="OLD-SKU",
        title="Mapping detail",
    )
    return {
        "tenant": tenant,
        "other_tenant": other_tenant,
        "user": user,
        "platform": platform,
        "other_platform": other_platform,
        "store": store,
        "other_store": other_store,
        "other_tenant_store": other_tenant_store,
        "store_mapping": store_mapping,
        "detail": detail,
        "sku_old": sku_old,
        "sku_new": sku_new,
    }


def _grant(user, *codes):
    role = Role.objects.create(
        tenant=user.tenant,
        code=f"mapping-{user.username}-{Role.objects.filter(tenant=user.tenant).count() + 1}",
        name="Mapping consolidation role",
    )
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "integrations", "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.ALL, config={})


def _grant_custom_scope(user, scope_config, *codes):
    role = Role.objects.create(
        tenant=user.tenant,
        code=f"mapping-scope-{user.username}-{Role.objects.filter(tenant=user.tenant).count() + 1}",
        name="Mapping custom scope role",
    )
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": code.split(".", 1)[0], "action": code.rsplit(".", 1)[-1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=DataScope.ScopeType.CUSTOM,
        config=scope_config,
    )


def test_platform_detail_link_rejects_cross_tenant_and_cross_store_identity():
    context = _fixture()
    with pytest.raises(ValidationError):
        create_product_mapping(
            tenant=context["tenant"],
            actor=context["user"],
            store_mapping=context["store_mapping"],
            platform_detail=PlatformProductDetail.objects.create(
                tenant=context["tenant"],
                platform=context["other_platform"],
                store=context["other_store"],
                platform_variant_id="V-OTHER",
            ),
        )
    foreign_detail = PlatformProductDetail.objects.create(
        tenant=context["other_tenant"],
        platform=PlatformMaster.objects.get(tenant=context["other_tenant"], code="shopee"),
        store=context["other_tenant_store"],
        platform_variant_id="V-FOREIGN",
    )
    with pytest.raises(ValidationError):
        create_product_mapping(
            tenant=context["tenant"],
            actor=context["user"],
            store_mapping=context["store_mapping"],
            platform_detail=foreign_detail,
        )


def test_confirm_atomically_writes_canonical_detail_and_audits_before_after():
    context = _fixture()
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_detail=context["detail"],
    )
    suggested = suggest_product_mapping(mapping, actor=context["user"], sku=context["sku_old"], confidence=93)
    confirmed = confirm_product_mapping(suggested, actor=context["user"], manually_confirmed=True)
    context["detail"].refresh_from_db()
    assert confirmed.status == "mapped"
    assert context["detail"].internal_sku_id == context["sku_old"].id
    audit = IntegrationAuditLog.objects.filter(action="product_mapping_confirm").latest("id")
    assert audit.masked_detail["before_internal_sku_id"] is None
    assert audit.masked_detail["after_internal_sku_id"] == context["sku_old"].id


def test_conflict_requires_expected_sku_and_explicit_replace_then_updates_detail():
    context = _fixture()
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_detail=context["detail"],
    )
    mapped = confirm_product_mapping(
        suggest_product_mapping(mapping, actor=context["user"], sku=context["sku_old"], confidence=90),
        actor=context["user"],
        manually_confirmed=True,
    )
    conflict = suggest_product_mapping(mapped, actor=context["user"], sku=context["sku_new"], confidence=45)
    assert conflict.status == "conflict"
    with pytest.raises(Exception):
        confirm_product_mapping(
            conflict,
            actor=context["user"],
            sku=context["sku_new"],
            manually_confirmed=True,
            expected_internal_sku_id=context["sku_new"].id,
            replace_existing=True,
        )
    context["detail"].refresh_from_db()
    assert context["detail"].internal_sku_id == context["sku_old"].id
    replaced = confirm_product_mapping(
        conflict,
        actor=context["user"],
        sku=context["sku_new"],
        manually_confirmed=True,
        expected_internal_sku_id=context["sku_old"].id,
        replace_existing=True,
    )
    context["detail"].refresh_from_db()
    assert replaced.status == "mapped"
    assert context["detail"].internal_sku_id == context["sku_new"].id


def test_suggestions_cannot_reopen_conflict_or_inactive_records():
    context = _fixture()
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_detail=context["detail"],
    )
    context["detail"].internal_sku = context["sku_old"]
    context["detail"].save(update_fields=["internal_sku", "updated_at"])
    conflict = suggest_product_mapping(mapping, actor=context["user"], sku=context["sku_new"], confidence=50)
    assert conflict.status == "conflict"
    with pytest.raises(Exception):
        suggest_product_mapping(conflict, actor=context["user"], sku=context["sku_old"], confidence=50)

    from apps.integrations.product_mapping_service import deactivate_product_mapping

    inactive_mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_product_id="P-INACTIVE",
        platform_variant_id="V-INACTIVE",
        platform_sku="S-INACTIVE",
    )
    inactive_mapping = deactivate_product_mapping(inactive_mapping, actor=context["user"])
    with pytest.raises(Exception):
        suggest_product_mapping(inactive_mapping, actor=context["user"], sku=context["sku_old"], confidence=50)


def test_confirm_permission_boundary_and_strict_boolean_payloads():
    context = _fixture()
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_detail=context["detail"],
    )
    suggest_product_mapping(mapping, actor=context["user"], sku=context["sku_old"], confidence=90)
    _grant(context["user"], "integrations.product_mapping.confirm")
    client = APIClient()
    client.force_authenticate(context["user"])
    confirmed = client.patch(
        f"/api/internal/integrations/product-mappings/{mapping.pk}/",
        {"manually_confirmed": True},
        format="json",
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["data"]["status"] == "mapped"

    manage_user = CustomUser.objects.create_user(
        username="mapping-manage-only",
        password="test-password",
        tenant=context["tenant"],
        user_type=CustomUser.UserType.INTERNAL,
    )
    _grant(manage_user, "integrations.product_mapping.manage")
    client.force_authenticate(manage_user)
    for raw_value in ("true", 1):
        response = client.patch(
            f"/api/internal/integrations/product-mappings/{mapping.pk}/",
            {"manually_confirmed": raw_value},
            format="json",
        )
        assert response.status_code == 400

    assert not ProductMappingUpdateSerializer(data={"manually_confirmed": "true"}).is_valid()
    assert not ProductMappingUpdateSerializer(
        data={"status": "inactive", "manually_confirmed": True}
    ).is_valid()


def test_old_mapping_fields_remain_compatible_without_platform_detail():
    context = _fixture()
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_product_id="P-LEGACY",
        platform_variant_id="V-LEGACY",
        platform_sku="LEGACY-PLATFORM-SKU",
    )
    assert mapping.platform_detail_id is None


def test_product_detail_scope_covers_get_patch_and_import_without_cross_store_access():
    context = _fixture()
    outside_detail = PlatformProductDetail.objects.create(
        tenant=context["tenant"],
        platform=context["other_platform"],
        store=context["other_store"],
        platform_variant_id="V-OUTSIDE",
        platform_product_id="P-OUTSIDE",
    )
    outside_scoped_store = StoreMaster.objects.create(
        tenant=context["tenant"],
        platform=context["platform"],
        code="store-my-2",
        name="Store MY 2",
        country_code="MY",
        currency="MYR",
    )
    outside_mapping_scope_detail = PlatformProductDetail.objects.create(
        tenant=context["tenant"],
        platform=context["platform"],
        store=outside_scoped_store,
        platform_variant_id="V-OUTSIDE-SCOPE",
        platform_product_id="P-OUTSIDE-SCOPE",
    )
    _grant_custom_scope(
        context["user"],
        {
            "platforms": ["shopee"],
            "store_ids": [context["store"].id, outside_scoped_store.id],
        },
        "listings.product_detail.view",
        "listings.product_detail.manage",
        "listings.product_detail.import",
    )
    _grant_custom_scope(
        context["user"],
        {"platforms": ["shopee"], "store_ids": [context["store"].id]},
        "integrations.product_mapping.view",
    )
    client = APIClient()
    client.force_authenticate(context["user"])
    listed = client.get("/api/internal/listings/product-details/")
    assert listed.status_code == 200
    listed_ids = {row["id"] for row in listed.json()["data"]["results"]}
    assert context["detail"].id in listed_ids
    assert outside_detail.id not in listed_ids
    assert outside_mapping_scope_detail.id in listed_ids

    status_listed = client.get(
        "/api/internal/listings/product-details/",
        {"mapping_status": "unmapped"},
    )
    assert status_listed.status_code == 200
    status_ids = {row["id"] for row in status_listed.json()["data"]["results"]}
    assert context["detail"].id in status_ids
    assert outside_mapping_scope_detail.id not in status_ids

    own_patch = client.patch(
        f"/api/internal/listings/product-details/{context['detail'].id}/",
        {"title": "范围内编辑"},
        format="json",
    )
    assert own_patch.status_code == 200
    outside_patch = client.patch(
        f"/api/internal/listings/product-details/{outside_detail.id}/",
        {"title": "越权编辑"},
        format="json",
    )
    assert outside_patch.status_code == 404

    upload = SimpleUploadedFile(
        "outside-scope.csv",
        "platform,store_code,platform_product_id,platform_variant_id\n"
        "tiktok,store-th,P-NEW,V-NEW\n".encode("utf-8"),
        content_type="text/csv",
    )
    imported = client.post(
        "/api/internal/listings/product-details/import/",
        {"file": upload},
        format="multipart",
    )
    assert imported.status_code == 200
    assert imported.json()["data"]["errors"]
    assert "范围内" in imported.json()["data"]["errors"][0]["message"]

    ids_upload = SimpleUploadedFile(
        "outside-scope-ids.csv",
        "变体ID,平台商品ID\nV-OUTSIDE,P-REJECTED\n".encode("utf-8"),
        content_type="text/csv",
    )
    ids_imported = client.post(
        "/api/internal/listings/product-details/import-platform-product-ids/",
        {"file": ids_upload},
        format="multipart",
    )
    assert ids_imported.status_code == 200
    assert ids_imported.json()["data"]["unmatched"] == 1
    outside_detail.refresh_from_db()
    assert outside_detail.platform_product_id == "P-OUTSIDE"


def test_product_only_options_keep_visible_inactive_history_and_do_not_guess_active_target():
    context = _fixture()
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_detail=context["detail"],
    )
    update_store_mapping(
        context["store_mapping"],
        actor=context["user"],
        status=MarketplaceStoreMapping.Status.INACTIVE,
    )
    _grant(context["user"], "integrations.product_mapping.view")
    client = APIClient()
    client.force_authenticate(context["user"])
    response = client.get("/api/internal/integrations/product-mappings/options/", {"mapping_status": "unmapped"})
    assert response.status_code == 200
    rows = response.json()["data"]["platform_details"]
    row = next(item for item in rows if item["id"] == context["detail"].id)
    assert row["mapping"]["id"] == mapping.id
    assert row["store_mapping_id"] is None


def test_direct_patch_bulk_and_import_cannot_bypass_controlled_mapping():
    context = _fixture()
    mapping = create_product_mapping(
        tenant=context["tenant"],
        actor=context["user"],
        store_mapping=context["store_mapping"],
        platform_detail=context["detail"],
    )
    context["detail"].internal_sku = context["sku_old"]
    context["detail"].save(update_fields=["internal_sku", "updated_at"])
    context["detail"].refresh_from_db()
    _grant(context["user"], "listings.product_detail.manage", "listings.product_detail.view")
    client = APIClient()
    client.force_authenticate(context["user"])
    patched = client.patch(
        f"/api/internal/listings/product-details/{context['detail'].id}/",
        {"internal_sku": context["sku_new"].id},
        format="json",
    )
    assert patched.status_code == 400
    context["detail"].refresh_from_db()
    assert context["detail"].internal_sku_id == context["sku_old"].id

    unchanged_prefill = client.patch(
        f"/api/internal/listings/product-details/{context['detail'].id}/",
        {
            "platform_product_id": context["detail"].platform_product_id,
            "platform_variant_id": context["detail"].platform_variant_id,
            "platform_sku": context["detail"].platform_sku,
            "source_old_sku_code": context["detail"].source_old_sku_code,
            "internal_sku": context["sku_old"].id,
            "title": "标题正常编辑",
        },
        format="json",
    )
    assert unchanged_prefill.status_code == 200
    context["detail"].refresh_from_db()
    assert context["detail"].title == "标题正常编辑"

    bulk = client.post(
        "/api/internal/listings/product-details/bulk-update/",
        {
            "match_type": "new_spu",
            "spu_code": context["sku_old"].spu.spu_code,
            "fields": {"internal_sku": context["sku_new"].id},
        },
        format="json",
    )
    assert bulk.status_code == 200
    assert bulk.json()["data"]["error_count"] == 1
    context["detail"].refresh_from_db()
    assert context["detail"].internal_sku_id == context["sku_old"].id

    from apps.listings.platform_product_details import import_platform_product_details

    result = import_platform_product_details(
        tenant=context["tenant"],
        raw=(
            "platform,store_code,platform_product_id,platform_variant_id,source_old_sku_code\n"
            "shopee,store-my,P-1,V-1,OLD-NEW\n"
        ).encode(),
        filename="mapping.csv",
    )
    assert result["errors"] and result["errors"][0]["code"] == "controlled_mapping_edit"
    context["detail"].refresh_from_db()
    assert context["detail"].internal_sku_id == context["sku_old"].id

    from apps.listings.platform_product_details import import_platform_product_ids

    replay = import_platform_product_ids(
        tenant=context["tenant"],
        raw="变体ID,平台商品ID\nV-1,P-1\n".encode("utf-8-sig"),
        filename="mapping-ids.csv",
    )
    assert replay["unchanged"] == 1
    assert replay["errors"] == []
