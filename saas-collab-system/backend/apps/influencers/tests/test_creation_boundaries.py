import re

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.influencers.models import (
    BdSampleAttributionSnapshot,
    Influencer,
    InfluencerRestriction,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
)
from apps.influencers.serializers import SampleFulfillmentSerializer, OutreachTaskSerializer
from apps.influencers.services import create_outreach_task, create_sample_fulfillment
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _records(code="creation-boundary"):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(
        username=f"{code}-user",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, code="bd", name="BD")
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code=f"platform-{code}",
        name="TikTok Shop",
        platform_type=PlatformMaster.PlatformType.TIKTOK,
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=f"store-{code}",
        name="Creator store",
        country_code="PH",
        currency="PHP",
    )
    influencer = Influencer.objects.create(
        tenant=tenant,
        code=f"creator-{code}",
        name="Creator",
        platform="tiktok",
    )
    return tenant, user, store, influencer


def _grant_all_scope(role, permission_code):
    permission, _ = Permission.objects.get_or_create(
        code=permission_code,
        defaults={"name": permission_code, "module": "influencers", "action": "manage"},
    )
    role.permissions.add(permission)
    DataScope.objects.create(
        tenant=role.tenant,
        role=role,
        scope_type=DataScope.ScopeType.ALL,
        config={"all": True},
    )


def _task(user, store, influencer=None, task_no="CLIENT-SUPPLIED", **overrides):
    payload = {
        "task_no": task_no,
        "task_name": "Boundary task",
        "store": store,
        "owner": user,
        "influencer": influencer,
    }
    payload.update(overrides)
    return create_outreach_task(
        user=user,
        validated_data=payload,
    )


def test_outreach_task_number_is_server_owned_and_collision_retry_is_safe(monkeypatch):
    tenant, user, store, influencer = _records("task-number")
    existing = OutreachTask.objects.create(
        tenant=tenant,
        task_no="DRJL0001",
        influencer=influencer,
        store=store,
        dispatcher=user,
        owner=user,
    )
    generated = iter(("DRJL0001", "DRJL0002"))
    monkeypatch.setattr(
        "apps.influencers.services._generate_outreach_task_no",
        lambda tenant: next(generated),
    )

    task = _task(user, store, influencer)

    assert existing.task_no == "DRJL0001"
    assert task.task_no == "DRJL0002"
    assert re.fullmatch(r"DRJL\d{4,}", task.task_no)

    serializer = OutreachTaskSerializer(
        data={"task_no": "CLIENT-CANNOT-EDIT", "store": store.pk, "owner": user.pk}
    )
    assert serializer.is_valid(), serializer.errors
    assert "task_no" not in serializer.validated_data


def test_sample_fulfillment_without_target_keeps_influencer_and_does_not_create_target():
    _, user, store, influencer = _records("targetless-sample")
    task = _task(user, store)
    target_count = OutreachTarget.objects.filter(task=task).count()

    assert target_count == 0

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="targetless-sample-key",
        validated_data={
            "fulfillment_no": "TARGETLESS-SAMPLE",
            "outreach_task": task,
            "influencer": influencer,
        },
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.influencer_id == influencer.pk
    assert fulfillment.outreach_target_id is None
    assert OutreachTarget.objects.filter(task=task).count() == target_count
    snapshot = BdSampleAttributionSnapshot.objects.get(fulfillment=fulfillment)
    assert snapshot.creator_username.startswith("__dfcy_missing_creator_handle__:")

    missing_influencer = SampleFulfillmentSerializer(
        data={"fulfillment_no": "MISSING-INFLUENCER", "outreach_task": task.pk}
    )
    assert missing_influencer.is_valid() is False
    assert "influencer" in missing_influencer.errors


def test_sample_edit_can_transition_status_atomically():
    tenant, user, store, influencer = _records("sample-edit-status")
    role = Role.objects.get(tenant=tenant, code="bd")
    _grant_all_scope(role, "influencers.fulfillment.manage")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-edit-status-key",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "product_name_snapshot": "Status transition sample",
            "external_product_id": "STATUS-PRODUCT",
        },
        item_payloads=[],
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.patch(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment.pk}/",
        {"notes": "edited", "status": SampleFulfillment.Status.PROCESSING},
        format="json",
        HTTP_IF_MATCH=f'"{fulfillment.version}"',
    )

    assert response.status_code == 200, response.data
    fulfillment.refresh_from_db()
    assert fulfillment.notes == "edited"
    assert fulfillment.status == SampleFulfillment.Status.PROCESSING
    assert fulfillment.sample_sent_at is not None


def test_invalid_status_transition_rolls_back_fact_edits():
    tenant, user, store, influencer = _records("sample-edit-status-rollback")
    role = Role.objects.get(tenant=tenant, code="bd")
    _grant_all_scope(role, "influencers.fulfillment.manage")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-edit-status-rollback-key",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "product_name_snapshot": "Rollback sample",
            "external_product_id": "ROLLBACK-PRODUCT",
        },
        item_payloads=[],
    )
    original_version = fulfillment.version
    client = APIClient()
    client.force_authenticate(user)

    response = client.patch(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment.pk}/",
        {"notes": "must roll back", "status": SampleFulfillment.Status.COMPLETED},
        format="json",
        HTTP_IF_MATCH=f'"{original_version}"',
    )

    assert response.status_code == 400
    fulfillment.refresh_from_db()
    assert fulfillment.notes == ""
    assert fulfillment.status == SampleFulfillment.Status.PENDING
    assert fulfillment.version == original_version


def test_task_sample_uses_task_product_snapshot_instead_of_client_product_name():
    _, user, store, influencer = _records("task-product-snapshot")
    task = _task(
        user,
        store,
        task_name="Task-facing product name",
        external_product_id="1730000000000000002",
        product_name_snapshot="Task product snapshot",
    )

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="task-product-snapshot-key",
        validated_data={
            "fulfillment_no": "TASK-PRODUCT-SNAPSHOT",
            "outreach_task": task,
            "influencer": influencer,
            "product_name_snapshot": "Stale client product name",
        },
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.external_product_id == task.external_product_id
    assert fulfillment.product_name_snapshot == "Task product snapshot"


def test_standalone_sample_uses_type_number_and_does_not_require_outreach_task():
    _, user, store, influencer = _records("standalone-sample")
    serializer = SampleFulfillmentSerializer(
        data={
            "influencer": influencer.pk,
            "store": store.pk,
            "product_name_snapshot": "Standalone product",
            "external_product_id": "1730000000000000001",
            "link_type": "YYJL",
        }
    )
    assert serializer.is_valid(), serializer.errors

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="standalone-sample-key",
        validated_data=serializer.validated_data,
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.outreach_task_id is None
    assert fulfillment.owner_id == user.pk
    assert fulfillment.store_id == store.pk
    assert re.fullmatch(r"YYJL\d{4,}", fulfillment.fulfillment_no)


def test_existing_target_payload_remains_compatible():
    tenant, user, store, influencer = _records("target-compatibility")
    task = _task(user, store, influencer)
    second_influencer = Influencer.objects.create(
        tenant=tenant,
        code="creator-target-compatibility-second",
        name="Second creator",
        platform="tiktok",
    )
    target = OutreachTarget.objects.create(
        tenant=tenant,
        task=task,
        influencer=second_influencer,
    )

    serializer = SampleFulfillmentSerializer(
        data={
            "fulfillment_no": "LEGACY-TARGET-SAMPLE",
            "outreach_task": task.pk,
            "outreach_target": target.pk,
        }
    )
    assert serializer.is_valid(), serializer.errors

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="legacy-target-key",
        validated_data={
            "fulfillment_no": "LEGACY-TARGET-SAMPLE",
            "outreach_task": task,
            "outreach_target": target,
        },
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.outreach_target_id == target.pk
    assert fulfillment.influencer_id == second_influencer.pk


def test_fulfillment_options_use_manage_permission_tenant_scope_and_minimal_task_fields():
    tenant, user, store, influencer = _records("fulfillment-options")
    role = user.user_roles.get().role
    client = APIClient()
    client.force_authenticate(user)
    denied = client.get("/api/internal/influencers/sample-fulfillment-options/")
    assert denied.status_code == 403

    _grant_all_scope(role, "influencers.fulfillment.manage")
    influencer.handle = "@duplicate.creator"
    influencer.save(update_fields=["handle"])
    task = _task(
        user,
        store,
        influencer,
        notes="must-not-leak",
        external_id="external-secret",
    )
    InfluencerRestriction.objects.create(
        tenant=tenant,
        influencer=influencer,
        is_blacklisted=True,
        created_by=user,
    )

    other_tenant, other_user, other_store, other_influencer = _records("other-options")
    other_task = _task(other_user, other_store, other_influencer)

    response = client.get("/api/internal/influencers/sample-fulfillment-options/")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert {item["id"] for item in payload["tasks"]} == {task.id}
    assert other_task.id not in {item["id"] for item in payload["tasks"]}
    assert {item["id"] for item in payload["influencers"]} == {influencer.id}
    assert payload["influencers"][0]["handle"] == "@duplicate.creator"
    assert payload["influencers"][0]["is_blacklisted"] is True
    assert set(payload["tasks"][0]) == {
        "id",
        "task_no",
        "task_name",
        "store",
        "store_name",
        "product_name_snapshot",
        "external_product_id",
        "sku_prefix",
        "status",
    }
    assert "notes" not in payload["tasks"][0]
    assert "external_id" not in payload["tasks"][0]


def test_outreach_options_include_account_and_blacklist_state():
    tenant, user, _, influencer = _records("outreach-options")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.outreach.view")
    influencer.handle = "@outreach.creator"
    influencer.save(update_fields=["handle"])
    InfluencerRestriction.objects.create(
        tenant=tenant,
        influencer=influencer,
        is_blacklisted=True,
        created_by=user,
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/internal/influencers/outreach-task-options/")

    assert response.status_code == 200
    candidates = response.json()["data"]["influencers"]
    assert candidates == [
        {
            "id": influencer.id,
            "code": influencer.code,
            "name": influencer.name,
            "handle": "@outreach.creator",
            "platform": influencer.platform,
            "is_blacklisted": True,
        }
    ]


def test_fulfillment_account_resolve_can_create_minimal_profile_idempotently():
    tenant, user, _, _ = _records("resolve-account")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    client = APIClient()
    client.force_authenticate(user)

    first = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "@new.creator"},
        format="json",
    )
    second = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "new.creator"},
        format="json",
    )

    assert first.status_code == 201
    assert second.status_code == 200
    assert first.json()["data"]["id"] == second.json()["data"]["id"]
    created = Influencer.objects.get(pk=first.json()["data"]["id"], tenant=tenant)
    assert created.handle == "new.creator"
    assert created.platform == "TikTok"
    assert Influencer.objects.filter(tenant=tenant, handle="new.creator").count() == 1


def test_outreach_manager_can_resolve_existing_influencer():
    _, user, _, influencer = _records("outreach-resolve")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.outreach.manage")
    influencer.handle = "outreach.creator"
    influencer.save(update_fields=["handle"])
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/internal/influencers/resolve/", {"q": "outreach.creator"})

    assert response.status_code == 200
    assert response.json()["data"]["candidates"][0]["id"] == influencer.id

    create_response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "outreach-created.creator"},
        format="json",
    )

    assert create_response.status_code == 403
    assert not Influencer.objects.filter(
        tenant=user.tenant,
        handle="outreach-created.creator",
    ).exists()


def test_account_resolve_prefers_blacklisted_duplicate_profile():
    tenant, user, _, clean = _records("resolve-blacklisted-duplicate")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    clean.handle = "duplicate.creator"
    clean.save(update_fields=["handle"])
    blocked = Influencer.objects.create(
        tenant=tenant,
        code="creator-blocked-duplicate",
        name="Blocked duplicate",
        handle="duplicate.creator",
        platform="tiktok",
    )
    InfluencerRestriction.objects.create(
        tenant=tenant,
        influencer=blocked,
        is_blacklisted=True,
        created_by=user,
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "@duplicate.creator"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == blocked.id
    assert response.json()["data"]["is_blacklisted"] is True
