import importlib
from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.db.migrations.exceptions import IrreversibleError
from django.db.models import BooleanField, Value
from django.db.models.query import QuerySet
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers.models import (
    AffiliateOrderSnapshot,
    AffiliateOrderRevision,
    BdOrderAttributionSnapshot,
    BdSampleAttributionSnapshot,
    Influencer,
    InfluencerRestriction,
    FulfillmentStatusEvent,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
    StoreProductListing,
    VideoResult,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant
from apps.influencers.services import (
    _payload_hash,
    _purchase_cost_for_item,
    _purchase_cost_for_payload,
    create_outreach_task,
    create_sample_fulfillment,
    mark_overdue_sample_fulfillments,
    refresh_sample_fulfillment_video_status,
    restore_sample_fulfillment,
    add_outreach_target,
    soft_delete_sample_fulfillment,
    outreach_task_progress,
    soft_delete_outreach_target,
    transition_outreach_task,
    transition_sample_fulfillment,
    update_sample_fulfillment,
    update_outreach_target,
)
from apps.influencers.attribution import (
    affiliate_order_source_row_key,
    build_bd_performance,
    influencer_account,
    parse_decimal,
    refresh_order_attributions,
    rule_version_for,
)


pytestmark = pytest.mark.django_db

FULFILLMENT_FORBIDDEN_RESPONSE_FIELDS = {
    "sales_amount",
    "pricing_status",
    "priced_at",
    "unit_price",
    "unit_cost",
    "currency",
    "price_match_status",
    "price_source",
    "price_snapshot_at",
}


def assert_cost_only_fulfillment_payload(payload):
    def visit(value):
        if isinstance(value, dict):
            assert FULFILLMENT_FORBIDDEN_RESPONSE_FIELDS.isdisjoint(value)
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    assert "calculated_cost" in payload
    for item in payload.get("items", []):
        assert "cost_amount" in item
        assert "cost_match_status" in item


def test_purchase_cost_matches_new_and_legacy_sku_without_crossing_tenants():
    tenant = Tenant.objects.create(name="Cost Tenant", code="cost-tenant")
    other_tenant = Tenant.objects.create(name="Other Cost Tenant", code="other-cost-tenant")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="COST-SPU", product_name="Cost Product")
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="101010004-blue-120X200CM",
        legacy_sku_code="DFYL003-B-B",
        purchase_price="27.1200",
    )
    other_spu = ProductSPU.objects.create(
        tenant=other_tenant, spu_code="OTHER-COST-SPU", product_name="Other Cost Product"
    )
    ProductSKU.objects.create(
        tenant=other_tenant,
        spu=other_spu,
        sku_code=sku.sku_code,
        legacy_sku_code=sku.legacy_sku_code,
        purchase_price="99.0000",
    )

    _, matched_new, new_status = _purchase_cost_for_item(tenant, "101010004-blue-120X200CM")
    _, matched_old, old_status = _purchase_cost_for_item(tenant, "dfyl003-b-b")

    assert matched_new == sku
    assert new_status == "matched_new_sku"
    assert matched_old == sku
    assert old_status == "matched_legacy_sku"
    assert str(matched_new.purchase_price) == "27.1200"

    normalized, selected, selected_status = _purchase_cost_for_payload(
        tenant, {"sku": sku, "requested_sku": None}
    )
    assert normalized == "101010004-BLUE-120X200CM"
    assert selected == sku
    assert selected_status == "matched_new_sku"

    with pytest.raises(DRFValidationError):
        _purchase_cost_for_payload(tenant, {"sku": sku, "requested_sku": "DIFFERENT-SKU"})

    sku.is_active = False
    sku.save(update_fields=["is_active"])
    with pytest.raises(DRFValidationError):
        _purchase_cost_for_payload(tenant, {"sku": sku, "requested_sku": sku.sku_code})


def user_with_permissions(tenant, username, *codes, scope=DataScope.ScopeType.ALL):
    user = CustomUser.objects.create_user(username=username, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)
    role = Role.objects.create(tenant=tenant, code=f"role-{username}", name=username)
    for code in codes:
        permission, _ = Permission.objects.get_or_create(
            code=code,
            defaults={"name": code, "module": "influencers", "action": code.split(".", 1)[1]},
        )
        role.permissions.add(permission)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    DataScope.objects.create(tenant=tenant, role=role, scope_type=scope, config={})
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def store_for(tenant, code):
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"platform-{code}",
        name="TikTok Shop",
        platform_type=PlatformMaster.PlatformType.TIKTOK,
    )
    return StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=code,
        name=code,
        country_code="PH",
        currency="PHP",
    )


def make_bd_owner(tenant, user):
    user.user_type = CustomUser.UserType.INTERNAL
    user.is_active = True
    user.save(update_fields=["user_type", "is_active"])
    role, _ = Role.objects.get_or_create(
        tenant=tenant,
        code="bd",
        defaults={"name": "BD", "status": Role.Status.ACTIVE},
    )
    if role.status != Role.Status.ACTIVE:
        role.status = Role.Status.ACTIVE
        role.save(update_fields=["status", "updated_at"])
    UserRole.objects.get_or_create(tenant=tenant, user=user, role=role)
    return user


def test_outreach_options_return_active_stores_and_bd_users_only():
    tenant = Tenant.objects.create(name="Options Tenant", code="options-tenant")
    _, client = user_with_permissions(
        tenant,
        "options-manager",
        "influencers.outreach.view",
        "influencers.outreach.manage",
    )
    store = store_for(tenant, "creator-store")
    bd_role = Role.objects.create(tenant=tenant, code="bd", name="BD")
    bd_user = CustomUser.objects.create_user(
        username="liyejun",
        full_name="李烨君",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    other_user = CustomUser.objects.create_user(
        username="not-bd",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    UserRole.objects.create(tenant=tenant, user=bd_user, role=bd_role)
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="creator-active",
        name="Active Creator",
        platform="tiktok",
        handle="active.creator",
    )
    Influencer.objects.create(
        tenant=tenant,
        code="creator-inactive",
        name="Inactive Creator",
        platform="tiktok",
        status=Influencer.Status.INACTIVE,
    )
    other_tenant = Tenant.objects.create(name="Other Options Tenant", code="other-options-tenant")
    Influencer.objects.create(
        tenant=other_tenant,
        code="creator-other",
        name="Other Creator",
        platform="tiktok",
    )

    response = client.get("/api/internal/influencers/outreach-task-options/")

    assert response.status_code == 200
    assert response.data["data"]["stores"] == [{
        "id": store.id,
        "name": store.name,
        "code": store.code,
        "country_code": "PH",
        "platform_name": "TikTok Shop",
    }]
    assert response.data["data"]["bd_users"] == [{
        "id": bd_user.id,
        "username": "liyejun",
        "full_name": "李烨君",
    }]
    assert other_user.id not in {item["id"] for item in response.data["data"]["bd_users"]}
    assert response.data["data"]["influencers"] == [{
        "id": influencer.id,
        "code": "creator-active",
        "name": "Active Creator",
        "display_name": "Active Creator",
        "handle": "active.creator",
        "platform": "tiktok",
        "status": "active",
        "is_blacklisted": False,
    }]

    invalid_priority = client.post("/api/internal/influencers/outreach-tasks/", {
        "task_no": "OPTIONS-BAD-PRIORITY",
        "task_name": "Reject invalid priority",
        "store": store.id,
        "owner": bd_user.id,
        "priority": "immediate",
        "target_count": 1,
    }, format="json")
    assert invalid_priority.status_code == 400

    rejected_owner = client.post("/api/internal/influencers/outreach-tasks/", {
        "task_no": "OPTIONS-NON-BD",
        "task_name": "Reject non-BD owner",
        "store": store.id,
        "owner": other_user.id,
        "target_count": 1,
    }, format="json")
    assert rejected_owner.status_code == 400

    store.status = "inactive"
    store.save(update_fields=["status"])
    rejected_store = client.post("/api/internal/influencers/outreach-tasks/", {
        "task_no": "OPTIONS-INACTIVE-STORE",
        "task_name": "Reject inactive store",
        "store": store.id,
        "owner": bd_user.id,
        "target_count": 1,
    }, format="json")
    assert rejected_store.status_code == 400


def test_outreach_product_match_groups_listings_by_store_and_returns_sku_prefixes():
    tenant = Tenant.objects.create(name="Product Match Tenant", code="product-match-tenant")
    _, client = user_with_permissions(tenant, "product-match-manager", "influencers.outreach.view")
    store = store_for(tenant, "matched-store")
    for site_code, parent_sku, external_sku in (("PH", "HY107", "HY107-RED"), ("PH-ALT", "", "HY107-BLUE")):
        listing = StoreProductListing.objects.create(
            tenant=tenant,
            store=store,
            external_product_id="1733134199243507606",
            parent_sku=parent_sku,
            product_name="Matched Product",
            site_code=site_code,
            source="test",
        )
        SkuPriceSnapshot.objects.create(
            tenant=tenant,
            listing=listing,
            external_sku=external_sku,
            currency="PHP",
            source="test",
        )

    response = client.get(
        "/api/internal/influencers/outreach-product-match/",
        {"product_id": "1733134199243507606"},
    )

    assert response.status_code == 200
    assert response.data["data"]["unique"] is True
    assert response.data["data"]["candidates"] == [{
        "store_id": store.id,
        "store_name": store.name,
        "store_code": store.code,
        "country_code": "PH",
        "product_name": "Matched Product",
        "sku_prefixes": ["HY107"],
    }]


def test_outreach_product_match_does_not_cross_tenants_or_auto_select_multiple_stores():
    tenant = Tenant.objects.create(name="Match Boundary Tenant", code="match-boundary-tenant")
    other_tenant = Tenant.objects.create(name="Other Match Tenant", code="other-match-tenant")
    _, client = user_with_permissions(tenant, "match-boundary-manager", "influencers.outreach.view")
    product_id = "1733134199243507606"
    for store in (store_for(tenant, "first-store"), store_for(tenant, "second-store")):
        StoreProductListing.objects.create(
            tenant=tenant,
            store=store,
            external_product_id=product_id,
            parent_sku=f"PREFIX-{store.code}",
            product_name="Tenant Product",
            site_code="PH",
            source="test",
        )
    other_store = store_for(other_tenant, "other-store")
    StoreProductListing.objects.create(
        tenant=other_tenant,
        store=other_store,
        external_product_id=product_id,
        parent_sku="OTHER",
        product_name="Other Tenant Product",
        site_code="PH",
        source="test",
    )

    response = client.get("/api/internal/influencers/outreach-product-match/", {"product_id": product_id})

    assert response.status_code == 200
    assert response.data["data"]["unique"] is False
    assert {candidate["store_id"] for candidate in response.data["data"]["candidates"]} == {
        store.id for store in StoreMaster.objects.filter(tenant=tenant)
    }
    assert other_store.id not in {
        candidate["store_id"] for candidate in response.data["data"]["candidates"]
    }


def base_records(tenant, user, suffix="a"):
    make_bd_owner(tenant, user)
    store = store_for(tenant, f"store-{suffix}")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code=f"creator-{suffix}",
        name=f"Creator {suffix}",
        platform="tiktok",
    )
    task = create_outreach_task(
        user=user,
        validated_data={
            "task_no": f"TASK-{suffix}",
            "influencer": influencer,
            "store": store,
            "owner": user,
        },
    )
    add_outreach_target(user=user, task=task, influencer=influencer)
    task.refresh_from_db()
    return store, influencer, task


def test_sample_pricing_data_migration_backfills_historical_values():
    tenant = Tenant.objects.create(name="Backfill Tenant", code="backfill-tenant")
    user = CustomUser.objects.create_user(username="backfill-user", tenant=tenant)
    _, _, task = base_records(tenant, user, "backfill")
    target = OutreachTarget.objects.get(task=task, is_deleted=False)
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="backfill-request",
        validated_data={
            "fulfillment_no": "BACKFILL-SAMPLE",
            "outreach_task": task,
            "outreach_target": target,
        },
        item_payloads=[{"site_code": "PH", "requested_sku": "HISTORICAL-SKU", "quantity": 2}],
    )
    QuerySet.update(
        SampleItem.objects.filter(fulfillment=fulfillment),
        unit_price="10.0000",
        unit_cost="4.0000",
        sales_amount=None,
        cost_amount=None,
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        sku_quantity=0,
        sales_amount=None,
        calculated_cost=None,
        pricing_status="pending",
    )

    migration = importlib.import_module("apps.influencers.migrations.0006_backfill_sample_pricing")
    migration.backfill_sample_pricing(django_apps, None)

    fulfillment.refresh_from_db()
    item = SampleItem.objects.get(fulfillment=fulfillment)
    assert fulfillment.sku_quantity == 2
    assert fulfillment.sales_amount == 20
    assert fulfillment.calculated_cost == 8
    assert fulfillment.pricing_status == "full"
    assert item.sales_amount == 20
    assert item.cost_amount == 8


def test_outreach_external_id_allows_multiple_nulls_but_rejects_duplicates():
    tenant = Tenant.objects.create(name="Tenant", code="outreach-external-id")
    user = CustomUser.objects.create_user(username="external-id-user", tenant=tenant)
    make_bd_owner(tenant, user)
    store = store_for(tenant, "external-id-store")
    influencer = Influencer.objects.create(tenant=tenant, code="external-id-creator", name="Creator", platform="tiktok")

    for number in (1, 2):
        create_outreach_task(
            user=user,
            validated_data={
                "task_no": f"NULL-EXT-{number}",
                "influencer": influencer,
                "store": store,
                "owner": user,
                "source": "manual",
                "external_id": None,
            },
        )

    create_outreach_task(
        user=user,
        validated_data={
            "task_no": "EXT-1",
            "influencer": influencer,
            "store": store,
            "owner": user,
            "source": "feishu",
            "external_id": "record-1",
        },
    )
    with pytest.raises(DRFValidationError):
        create_outreach_task(
            user=user,
            validated_data={
                "task_no": "EXT-2",
                "influencer": influencer,
                "store": store,
                "owner": user,
                "source": "feishu",
                "external_id": "record-1",
            },
        )


def test_outreach_rejects_cross_tenant_relations():
    tenant_a = Tenant.objects.create(name="A", code="influencer-a")
    tenant_b = Tenant.objects.create(name="B", code="influencer-b")
    user, client = user_with_permissions(tenant_a, "manager-a", "influencers.outreach.manage")
    foreign_store = store_for(tenant_b, "foreign-store")
    foreign_influencer = Influencer.objects.create(tenant=tenant_b, code="foreign", name="Foreign", platform="tiktok")

    response = client.post(
        "/api/internal/influencers/outreach-tasks/",
        {
            "task_no": "CROSS-1",
            "influencer": foreign_influencer.pk,
            "store": foreign_store.pk,
            "owner": user.pk,
        },
        format="json",
    )

    assert response.status_code == 400
    assert OutreachTask.objects.filter(task_no="CROSS-1").exists() is False


def test_non_all_scope_is_denied_even_with_permission():
    tenant = Tenant.objects.create(name="Tenant", code="influencer-own-scope")
    _, client = user_with_permissions(
        tenant,
        "own-scope-user",
        "influencers.outreach.view",
        scope=DataScope.ScopeType.OWN,
    )

    assert client.get("/api/internal/influencers/outreach-tasks/").status_code == 403


def test_sample_creation_is_idempotent_and_price_miss_does_not_block():
    tenant = Tenant.objects.create(name="Tenant", code="sample-idempotent")
    user, client = user_with_permissions(tenant, "sample-manager", "influencers.fulfillment.manage")
    store, influencer, task = base_records(tenant, user, "idem")
    influencer.handle = "active.creator"
    influencer.save(update_fields=["handle"])
    payload = {
        "fulfillment_no": "SAMPLE-1",
        "outreach_task": task.pk,
        "influencer": influencer.pk,
        "store": store.pk,
        "owner": user.pk,
        "items": [{"site_code": "PH", "requested_sku": "UNKNOWN-SKU", "external_product_id": "P-1", "quantity": 1}],
    }

    first = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="sample-key-1",
    )
    second = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="sample-key-1",
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.data["data"]["id"] == second.data["data"]["id"]
    assert first.data["data"]["influencer_handle"] == "active.creator"
    assert_cost_only_fulfillment_payload(first.data["data"])
    assert_cost_only_fulfillment_payload(second.data["data"])
    assert SampleFulfillment.objects.count() == 1

    view_permission, _ = Permission.objects.get_or_create(
        code="influencers.fulfillment.view",
        defaults={"name": "influencers.fulfillment.view", "module": "influencers", "action": "view"},
    )
    user.user_roles.filter(role__permissions__code="influencers.fulfillment.manage").first().role.permissions.add(view_permission)
    fulfillment_id = first.data["data"]["id"]
    listed = client.get("/api/internal/influencers/sample-fulfillments/")
    detailed = client.get(f"/api/internal/influencers/sample-fulfillments/{fulfillment_id}/")
    assert listed.status_code == 200
    assert detailed.status_code == 200
    assert listed.data["data"]["results"][0]["influencer_handle"] == "active.creator"
    assert detailed.data["data"]["influencer_handle"] == "active.creator"
    assert_cost_only_fulfillment_payload(listed.data["data"]["results"][0])
    assert_cost_only_fulfillment_payload(detailed.data["data"])

    conflicting_payload = {**payload, "fulfillment_no": "SAMPLE-OTHER"}
    conflict = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        conflicting_payload,
        format="json",
        HTTP_IDEMPOTENCY_KEY="sample-key-1",
    )
    assert conflict.status_code == 409
    assert SampleFulfillment.objects.count() == 1


def test_workflow_models_require_audited_state_machine_writes_and_stale_versions_are_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="state-machine-guard")
    user, client = user_with_permissions(
        tenant,
        "state-machine-user",
        "influencers.outreach.manage",
        "influencers.fulfillment.manage",
    )
    store, influencer, task = base_records(tenant, user, "guard")

    with pytest.raises(DjangoValidationError):
        OutreachTask.objects.create(
            tenant=tenant,
            task_no="ILLEGAL-TERMINAL-CREATE",
            influencer=influencer,
            store=store,
            dispatcher=user,
            owner=user,
            status=OutreachTask.Status.COMPLETED,
        )

    task.status = OutreachTask.Status.IN_PROGRESS
    with pytest.raises(DjangoValidationError):
        task.save()
    task.refresh_from_db()
    task.status = OutreachTask.Status.IN_PROGRESS
    with pytest.raises(DjangoValidationError):
        task.save(update_fields=["status"])
    with pytest.raises(DjangoValidationError):
        task.save_base()
    task.refresh_from_db()

    response = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "GUARD-SAMPLE",
            "outreach_task": task.pk,
            "influencer": influencer.pk,
            "store": store.pk,
            "owner": user.pk,
            "items": [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="guard-sample-key",
    )
    assert response.status_code == 201
    fulfillment = SampleFulfillment.objects.get(pk=response.data["data"]["id"])
    fulfillment.status = SampleFulfillment.Status.SHIPPED
    with pytest.raises(DjangoValidationError):
        fulfillment.save()
    fulfillment.refresh_from_db()
    fulfillment.status = SampleFulfillment.Status.SHIPPED
    with pytest.raises(DjangoValidationError):
        fulfillment.save(update_fields=["status"])
    fulfillment.refresh_from_db()

    first_view = OutreachTask.objects.get(pk=task.pk)
    stale_view = OutreachTask.objects.get(pk=task.pk)
    transition_outreach_task(
        user=user,
        task=first_view,
        status=OutreachTask.Status.IN_PROGRESS,
        expected_version=1,
    )
    with pytest.raises(DRFValidationError) as stale_error:
        transition_outreach_task(
            user=user,
            task=stale_view,
            status=OutreachTask.Status.CANCELLED,
            expected_version=1,
        )
    assert stale_error.value.get_codes() == {"version": "conflict"}

    transition_sample_fulfillment(
        user=user,
        fulfillment=fulfillment,
        status=SampleFulfillment.Status.SHIPPED,
        expected_version=1,
    )
    assert fulfillment.status_events.filter(to_status=SampleFulfillment.Status.SHIPPED).exists()
    assert OperationLog.objects.filter(tenant=tenant, action="outreach_status", object_id=str(task.pk)).exists()
    assert OperationLog.objects.filter(tenant=tenant, action="sample_status", object_id=str(fulfillment.pk)).exists()


def test_fulfillment_requires_matching_task_store_and_influencer_under_model_and_service_checks():
    tenant = Tenant.objects.create(name="Tenant", code="task-relation-check")
    user, client = user_with_permissions(tenant, "task-relation-user", "influencers.fulfillment.manage")
    store_a, influencer_a, task_a = base_records(tenant, user, "relation-a")
    store_b, influencer_b, _ = base_records(tenant, user, "relation-b")

    mismatched_influencer = SampleFulfillment(
        tenant=tenant,
        fulfillment_no="MODEL-BAD-INFLUENCER",
        request_key="model-bad-influencer",
        request_hash="hash",
        outreach_task=task_a,
        influencer=influencer_b,
        store=store_a,
        owner=user,
    )
    with pytest.raises(DjangoValidationError):
        mismatched_influencer.full_clean()

    mismatched_store = SampleFulfillment(
        tenant=tenant,
        fulfillment_no="MODEL-BAD-STORE",
        request_key="model-bad-store",
        request_hash="hash",
        outreach_task=task_a,
        influencer=influencer_a,
        store=store_b,
        owner=user,
    )
    with pytest.raises(DjangoValidationError):
        mismatched_store.full_clean()

    response = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "SERVICE-BAD-STORE",
            "outreach_task": task_a.pk,
            "influencer": influencer_a.pk,
            "store": store_b.pk,
            "owner": user.pk,
            "items": [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="service-bad-store",
    )
    assert response.status_code == 400
    assert not SampleFulfillment.objects.filter(fulfillment_no="SERVICE-BAD-STORE").exists()


def test_idempotency_hash_uses_relation_primary_keys_and_scalar_values():
    tenant = Tenant.objects.create(name="Tenant", code="canonical-hash")
    user = CustomUser.objects.create_user(username="canonical-hash-user", tenant=tenant)
    influencer = Influencer.objects.create(tenant=tenant, code="canonical-creator", name="Creator", platform="tiktok")

    assert _payload_hash({"influencer": influencer, "owner": user, "items": [{"quantity": 1}]}) == _payload_hash(
        {"influencer": influencer.pk, "owner": user.pk, "items": [{"quantity": 1}]}
    )


def test_fulfillment_number_race_is_reported_as_a_domain_conflict(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="fulfillment-number-race")
    user = CustomUser.objects.create_user(username="fulfillment-race-user", tenant=tenant)
    store, influencer, task = base_records(tenant, user, "fulfillment-race")
    existing, _ = create_sample_fulfillment(
        user=user,
        request_key="winner-key",
        validated_data={
            "fulfillment_no": "RACE-FULFILLMENT",
            "outreach_task": task,
            "influencer": influencer,
            "store": store,
            "owner": user,
        },
        item_payloads=[],
    )
    assert existing.fulfillment_no == "RACE-FULFILLMENT"

    import apps.influencers.services as influencer_services

    monkeypatch.setattr(influencer_services, "_save", lambda instance: (_ for _ in ()).throw(IntegrityError("race")))
    with pytest.raises(DRFValidationError) as error:
        create_sample_fulfillment(
            user=user,
            request_key="loser-key",
            validated_data={
                "fulfillment_no": "RACE-FULFILLMENT",
                "outreach_task": task,
                "influencer": influencer,
                "store": store,
                "owner": user,
            },
            item_payloads=[],
        )
    assert error.value.get_codes() == {"fulfillment_no": "conflict"}


def test_fulfillment_number_domain_conflict_maps_to_http_409(monkeypatch):
    tenant = Tenant.objects.create(name="Tenant", code="fulfillment-number-http-conflict")
    user, client = user_with_permissions(tenant, "fulfillment-http-user", "influencers.fulfillment.manage")
    store, influencer, task = base_records(tenant, user, "fulfillment-http")

    import apps.influencers.views as influencer_views

    def raise_number_conflict(**kwargs):
        raise DRFValidationError({"fulfillment_no": "Fulfillment number already exists."}, code="conflict")

    monkeypatch.setattr(influencer_views, "create_sample_fulfillment", raise_number_conflict)
    response = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "HTTP-CONFLICT",
            "outreach_task": task.pk,
            "influencer": influencer.pk,
            "store": store.pk,
            "owner": user.pk,
            "items": [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="http-conflict-key",
    )
    assert response.status_code == 409


def test_requested_sku_nullable_migration_is_explicitly_irreversible():
    migration = importlib.import_module(
        "apps.influencers.migrations.0003_sampleitem_requested_sku_nullable"
    )
    with pytest.raises(IrreversibleError, match="forward fix or restore a backup"):
        migration.block_reverse(None, None)


def test_sample_status_baseline_migration_is_reversible_and_keeps_event_values_compatible():
    tenant = Tenant.objects.create(name="Status migration tenant", code="status-migration")
    user, _ = user_with_permissions(tenant, "status-migration-user")
    store, influencer, task = base_records(tenant, user, "status-migration")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="status-migration-key",
        validated_data={
            "fulfillment_no": "STATUS-MIGRATION-SAMPLE",
            "outreach_task": task,
            "influencer": influencer,
            "store": store,
            "owner": user,
        },
        item_payloads=[],
    )
    InfluencerRestriction.objects.create(
        tenant=tenant,
        influencer=influencer,
        is_blacklisted=True,
        created_by=user,
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        status="creating",
    )
    legacy_event = FulfillmentStatusEvent.objects.create(
        tenant=tenant,
        fulfillment=fulfillment,
        from_status="creating",
        to_status="processing",
        actor=user,
        reason="legacy status",
    )
    migration = importlib.import_module(
        "apps.influencers.migrations.0012_sample_fulfillment_status_baseline"
    )

    migration.migrate_status_baseline(django_apps, None)

    fulfillment.refresh_from_db()
    legacy_event.refresh_from_db()
    assert fulfillment.status == SampleFulfillment.Status.BLACKLISTED
    assert legacy_event.from_status == SampleFulfillment.Status.BLACKLISTED
    assert legacy_event.to_status == SampleFulfillment.Status.BLACKLISTED

    migration.restore_status_baseline(django_apps, None)

    fulfillment.refresh_from_db()
    legacy_event.refresh_from_db()
    assert fulfillment.status == SampleFulfillment.Status.CANCELLED
    assert legacy_event.from_status == SampleFulfillment.Status.CANCELLED
    assert legacy_event.to_status == SampleFulfillment.Status.CANCELLED


def test_blacklisted_influencer_cannot_receive_sample():
    tenant = Tenant.objects.create(name="Tenant", code="sample-blacklist")
    user, client = user_with_permissions(tenant, "blacklist-manager", "influencers.fulfillment.manage")
    store, influencer, task = base_records(tenant, user, "blacklist")
    InfluencerRestriction.objects.create(
        tenant=tenant,
        influencer=influencer,
        is_blacklisted=True,
        reason="risk",
        created_by=user,
    )

    response = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "SAMPLE-BLOCKED",
            "outreach_task": task.pk,
            "influencer": influencer.pk,
            "store": store.pk,
            "owner": user.pk,
            "items": [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="sample-blacklisted",
    )

    assert response.status_code == 400
    assert SampleFulfillment.objects.filter(fulfillment_no="SAMPLE-BLOCKED").exists() is False


def test_sample_price_match_is_internal_and_fulfillment_contract_is_cost_only():
    tenant = Tenant.objects.create(name="Tenant", code="sample-site-price")
    user, client = user_with_permissions(tenant, "site-price-manager", "influencers.fulfillment.manage")
    store, influencer, task = base_records(tenant, user, "site-price")
    for site, price in (("PH", "10.0000"), ("TH", "20.0000")):
        listing = StoreProductListing.objects.create(
            tenant=tenant,
            store=store,
            external_product_id=f"ITEM-{site}",
            product_name=f"Product {site}",
            site_code=site,
            source="db-daren",
        )
        SkuPriceSnapshot.objects.create(
            tenant=tenant,
            listing=listing,
            external_sku="SAME-SKU",
            effective_price=price,
            currency="PHP" if site == "PH" else "THB",
            source="db-daren",
        )

    response = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "SAMPLE-SITE",
            "outreach_task": task.pk,
            "influencer": influencer.pk,
            "store": store.pk,
            "owner": user.pk,
            "items": [{"site_code": "PH", "requested_sku": "SAME-SKU", "quantity": 1}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="sample-site-key",
    )

    assert response.status_code == 201
    assert_cost_only_fulfillment_payload(response.data["data"])
    item = SampleItem.objects.get(fulfillment__fulfillment_no="SAMPLE-SITE")
    assert item.unit_price == Decimal("10.0000")
    assert item.currency == "PHP"


def test_requested_sku_empty_values_are_stored_as_null_and_non_empty_values_remain_unique():
    tenant = Tenant.objects.create(name="Tenant", code="requested-sku-null")
    user, client = user_with_permissions(tenant, "requested-sku-user", "influencers.fulfillment.manage")
    store, influencer, task = base_records(tenant, user, "requested-sku")

    response = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "SAMPLE-NULL-SKU",
            "outreach_task": task.pk,
            "influencer": influencer.pk,
            "store": store.pk,
            "owner": user.pk,
            "items": [
                {"site_code": "PH", "requested_sku": "", "quantity": 1},
                {"site_code": "PH", "requested_sku": "   ", "quantity": 1},
            ],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="requested-sku-null-key",
    )
    assert response.status_code == 201
    fulfillment = SampleFulfillment.objects.get(fulfillment_no="SAMPLE-NULL-SKU")
    assert list(SampleItem.objects.filter(fulfillment=fulfillment).values_list("requested_sku", flat=True)) == [None, None]
    assert response.data["data"]["items"][0]["requested_sku"] is None

    duplicate = SampleItem(
        tenant=tenant,
        fulfillment=fulfillment,
        site_code="PH",
        requested_sku="NONEMPTY-SKU",
        quantity=1,
    )
    duplicate.save()
    with pytest.raises(IntegrityError), transaction.atomic():
        SampleItem(
            tenant=tenant,
            fulfillment=fulfillment,
            site_code="PH",
            requested_sku="NONEMPTY-SKU",
            quantity=1,
        ).save_base(force_insert=True)


def test_price_lookup_requires_tenant_store_site_and_returns_real_nulls():
    tenant = Tenant.objects.create(name="Tenant", code="price-lookup")
    other = Tenant.objects.create(name="Other", code="price-other")
    _, client = user_with_permissions(tenant, "catalog-viewer", "influencers.catalog.view")
    store = store_for(tenant, "price-store")
    other_store = store_for(other, "other-store")
    listing = StoreProductListing.objects.create(
        tenant=tenant,
        store=store,
        external_product_id="ITEM-1",
        parent_sku="PARENT",
        product_name="Product",
        site_code="PH",
        source="db-daren",
    )
    other_listing = StoreProductListing.objects.create(
        tenant=other,
        store=other_store,
        external_product_id="ITEM-1",
        product_name="Hidden",
        site_code="PH",
        source="db-daren",
    )
    SkuPriceSnapshot.objects.create(
        tenant=tenant,
        listing=listing,
        external_sku="SKU-1",
        original_price="10.0000",
        promotion_price=None,
        effective_price="10.0000",
        inbound_cost=None,
        currency="PHP",
        source="db-daren",
    )
    SkuPriceSnapshot.objects.create(
        tenant=other,
        listing=other_listing,
        external_sku="SKU-1",
        original_price="99.0000",
        effective_price="99.0000",
        currency="PHP",
        source="db-daren",
    )

    matched = client.get(
        "/api/internal/influencers/product-price-lookup/",
        {"store_id": store.pk, "site_code": "PH", "sku": "SKU-1"},
    )
    missing = client.get(
        "/api/internal/influencers/product-price-lookup/",
        {"store_id": store.pk, "site_code": "PH", "sku": "NOT-IMPORTED"},
    )

    assert matched.status_code == 200
    assert matched.data["data"]["matched"] is True
    assert len(matched.data["data"]["results"]) == 1
    assert matched.data["data"]["results"][0]["promotion_price"] is None
    for field in ("inbound_cost", "stock", "cost_updated_at"):
        assert field not in matched.data["data"]["results"][0]
    assert missing.data["data"] == {"matched": False, "reason": "data_source_not_imported", "results": []}


def test_illegal_status_transition_and_stale_version_are_rejected():
    tenant = Tenant.objects.create(name="Tenant", code="status-machine")
    user, client = user_with_permissions(
        tenant,
        "status-manager",
        "influencers.outreach.manage",
        "influencers.fulfillment.manage",
    )
    store, influencer, task = base_records(tenant, user, "status")

    illegal = client.post(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/status/",
        {"status": "completed"},
        format="json",
        HTTP_IF_MATCH="1",
    )
    started = client.post(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/status/",
        {"status": "in_progress"},
        format="json",
        HTTP_IF_MATCH="1",
    )
    stale = client.post(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/status/",
        {"status": "cancelled"},
        format="json",
        HTTP_IF_MATCH="1",
    )

    assert illegal.status_code == 400
    assert started.status_code == 200
    assert stale.status_code == 409


def test_outreach_task_detail_patch_is_allowlisted_versioned_and_soft_deleted():
    tenant = Tenant.objects.create(name="Task Edit Tenant", code="task-edit-tenant")
    other_tenant = Tenant.objects.create(name="Other Task Edit Tenant", code="other-task-edit-tenant")
    user, client = user_with_permissions(
        tenant,
        "task-edit-manager",
        "influencers.outreach.view",
        "influencers.outreach.manage",
    )
    store, _, task = base_records(tenant, user, "task-edit")
    replacement_store = store_for(tenant, "replacement-store")
    foreign_store = store_for(other_tenant, "foreign-store")
    original_times = {
        "dispatch_time": task.dispatch_time,
        "outreach_at": task.outreach_at,
        "started_at": task.started_at,
        "finalized_at": task.finalized_at,
    }

    updated = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        {
            "task_name": "Edited task",
            "priority": "high",
            "store": replacement_store.id,
            "external_product_id": "EDITED-PRODUCT",
            "sku_prefix": "EDITED-SKU",
            "target_count": 2,
            "owner": user.id,
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )

    assert updated.status_code == 200
    task.refresh_from_db()
    assert task.task_name == "Edited task"
    assert task.priority == "high"
    assert task.store_id == replacement_store.id
    assert task.external_product_id == "EDITED-PRODUCT"
    assert task.sku_prefix == "EDITED-SKU"
    assert task.target_count == 2
    assert task.owner_id == user.id
    assert task.version == 2
    for field, value in original_times.items():
        assert getattr(task, field) == value

    stale = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        {"task_name": "Stale edit"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert stale.status_code == 409
    task.refresh_from_db()
    assert task.task_name == "Edited task"

    state_override = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        {"status": "completed", "started_at": "2026-08-11T00:00:00Z"},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    assert state_override.status_code == 400

    foreign_relation = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        {"store": foreign_store.id},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    assert foreign_relation.status_code == 400

    _, view_only_client = user_with_permissions(
        tenant,
        "task-edit-viewer",
        "influencers.outreach.view",
    )
    forbidden = view_only_client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        {"task_name": "Forbidden edit"},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    assert forbidden.status_code == 403

    foreign_user = CustomUser.objects.create_user(username="foreign-delete-user", tenant=other_tenant)
    _, _, foreign_task = base_records(other_tenant, foreign_user, "foreign-delete")
    foreign_delete = client.delete(
        f"/api/internal/influencers/outreach-tasks/{foreign_task.pk}/",
        HTTP_IF_MATCH='"1"',
    )
    assert foreign_delete.status_code == 404

    missing_version = client.delete(f"/api/internal/influencers/outreach-tasks/{task.pk}/")
    assert missing_version.status_code == 400
    task.refresh_from_db()
    assert task.is_deleted is False
    assert task.version == 2

    stale_delete = client.delete(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        HTTP_IF_MATCH='"1"',
    )
    assert stale_delete.status_code == 409

    deleted = client.delete(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        HTTP_IF_MATCH='"2"',
    )
    assert deleted.status_code == 200
    task.refresh_from_db()
    assert task.is_deleted is True
    assert task.version == 3
    assert client.get(f"/api/internal/influencers/outreach-tasks/{task.pk}/").status_code == 404


@pytest.mark.parametrize("terminal_status", [OutreachTask.Status.COMPLETED, OutreachTask.Status.CANCELLED])
def test_terminal_outreach_tasks_reject_business_and_attribution_updates(terminal_status):
    tenant = Tenant.objects.create(name="Terminal Edit Tenant", code=f"terminal-edit-{terminal_status}")
    user, client = user_with_permissions(
        tenant,
        f"terminal-edit-{terminal_status}",
        "influencers.outreach.manage",
    )
    store, influencer, task = base_records(tenant, user, f"terminal-edit-{terminal_status}")
    if terminal_status == OutreachTask.Status.COMPLETED:
        task.target_count = 1
        task.save()
        target = OutreachTarget.objects.get(task=task, influencer=influencer)
        completed = client.patch(
            f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/{target.pk}/",
            {"outreach_result": OutreachTarget.OutreachResult.SUCCESS},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert completed.status_code == 200
    else:
        cancelled = client.post(
            f"/api/internal/influencers/outreach-tasks/{task.pk}/status/",
            {"status": terminal_status},
            format="json",
            HTTP_IF_MATCH='"1"',
        )
        assert cancelled.status_code == 200

    task.refresh_from_db()
    before = {
        "task_name": task.task_name,
        "priority": task.priority,
        "store_id": task.store_id,
        "owner_id": task.owner_id,
        "target_count": task.target_count,
        "external_product_id": task.external_product_id,
    }
    update = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/",
        {
            "task_name": "terminal-edit-must-fail",
            "priority": "urgent",
            "store": store.pk,
            "owner": user.pk,
            "target_count": task.target_count + 1,
            "external_product_id": "TERMINAL-EDIT-MUST-FAIL",
        },
        format="json",
        HTTP_IF_MATCH=f'"{task.version}"',
    )

    assert update.status_code == 409
    task.refresh_from_db()
    assert {
        "task_name": task.task_name,
        "priority": task.priority,
        "store_id": task.store_id,
        "owner_id": task.owner_id,
        "target_count": task.target_count,
        "external_product_id": task.external_product_id,
    } == before


def test_bulk_tenant_owned_writes_are_disabled():
    tenant = Tenant.objects.create(name="Tenant", code="bulk-guard")
    user, _ = user_with_permissions(tenant, "bulk-user", "influencers.outreach.manage")
    store, influencer, task = base_records(tenant, user, "bulk")

    with pytest.raises(DjangoValidationError):
        OutreachTask.objects.filter(pk=task.pk).update(status=OutreachTask.Status.COMPLETED)
    with pytest.raises(DjangoValidationError):
        OutreachTask.objects.bulk_create([
            OutreachTask(
                tenant=tenant,
                task_no="BULK-2",
                influencer=influencer,
                store=store,
                dispatcher=user,
                owner=user,
            )
        ])
    with pytest.raises(DjangoValidationError):
        Influencer.objects.filter(pk=influencer.pk).update(status=Influencer.Status.INACTIVE)


def test_0025_grants_new_permissions_to_manager_and_administrator_roles():
    tenant = Tenant.objects.create(name="Tenant", code="permission-upgrade")
    manager = Role.objects.create(tenant=tenant, code="002", name="Influencer manager")
    administrator = Role.objects.create(tenant=tenant, code="administrator", name="Administrator")
    migration = importlib.import_module("apps.permissions.migrations.0025_expand_influencer_permissions")

    migration.seed(django_apps, None)

    expected = {code for code, *_ in migration.PERMISSIONS}
    assert expected <= set(manager.permissions.values_list("code", flat=True))
    assert expected <= set(administrator.permissions.values_list("code", flat=True))


def test_influencer_private_fields_are_hidden_handle_is_searchable_and_status_is_versioned():
    tenant = Tenant.objects.create(name="Tenant", code="sensitive-profile")
    _, client = user_with_permissions(
        tenant,
        "profile-manager",
        "influencers.view",
        "influencers.manage",
    )
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="safe-code",
        name="Safe display name",
        platform="tiktok",
        handle="secret.handle",
        contact_name="Private Name",
        contact_phone="13800138000",
        contact_email="private@example.test",
        notes="private note",
    )

    listed = client.get("/api/internal/influencers/")
    searched = client.get("/api/internal/influencers/", {"search": "secret.handle"})
    item = listed.data["data"]["results"][0]
    assert item["display_name"] == "Safe display name"
    assert item["handle"] == "secret.handle"
    for field in ("contact_name", "contact_phone", "contact_email", "notes"):
        assert field not in item
    assert searched.data["data"]["count"] == 1

    version = influencer.updated_at.isoformat()
    first = client.post(
        f"/api/internal/influencers/{influencer.pk}/status/",
        {"status": "inactive"},
        format="json",
        HTTP_IF_MATCH=version,
    )
    stale = client.post(
        f"/api/internal/influencers/{influencer.pk}/status/",
        {"status": "active"},
        format="json",
        HTTP_IF_MATCH=version,
    )
    assert first.status_code == 200
    assert stale.status_code == 409


def test_outreach_task_supports_multiple_targets_linked_count_and_soft_delete():
    tenant = Tenant.objects.create(name="Tenant", code="a2-multiple-targets")
    user, client = user_with_permissions(
        tenant,
        "a2-target-manager",
        "influencers.outreach.view",
        "influencers.outreach.manage",
    )
    store, influencer, task = base_records(tenant, user, "a2-targets")
    second = Influencer.objects.create(
        tenant=tenant,
        code="creator-a2-second",
        name="Creator second",
        platform="tiktok",
    )
    task.target_count = 2
    task.save()

    linked = client.post(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/",
        {"influencer": second.pk},
        format="json",
    )
    listed = client.get(f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/")

    assert linked.status_code == 201
    assert listed.status_code == 200
    assert listed.data["data"]["count"] == 2
    assert client.get(f"/api/internal/influencers/outreach-tasks/{task.pk}/").data["data"]["linked_count"] == 2

    first_target = OutreachTarget.objects.get(task=task, influencer=influencer)
    deleted = client.delete(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/{first_target.pk}/",
        HTTP_IF_MATCH='"1"',
    )
    hidden = client.get(f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/")
    restored = client.post(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/",
        {"influencer": influencer.pk},
        format="json",
        HTTP_IF_MATCH='"2"',
    )

    assert deleted.status_code == 200
    assert hidden.data["data"]["count"] == 1
    assert restored.status_code == 200
    assert OutreachTarget.objects.filter(pk=first_target.pk, is_deleted=False).exists()


def test_single_target_terminal_result_auto_completes_task_once():
    tenant = Tenant.objects.create(name="Tenant", code="a2-auto-complete")
    user, client = user_with_permissions(
        tenant,
        "a2-auto-complete-user",
        "influencers.outreach.view",
        "influencers.outreach.manage",
    )
    _, influencer, task = base_records(tenant, user, "a2-auto")
    task.target_count = 1
    task.save()
    target = OutreachTarget.objects.get(task=task, influencer=influencer)

    first = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/{target.pk}/",
        {"outreach_result": "success"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    task.refresh_from_db()
    finalized_at = task.finalized_at
    second = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/{target.pk}/",
        {"notes": "terminal target"},
        format="json",
        HTTP_IF_MATCH='"2"',
    )
    task.refresh_from_db()

    assert first.status_code == 200
    assert second.status_code == 409
    assert task.status == OutreachTask.Status.COMPLETED
    assert task.finalized_at == finalized_at


def test_zero_target_count_does_not_auto_complete_outreach_task():
    tenant = Tenant.objects.create(name="Tenant", code="a2-zero-target")
    user, client = user_with_permissions(
        tenant,
        "a2-zero-target-user",
        "influencers.outreach.view",
        "influencers.outreach.manage",
    )
    _, influencer, task = base_records(tenant, user, "a2-zero-target")
    task.target_count = 0
    task.save(update_fields=["target_count"])
    target = OutreachTarget.objects.get(task=task, influencer=influencer)

    response = client.patch(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/{target.pk}/",
        {"outreach_result": "success"},
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    task.refresh_from_db()

    assert response.status_code == 200
    assert task.status != OutreachTask.Status.COMPLETED
    assert task.finalized_at is None


def test_blacklisted_influencer_cannot_be_added_to_outreach_task():
    tenant = Tenant.objects.create(name="Tenant", code="target-blacklist")
    user, client = user_with_permissions(
        tenant,
        "target-blacklist-manager",
        "influencers.outreach.manage",
    )
    _, _, task = base_records(tenant, user, "target-blacklist")
    blocked = Influencer.objects.create(
        tenant=tenant,
        code="blocked-target",
        name="Blocked target",
        platform="tiktok",
    )
    InfluencerRestriction.objects.create(
        tenant=tenant,
        influencer=blocked,
        is_blacklisted=True,
        reason="risk",
        created_by=user,
    )

    response = client.post(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/",
        {"influencer": blocked.pk},
        format="json",
    )

    assert response.status_code == 409
    assert not OutreachTarget.objects.filter(task=task, influencer=blocked).exists()


def test_inactive_influencer_cannot_be_added_or_receive_a_sample():
    tenant = Tenant.objects.create(name="Inactive Influencer Tenant", code="inactive-influencer")
    user, client = user_with_permissions(
        tenant,
        "inactive-influencer-manager",
        "influencers.outreach.manage",
        "influencers.fulfillment.manage",
    )
    store, influencer, task = base_records(tenant, user, "inactive-influencer")
    inactive = Influencer.objects.create(
        tenant=tenant,
        code="inactive-target",
        name="Inactive target",
        platform="tiktok",
        status=Influencer.Status.INACTIVE,
    )

    create_task = client.post(
        "/api/internal/influencers/outreach-tasks/",
        {
            "task_no": "INACTIVE-CREATE-TASK",
            "task_name": "Reject inactive creator during task creation",
            "influencer": inactive.pk,
            "store": store.pk,
            "owner": user.pk,
            "target_count": 1,
        },
        format="json",
    )
    assert create_task.status_code == 409
    assert not OutreachTask.objects.filter(task_no="INACTIVE-CREATE-TASK").exists()

    add_target = client.post(
        f"/api/internal/influencers/outreach-tasks/{task.pk}/targets/",
        {"influencer": inactive.pk},
        format="json",
    )
    assert add_target.status_code == 409
    assert not OutreachTarget.objects.filter(task=task, influencer=inactive).exists()

    target = OutreachTarget.objects.get(task=task, influencer=influencer)
    influencer.status = Influencer.Status.INACTIVE
    influencer.save(update_fields=["status", "updated_at"])
    sample = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "INACTIVE-SAMPLE",
            "outreach_task": task.pk,
            "outreach_target": target.pk,
            "items": [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="inactive-sample-key",
    )

    assert sample.status_code == 409
    assert not SampleFulfillment.objects.filter(fulfillment_no="INACTIVE-SAMPLE").exists()


def test_sample_order_number_marks_new_fulfillment_as_shipped():
    tenant = Tenant.objects.create(name="Tenant", code="sample-order-shipped")
    user, client = user_with_permissions(
        tenant,
        "sample-order-manager",
        "influencers.fulfillment.manage",
    )
    store, influencer, task = base_records(tenant, user, "sample-order")
    target = OutreachTarget.objects.get(task=task, influencer=influencer)

    response = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "SAMPLE-SHIPPED",
            "outreach_task": task.pk,
            "outreach_target": target.pk,
            "sample_order_no": "ORDER-001",
            "items": [],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="sample-shipped-on-create",
    )

    assert response.status_code == 201
    fulfillment = SampleFulfillment.objects.get(fulfillment_no="SAMPLE-SHIPPED")
    assert fulfillment.store_id == store.pk
    assert fulfillment.status == SampleFulfillment.Status.SHIPPED
    assert fulfillment.shipped_at is not None


def test_sample_list_outreach_task_filter_is_exact_and_tenant_scoped():
    tenant = Tenant.objects.create(name="Sample filter tenant", code="sample-filter")
    user, client = user_with_permissions(
        tenant,
        "sample-filter-user",
        "influencers.fulfillment.view",
    )
    first_store, first_influencer, first_task = base_records(tenant, user, "filter-first")
    second_store, second_influencer, second_task = base_records(tenant, user, "filter-second")
    first_sample, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-filter-first-key",
        validated_data={
            "fulfillment_no": "SAMPLE-FILTER-FIRST",
            "outreach_task": first_task,
            "influencer": first_influencer,
            "store": first_store,
            "owner": user,
        },
        item_payloads=[],
    )
    second_sample, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-filter-second-key",
        validated_data={
            "fulfillment_no": "SAMPLE-FILTER-SECOND",
            "outreach_task": second_task,
            "influencer": second_influencer,
            "store": second_store,
            "owner": user,
        },
        item_payloads=[],
    )
    other_tenant = Tenant.objects.create(name="Other sample filter tenant", code="sample-filter-other")
    other_user, _ = user_with_permissions(other_tenant, "sample-filter-other-user")
    other_store, other_influencer, other_task = base_records(other_tenant, other_user, "filter-other")
    other_sample, _ = create_sample_fulfillment(
        user=other_user,
        request_key="sample-filter-other-key",
        validated_data={
            "fulfillment_no": "SAMPLE-FILTER-OTHER",
            "outreach_task": other_task,
            "influencer": other_influencer,
            "store": other_store,
            "owner": other_user,
        },
        item_payloads=[],
    )

    response = client.get(
        "/api/internal/influencers/sample-fulfillments/",
        {"outreach_task": first_task.pk, "page": 1, "page_size": 100},
    )

    assert response.status_code == 200
    result_ids = {row["id"] for row in response.data["data"]["results"]}
    assert result_ids == {first_sample.id}
    assert second_sample.id not in result_ids
    assert other_sample.id not in result_ids
    assert client.get(
        "/api/internal/influencers/sample-fulfillments/",
        {"outreach_task": other_task.pk},
    ).data["data"]["count"] == 0
    assert client.get(
        "/api/internal/influencers/sample-fulfillments/",
        {"outreach_task": "not-an-id"},
    ).status_code == 400


def _new_affiliate_order(
    tenant,
    *,
    data_time,
    product_id="P-1",
    fully_returned="否",
    order_status="completed",
    order_id=None,
):
    order_id = order_id or f"ORDER-{data_time.timestamp()}"
    order = AffiliateOrderSnapshot(
        tenant=tenant,
        source="affiliate_orders_report",
        source_row_key=affiliate_order_source_row_key(
            data_time=data_time,
            shop_abbr="store-affiliate",
            site="PH",
            order_id=order_id,
            sku_id="SKU-1",
        ),
        row_hash="a" * 64,
        data_time=data_time,
        shop_abbr="store-affiliate",
        site="PH",
        order_id=order_id,
        product_id=product_id,
        sku_id="SKU-1",
        payment_amount=Decimal("1000"),
        currency="PHP",
        quantity=2,
        fully_returned=fully_returned,
        order_status=order_status,
        creator_username="creator.account",
        creator_username_normalized="creator.account",
        actual_paid_commission=Decimal("0"),
        estimated_paid_commission=Decimal("10"),
    )
    order.save()
    return order


def test_affiliate_order_constraints_are_tenant_scoped_and_csv_replay_is_idempotent(tmp_path, monkeypatch):
    tenant = Tenant.objects.create(name="Affiliate tenant", code="affiliate-constraints")
    other_tenant = Tenant.objects.create(name="Other affiliate tenant", code="affiliate-other")
    when = timezone.now() - timedelta(days=2)
    order = _new_affiliate_order(tenant, data_time=when)
    duplicate = AffiliateOrderSnapshot.objects.get(pk=order.pk)
    duplicate.pk = None
    duplicate._state.adding = True
    with pytest.raises((IntegrityError, DjangoValidationError)):
        duplicate.save(force_insert=True)
    foreign = _new_affiliate_order(other_tenant, data_time=when)
    assert AffiliateOrderSnapshot.objects.filter(tenant=tenant, pk=foreign.pk).exists() is False

    csv_path = tmp_path / "affiliate.csv"
    header = "data_time,shop_abbr,site,order_id,product_id,sku_id,creator_username,payment_amount,quantity,currency,fully_returned,order_status,actual_paid_commission,estimated_paid_commission,export_time\n"
    row = "2026-08-16,store-affiliate,PH,CSV-1,P-1,SKU-1,creator.account,100,1,PHP,否,completed,0,10,2026-08-17T10:00:00+00:00\n"
    csv_path.write_text(header + row, encoding="utf-8")
    first_output, second_output = StringIO(), StringIO()
    call_command(
        "import_affiliate_orders_csv",
        tenant_id=tenant.pk,
        file=str(csv_path),
        source="affiliate_orders_report",
        stdout=first_output,
    )
    call_command(
        "import_affiliate_orders_csv",
        tenant_id=tenant.pk,
        file=str(csv_path),
        source="affiliate_orders_report",
        stdout=second_output,
    )
    assert "created=1" in first_output.getvalue()
    assert "noop=1" in second_output.getvalue()
    assert "CSV-1" not in first_output.getvalue()
    assert AffiliateOrderRevision.objects.filter(tenant=tenant).count() == 0

    csv_path.write_text(
        header + row.replace(",100,", ",120,").replace("10:00:00", "11:00:00"),
        encoding="utf-8",
    )
    call_command(
        "import_affiliate_orders_csv",
        tenant_id=tenant.pk,
        file=str(csv_path),
        source="affiliate_orders_report",
        stdout=StringIO(),
    )
    assert AffiliateOrderRevision.objects.filter(tenant=tenant).count() == 1

    imported = AffiliateOrderSnapshot.objects.get(tenant=tenant, order_id="CSV-1")
    original_full_clean = AffiliateOrderSnapshot.full_clean

    def reject_import_update(instance, *args, **kwargs):
        if instance.pk == imported.pk:
            raise DjangoValidationError("forced validation failure")
        return original_full_clean(instance, *args, **kwargs)

    monkeypatch.setattr(AffiliateOrderSnapshot, "full_clean", reject_import_update)
    csv_path.write_text(
        header + row.replace(",100,", ",140,").replace("10:00:00", "12:00:00"),
        encoding="utf-8",
    )
    with pytest.raises(CommandError, match="Affiliate import failed"):
        call_command(
            "import_affiliate_orders_csv",
            tenant_id=tenant.pk,
            file=str(csv_path),
            source="affiliate_orders_report",
            stdout=StringIO(),
        )
    imported.refresh_from_db()
    assert imported.payment_amount == Decimal("120")
    assert AffiliateOrderRevision.objects.filter(tenant=tenant).count() == 1


def test_affiliate_csv_rejects_stale_rows_and_counts_same_timestamp_conflicts(tmp_path):
    tenant = Tenant.objects.create(name="Affiliate freshness tenant", code="affiliate-freshness")
    csv_path = tmp_path / "affiliate-freshness.csv"
    header = "data_time,shop_abbr,site,order_id,product_id,sku_id,creator_username,payment_amount,quantity,currency,fully_returned,order_status,actual_paid_commission,estimated_paid_commission,export_time\n"
    initial = "2026-08-16,store-affiliate,PH,CSV-FRESH-1,P-1,SKU-1,creator.account,100,1,PHP,否,completed,0,10,2026-08-17T10:00:00+00:00\n"
    csv_path.write_text(header + initial, encoding="utf-8")
    call_command(
        "import_affiliate_orders_csv",
        tenant_id=tenant.pk,
        file=str(csv_path),
        source="affiliate_orders_report",
        stdout=StringIO(),
    )

    stale = initial.replace(",100,", ",120,").replace("10:00:00", "09:00:00")
    stale_output = StringIO()
    csv_path.write_text(header + stale, encoding="utf-8")
    call_command(
        "import_affiliate_orders_csv",
        tenant_id=tenant.pk,
        file=str(csv_path),
        source="affiliate_orders_report",
        stdout=stale_output,
    )
    assert "updated=0" in stale_output.getvalue()
    assert "conflict=0" in stale_output.getvalue()
    assert "rejected=1" in stale_output.getvalue()
    assert AffiliateOrderSnapshot.objects.get(tenant=tenant).payment_amount == Decimal("100")

    conflict = initial.replace(",100,", ",130,")
    conflict_output = StringIO()
    csv_path.write_text(header + conflict, encoding="utf-8")
    call_command(
        "import_affiliate_orders_csv",
        tenant_id=tenant.pk,
        file=str(csv_path),
        source="affiliate_orders_report",
        stdout=conflict_output,
    )
    assert "conflict=1" in conflict_output.getvalue()
    assert "rejected=1" in conflict_output.getvalue()
    assert AffiliateOrderRevision.objects.filter(tenant=tenant).count() == 0


def test_affiliate_decimal_limits_and_currency_allowlist_are_exact():
    assert parse_decimal("1234567890123456.1234", field="amount") == Decimal("1234567890123456.1234")
    with pytest.raises(ValueError, match="too_many_digits"):
        parse_decimal("12345678901234567.1234", field="amount")
    with pytest.raises(ValueError, match="too_many_decimal_places"):
        parse_decimal("1.12345", field="amount")

    tenant = Tenant.objects.create(name="Currency validation tenant", code="currency-validation")
    order = _new_affiliate_order(tenant, data_time=timezone.now() - timedelta(days=1))
    order.currency = "EUR"
    with pytest.raises(DjangoValidationError):
        order.full_clean()


def test_bd_attribution_requires_product_in_strict_mode_and_uses_latest_sample_in_fallback():
    tenant = Tenant.objects.create(name="Attribution tenant", code="attribution-rules")
    user, _ = user_with_permissions(tenant, "attribution-owner")
    make_bd_owner(tenant, user)
    store = store_for(tenant, "store-affiliate")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="creator.account",
        name="Creator",
        platform="tiktok",
        handle="creator.account",
    )
    task = create_outreach_task(
        user=user,
        validated_data={
            "task_no": "ATTRIBUTION-TASK",
            "influencer": influencer,
            "store": store,
            "owner": user,
            "external_product_id": "P-1",
        },
    )
    target, _ = add_outreach_target(user=user, task=task, influencer=influencer)
    old_fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="attribution-old",
        validated_data={"fulfillment_no": "ATTRIBUTION-OLD", "outreach_task": task, "outreach_target": target},
        item_payloads=[],
    )
    new_fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="attribution-new",
        validated_data={"fulfillment_no": "ATTRIBUTION-NEW", "outreach_task": task, "outreach_target": target},
        item_payloads=[],
    )
    old_sample = BdSampleAttributionSnapshot.objects.get(fulfillment=old_fulfillment)
    new_sample = BdSampleAttributionSnapshot.objects.get(fulfillment=new_fulfillment)
    old_sample.sampled_at = timezone.now() - timedelta(days=4)
    old_sample.product_id = "P-1"
    old_sample.save()
    new_sample.sampled_at = timezone.now() - timedelta(days=2)
    new_sample.product_id = "P-1"
    new_sample.save()

    other_product = _new_affiliate_order(
        tenant,
        data_time=timezone.now() - timedelta(days=1),
        product_id="P-2",
    )
    assert refresh_order_attributions(tenant=tenant, attribution="strict")["created"] == 0
    fallback = refresh_order_attributions(tenant=tenant, attribution="fallback")
    assert fallback["created"] == 1
    attribution = BdOrderAttributionSnapshot.objects.get(order_snapshot=other_product, rule="fallback")
    assert attribution.sample_attribution_id == new_sample.pk

    refunded = _new_affiliate_order(
        tenant,
        data_time=timezone.now() - timedelta(days=1),
        product_id="P-1",
        fully_returned="是",
        order_id="ORDER-REFUNDED",
    )
    cancelled = _new_affiliate_order(
        tenant,
        data_time=timezone.now() - timedelta(days=1),
        product_id="P-1",
        order_status="cancelled",
        order_id="ORDER-CANCELLED",
    )
    refresh_order_attributions(tenant=tenant, attribution="strict")
    assert not BdOrderAttributionSnapshot.objects.filter(order_snapshot__in=[refunded, cancelled]).exists()


def test_standalone_sample_is_attributed_to_its_owner_and_deduplicates_order_sku():
    tenant = Tenant.objects.create(name="Standalone attribution tenant", code="standalone-attribution")
    user = CustomUser.objects.create_user(username="standalone-owner", tenant=tenant)
    make_bd_owner(tenant, user)
    store = store_for(tenant, "store-affiliate")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="creator.account",
        name="Creator",
        platform="tiktok",
        handle="creator.account",
    )
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="standalone-attribution",
        validated_data={
            "fulfillment_no": "STANDALONE-1",
            "link_type": "YYJL",
            "influencer": influencer,
            "store": store,
            "owner": user,
            "external_product_id": "P-1",
            "product_name_snapshot": "Product",
        },
        item_payloads=[],
    )
    order_time = timezone.now() - timedelta(days=1)
    sample = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    sample.sampled_at = order_time - timedelta(hours=1)
    sample.shop_abbr = "store-affiliate"
    sample.product_id = "P-1"
    sample.save()
    order = _new_affiliate_order(tenant, data_time=order_time)
    duplicate = _new_affiliate_order(tenant, data_time=order_time + timedelta(minutes=1))
    duplicate.order_id = order.order_id
    duplicate.source_row_key = affiliate_order_source_row_key(
        data_time=duplicate.data_time,
        shop_abbr=duplicate.shop_abbr,
        site=duplicate.site,
        order_id=duplicate.order_id,
        sku_id=duplicate.sku_id,
    )
    duplicate.save()

    result = refresh_order_attributions(tenant=tenant, attribution="strict")

    assert result["created"] == 1
    attribution = BdOrderAttributionSnapshot.objects.get(tenant=tenant)
    assert attribution.owner_id == user.pk
    assert attribution.order_id == order.order_id
    assert attribution.sku_id == order.sku_id


def test_sample_attribution_uses_only_the_normalized_tiktok_handle():
    tenant = Tenant.objects.create(name="Canonical handle tenant", code="canonical-handle-attribution")
    user = CustomUser.objects.create_user(username="canonical-handle-owner", tenant=tenant)
    make_bd_owner(tenant, user)
    store = store_for(tenant, "canonical-handle")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="canonical-handle-creator",
        name="Shedeserve ✨",
        platform="tiktok",
        handle=" @CANONICAL.CREATOR ",
    )

    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="canonical-handle-sample",
        validated_data={
            "fulfillment_no": "CANONICAL-HANDLE-SAMPLE",
            "link_type": "YYJL",
            "influencer": influencer,
            "store": store,
            "owner": user,
            "external_product_id": "P-CANONICAL-HANDLE",
        },
        item_payloads=[],
    )

    snapshot = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    assert snapshot.creator_username == "canonical.creator"
    name_only = Influencer(
        tenant=tenant,
        code="name-only-attribution",
        name="canonical.creator",
        platform="tiktok",
        handle="",
    )
    assert influencer_account(name_only) == ""


def test_bd_performance_requires_both_permissions_and_empty_tenant_is_not_imported():
    tenant = Tenant.objects.create(name="Performance tenant", code="performance-empty")
    _, client = user_with_permissions(
        tenant,
        "performance-viewer",
        "influencers.outreach.view",
        "influencers.fulfillment.view",
    )
    response = client.get("/api/internal/influencers/bd-performance/", {"currency": "PHP"})
    assert response.status_code == 200
    assert response.data["data"]["source_status"] == "not_imported"
    assert response.data["data"]["totals"]["gmv"] == "0.0000"
    assert response.data["data"]["rates"] == {}
    assert response.data["data"]["rate_details"] == []
    assert response.data["data"]["rate_missing"] is False
    assert response.data["data"]["missing_exchange_rates"] == []

    _, denied_client = user_with_permissions(
        tenant,
        "performance-outreach-only",
        "influencers.outreach.view",
    )
    assert denied_client.get("/api/internal/influencers/bd-performance/").status_code == 403


def test_bd_performance_export_and_zero_gmv_diagnostic_are_authorized_and_safe():
    tenant = Tenant.objects.create(name="Performance export tenant", code="performance-export")
    _, client = user_with_permissions(
        tenant,
        "performance-export-viewer",
        "influencers.outreach.view",
        "influencers.fulfillment.view",
    )
    export = client.get("/api/internal/influencers/bd-performance/export/")
    assert export.status_code == 200
    assert export["Content-Type"].startswith("text/csv")
    assert export["X-Content-Type-Options"] == "nosniff"
    assert b"owner_id" in export.content
    diagnostic = client.get("/api/internal/influencers/bd-performance/diagnostics/")
    assert diagnostic.status_code == 200
    assert diagnostic.data["data"]["is_zero_gmv"] is True
    assert "orders_not_imported" in diagnostic.data["data"]["reason_codes"]


def test_sample_fulfillment_detail_edit_soft_delete_restore_and_sku_repricing_contract():
    tenant = Tenant.objects.create(name="Sample lifecycle tenant", code="sample-lifecycle")
    user, client = user_with_permissions(
        tenant,
        "sample-lifecycle-user",
        "influencers.fulfillment.view",
        "influencers.fulfillment.manage",
    )
    store, influencer, task = base_records(tenant, user, "sample-lifecycle")
    task.target_count = 2
    task.save()

    created = client.post(
        "/api/internal/influencers/sample-fulfillments/",
        {
            "fulfillment_no": "SAMPLE-LIFECYCLE",
            "outreach_task": task.pk,
            "influencer": influencer.pk,
            "store": store.pk,
            "owner": user.pk,
            "quick_tags": ["重点", "重点"],
            "items": [{"site_code": "PH", "requested_sku": "SKU-A", "quantity": 1}],
        },
        format="json",
        HTTP_IDEMPOTENCY_KEY="sample-lifecycle-key",
    )
    assert created.status_code == 201
    fulfillment_id = created.data["data"]["id"]
    assert created.data["data"]["link_type"] == "DRJL"
    assert created.data["data"]["quick_tags"] == ["重点"]
    assert created.data["data"]["video_deadline_at"] is not None

    detail = client.get(f"/api/internal/influencers/sample-fulfillments/{fulfillment_id}/")
    assert detail.status_code == 200
    assert detail.data["data"]["video_match_count"] == 0

    edited = client.patch(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment_id}/",
        {
            "sample_order_no": "ORDER-1",
            "notes": "edited",
            "link_type": "TKOne",
            "quick_tags": ["已发货"],
            "status": SampleFulfillment.Status.PENDING,
            "items": [
                {"site_code": "PH", "requested_sku": "SKU-A", "quantity": 2},
                {"site_code": "PH", "requested_sku": "SKU-B", "quantity": 1},
            ],
        },
        format="json",
        HTTP_IF_MATCH='"1"',
    )
    assert edited.status_code == 200
    assert edited.data["data"]["version"] == 2
    assert edited.data["data"]["status"] == SampleFulfillment.Status.SHIPPED
    assert FulfillmentStatusEvent.objects.filter(
        fulfillment_id=fulfillment_id,
        from_status=SampleFulfillment.Status.PENDING,
        to_status=SampleFulfillment.Status.SHIPPED,
        reason="sample_order_no_added",
    ).exists()
    assert edited.data["data"]["link_type"] == "TKOne"
    assert edited.data["data"]["sku_quantity"] == 3

    deleted = client.delete(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment_id}/",
        HTTP_IF_MATCH='"2"',
    )
    assert deleted.status_code == 200
    assert deleted.data["data"]["is_deleted"] is True
    assert client.get("/api/internal/influencers/sample-fulfillments/").data["data"]["count"] == 0
    deleted_list = client.get(
        "/api/internal/influencers/sample-fulfillments/",
        {"include_deleted": "true"},
    )
    assert deleted_list.data["data"]["count"] == 1
    deleted_only = client.get(
        "/api/internal/influencers/sample-fulfillments/",
        {"deleted_only": "true"},
    )
    assert deleted_only.status_code == 200
    assert deleted_only.data["data"]["count"] == 1
    assert all(row["is_deleted"] for row in deleted_only.data["data"]["results"])
    conflicting_deleted_filters = client.get(
        "/api/internal/influencers/sample-fulfillments/",
        {"deleted_only": "true", "include_deleted": "true"},
    )
    assert conflicting_deleted_filters.status_code == 400

    restored = client.post(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment_id}/restore/",
        HTTP_IF_MATCH='"3"',
    )
    assert restored.status_code == 200
    assert restored.data["data"]["is_deleted"] is False


def test_sample_fulfillment_public_status_choices_are_the_controlled_baseline():
    assert set(SampleFulfillment.Status.values) == {
        "pending", "shipped", "delivered", "completed", "cancelled",
        "published", "live_creator", "overdue", "blacklisted",
    }


def test_sample_timeout_video_recovery_and_task_completion_summary_are_idempotent():
    tenant = Tenant.objects.create(name="Sample automation tenant", code="sample-automation")
    user, client = user_with_permissions(
        tenant,
        "sample-automation-user",
        "influencers.outreach.view",
        "influencers.outreach.manage",
        "influencers.fulfillment.view",
        "influencers.fulfillment.manage",
    )
    store, influencer, task = base_records(tenant, user, "sample-automation")
    task.target_count = 1
    task.save()
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-automation-key",
        validated_data={
            "fulfillment_no": "SAMPLE-AUTOMATION",
            "outreach_task": task,
            "influencer": influencer,
            "store": store,
            "owner": user,
        },
        item_payloads=[],
    )
    old_deadline = timezone.now() - timedelta(days=1)
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        video_deadline_at=old_deadline,
    )
    first = mark_overdue_sample_fulfillments(actor=user, tenant=tenant, now=timezone.now())
    second = mark_overdue_sample_fulfillments(actor=user, tenant=tenant, now=timezone.now())
    fulfillment.refresh_from_db()
    assert first["marked"] == 1
    assert second["marked"] == 0
    assert fulfillment.status == SampleFulfillment.Status.OVERDUE
    assert fulfillment.status_events.filter(to_status=SampleFulfillment.Status.OVERDUE).count() == 1

    VideoResult.objects.create(
        tenant=tenant,
        influencer=influencer,
        outreach_task=task,
        sample_fulfillment=fulfillment,
        store=store,
        content_type=VideoResult.ContentType.VIDEO,
        platform="tiktok",
        external_content_id="video-sample-automation",
        metric_date=timezone.localdate(),
        published_at=timezone.now(),
        currency="PHP",
    )
    recovered = refresh_sample_fulfillment_video_status(user=user, fulfillment=fulfillment)
    assert recovered.status == SampleFulfillment.Status.PUBLISHED
    task.refresh_from_db()
    assert task.status == OutreachTask.Status.COMPLETED

    task_detail = client.get(f"/api/internal/influencers/outreach-tasks/{task.pk}/")
    assert task_detail.status_code == 200
    data = task_detail.data["data"]
    assert data["sample_fulfillment_count"] == 1
    assert data["sample_fulfillment_completed_count"] == 1
    assert data["sample_fulfillment_video_match_count"] == 1
    assert data["completion_validation"]["target_reached"] is True


def test_sample_timeout_rechecks_published_video_after_stale_candidate_scan(monkeypatch):
    tenant = Tenant.objects.create(name="Sample timeout race tenant", code="sample-timeout-race")
    user, _ = user_with_permissions(
        tenant,
        "sample-timeout-race-user",
        "influencers.outreach.manage",
        "influencers.fulfillment.manage",
    )
    store, influencer, task = base_records(tenant, user, "sample-timeout-race")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-timeout-race-key",
        validated_data={
            "fulfillment_no": "SAMPLE-TIMEOUT-RACE",
            "outreach_task": task,
            "influencer": influencer,
            "store": store,
            "owner": user,
        },
        item_payloads=[],
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        video_deadline_at=timezone.now() - timedelta(days=1),
    )
    VideoResult.objects.create(
        tenant=tenant,
        influencer=influencer,
        outreach_task=task,
        sample_fulfillment=fulfillment,
        store=store,
        content_type=VideoResult.ContentType.VIDEO,
        platform="tiktok",
        external_content_id="video-timeout-race",
        metric_date=timezone.localdate(),
        published_at=timezone.now(),
        currency="PHP",
    )

    # Force the first scan to look stale; the lock-time check must still win.
    monkeypatch.setattr(
        "apps.influencers.services.Exists",
        lambda _query: Value(False, output_field=BooleanField()),
    )
    result = mark_overdue_sample_fulfillments(actor=user, tenant=tenant, now=timezone.now())

    fulfillment.refresh_from_db()
    assert result == {"marked": 0, "skipped_with_video": 1}
    assert fulfillment.status == SampleFulfillment.Status.PUBLISHED
    assert not fulfillment.status_events.filter(to_status=SampleFulfillment.Status.OVERDUE).exists()


def test_refresh_deletes_invalid_current_rule_version_and_keeps_source_scoped_lines():
    tenant = Tenant.objects.create(name="Refresh deletion tenant", code="refresh-deletion")
    user, _ = user_with_permissions(tenant, "refresh-owner")
    make_bd_owner(tenant, user)
    store = store_for(tenant, "store-affiliate")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="refresh-creator",
        name="Refresh creator",
        platform="tiktok",
        handle="creator.account",
    )
    task = create_outreach_task(
        user=user,
        validated_data={
            "task_no": "REFRESH-TASK",
            "influencer": influencer,
            "store": store,
            "owner": user,
            "external_product_id": "P-1",
        },
    )
    target, _ = add_outreach_target(user=user, task=task, influencer=influencer)
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="refresh-sample",
        validated_data={"fulfillment_no": "REFRESH-SAMPLE", "outreach_task": task, "outreach_target": target},
        item_payloads=[],
    )
    first_order = _new_affiliate_order(
        tenant,
        data_time=timezone.now() - timedelta(days=1),
    )
    first_order.source = "affiliate-a"
    first_order.order_id = "SHARED-ORDER"
    first_order.save()
    second_order = _new_affiliate_order(
        tenant,
        data_time=first_order.data_time + timedelta(minutes=1),
        order_status="COMPLETED",
    )
    second_order.source = "affiliate-b"
    second_order.order_id = "SHARED-ORDER"
    second_order.save()
    sample = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    sample.sampled_at = first_order.data_time - timedelta(hours=1)
    sample.product_id = "P-1"
    sample.save()

    refreshed = refresh_order_attributions(tenant=tenant, attribution="strict")
    assert refreshed["created"] == 1
    performance = build_bd_performance(
        tenant=tenant,
        start_date=first_order.data_time.date(),
        end_date=first_order.data_time.date(),
        attribution="strict",
        currency="PHP",
    )
    assert performance["totals"]["item_quantity"] == 2
    assert performance["totals"]["valid_orders"] == 1

    first_order.fully_returned = "是"
    first_order.save(update_fields=["fully_returned"])
    second_order.fully_returned = "是"
    second_order.save(update_fields=["fully_returned"])
    invalidated = refresh_order_attributions(tenant=tenant, attribution="strict")
    assert invalidated["deleted"] == 1
    assert not BdOrderAttributionSnapshot.objects.filter(
        tenant=tenant,
        rule_version=rule_version_for("strict"),
    ).exists()


def test_bd_performance_shipped_count_reads_current_fulfillment_fields():
    tenant = Tenant.objects.create(name="Current shipment tenant", code="current-shipment")
    user, _ = user_with_permissions(tenant, "current-shipment-owner")
    make_bd_owner(tenant, user)
    store = store_for(tenant, "current-shipment-store")
    influencer = Influencer.objects.create(
        tenant=tenant,
        code="current.shipment.creator",
        name="Current shipment creator",
        platform="tiktok",
        handle="current.shipment.creator",
    )
    task = create_outreach_task(
        user=user,
        validated_data={
            "task_no": "CURRENT-SHIPMENT-TASK",
            "influencer": influencer,
            "store": store,
            "owner": user,
        },
    )
    target, _ = add_outreach_target(user=user, task=task, influencer=influencer)
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="current-shipment-sample",
        validated_data={
            "fulfillment_no": "CURRENT-SHIPMENT-SAMPLE",
            "outreach_task": task,
            "outreach_target": target,
        },
        item_payloads=[],
    )
    sample = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    sample.sample_status = SampleFulfillment.Status.SHIPPED
    sample.shipped_at = timezone.now()
    sample.save()
    report_date = timezone.localtime(sample.sampled_at).date()
    before_current_update = build_bd_performance(
        tenant=tenant,
        start_date=report_date,
        end_date=report_date,
        currency="PHP",
    )
    assert before_current_update["totals"]["shipped_count"] == 0

    fulfillment.sample_order_no = "CURRENT-SAMPLE-ORDER"
    fulfillment.save(update_fields=["sample_order_no"])
    after_current_update = build_bd_performance(
        tenant=tenant,
        start_date=report_date,
        end_date=report_date,
        currency="PHP",
    )
    assert after_current_update["totals"]["shipped_count"] == 1
