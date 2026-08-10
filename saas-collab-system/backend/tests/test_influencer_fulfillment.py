import importlib

import pytest
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.migrations.exceptions import IrreversibleError
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers.models import (
    Influencer,
    InfluencerRestriction,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    SkuPriceSnapshot,
    StoreProductListing,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant
from apps.influencers.services import (
    _payload_hash,
    create_outreach_task,
    create_sample_fulfillment,
    transition_outreach_task,
    transition_sample_fulfillment,
)


pytestmark = pytest.mark.django_db


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


def base_records(tenant, user, suffix="a"):
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
    return store, influencer, task


def test_outreach_external_id_allows_multiple_nulls_but_rejects_duplicates():
    tenant = Tenant.objects.create(name="Tenant", code="outreach-external-id")
    user = CustomUser.objects.create_user(username="external-id-user", tenant=tenant)
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
    assert first.data["data"]["items"][0]["price_match_status"] == "not_imported"
    assert SampleFulfillment.objects.count() == 1

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
    fulfillment.status = SampleFulfillment.Status.PROCESSING
    with pytest.raises(DjangoValidationError):
        fulfillment.save()
    fulfillment.refresh_from_db()
    fulfillment.status = SampleFulfillment.Status.PROCESSING
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
        status=SampleFulfillment.Status.PROCESSING,
        expected_version=1,
    )
    assert fulfillment.status_events.filter(to_status=SampleFulfillment.Status.PROCESSING).exists()
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


def test_requested_sku_nullable_migration_is_explicitly_irreversible():
    migration = importlib.import_module(
        "apps.influencers.migrations.0003_sampleitem_requested_sku_nullable"
    )
    with pytest.raises(IrreversibleError, match="forward fix or restore a backup"):
        migration.block_reverse(None, None)


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


def test_sample_price_match_is_scoped_to_store_and_site():
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
    assert response.data["data"]["items"][0]["unit_price"] == "10.0000"
    assert response.data["data"]["items"][0]["currency"] == "PHP"


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


def test_influencer_sensitive_fields_are_not_returned_or_searchable_and_status_is_versioned():
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
        handle="secret-handle",
        contact_name="Private Name",
        contact_phone="13800138000",
        contact_email="private@example.test",
        notes="private note",
    )

    listed = client.get("/api/internal/influencers/")
    searched = client.get("/api/internal/influencers/", {"search": "secret-handle"})
    item = listed.data["data"]["results"][0]
    for field in ("handle", "contact_name", "contact_phone", "contact_email", "notes"):
        assert field not in item
    assert searched.data["data"]["count"] == 0

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
