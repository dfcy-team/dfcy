import re

from django.core.exceptions import ValidationError as DjangoValidationError
import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.influencers.models import (
    Influencer,
    InfluencerProfile,
    InfluencerRestrictEvent,
    InfluencerRestriction,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
)
from apps.influencers.serializers import (
    InfluencerSerializer,
    OutreachTargetSerializer,
    OutreachTaskSerializer,
    SampleFulfillmentSerializer,
)
from apps.influencers.services import (
    create_outreach_task,
    create_sample_fulfillment,
    set_influencer_blacklist,
)
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


def test_outreach_task_can_use_manual_store_when_product_is_not_matched():
    _, user, store, _ = _records("task-unmatched-product")

    serializer = OutreachTaskSerializer(
        data={
            "task_name": "Unmatched product remains creatable",
            "store": store.pk,
            "owner": user.pk,
            "external_product_id": "1737123802146506012",
            "sku_prefix": "",
            "target_count": 10,
        }
    )
    assert serializer.is_valid(), serializer.errors
    task = create_outreach_task(user=user, validated_data=serializer.validated_data)
    assert task.store_id == store.pk
    assert task.external_product_id == "1737123802146506012"
    assert task.sku_prefix == ""


def test_tiktok_handle_schema_is_the_canonical_non_nullable_identity_column():
    field = Influencer._meta.get_field("handle")

    assert field.max_length == 255
    assert field.null is False
    assert field.db_comment == "TikTok用户名"
    assert not hasattr(Influencer(), "canonical_handle")
    assert not hasattr(Influencer(), "canonical_handle_digest")


def test_tiktok_handle_save_normalizes_the_business_field():
    _, _, _, influencer = _records("canonical-handle")
    influencer.handle = " ＠ＭＨＡＩＮＥ＿９４ "
    influencer.save(update_fields=["handle"])

    influencer.refresh_from_db()
    assert influencer.handle == "mhaine_94"

    influencer.platform = "Instagram"
    influencer.handle = "Visible.Account"
    influencer.save(update_fields=["platform", "handle"])
    influencer.refresh_from_db()
    assert influencer.handle == "Visible.Account"


def test_influencer_api_exposes_handle_but_not_identity_helpers():
    _, _, _, influencer = _records("handle-output")
    influencer.handle = "mhaine_94"
    influencer.save(update_fields=["handle"])

    payload = InfluencerSerializer(influencer).data

    assert payload["handle"] == "mhaine_94"
    assert "canonical_handle" not in payload
    assert "canonical_handle_digest" not in payload


def test_duplicate_tiktok_handle_shares_blacklist_identity_and_blocks_sampling():
    tenant, user, store, blocked = _records("canonical-blacklist")
    blocked.handle = "＠ＭＨＡＩＮＥ＿９４"
    blocked.save(update_fields=["handle"])
    duplicate = Influencer.objects.create(
        tenant=tenant,
        code="canonical-blacklist-duplicate",
        name="Auxiliary display name",
        platform="TikTok",
        handle="mhaine_94",
    )
    set_influencer_blacklist(
        user=user,
        influencer=blocked,
        blacklisted=True,
        reason="identity-level blacklist",
    )

    blocked.refresh_from_db()
    duplicate.refresh_from_db()
    assert blocked.handle == "mhaine_94"
    assert duplicate.handle == "mhaine_94"
    with pytest.raises(ValidationError, match="Blacklisted influencers"):
        create_sample_fulfillment(
            user=user,
            request_key="canonical-blacklist-sample",
            validated_data={
                "influencer": duplicate,
                "store": store,
                "link_type": "YYJL",
                "external_product_id": "CANONICAL-BLACKLIST-PRODUCT",
            },
            item_payloads=[],
        )


def test_blacklist_syncs_duplicate_restrictions_and_any_active_restriction_blocks():
    tenant, user, store, blocked = _records("canonical-restriction-sync")
    blocked.handle = "sync.creator"
    blocked.save(update_fields=["handle"])
    duplicate = Influencer.objects.create(
        tenant=tenant,
        code="canonical-restriction-sync-duplicate",
        name="Duplicate creator",
        platform="TikTok",
        handle="SYNC.CREATOR",
    )

    set_influencer_blacklist(
        user=user,
        influencer=blocked,
        blacklisted=True,
        reason="sync blacklist",
    )
    restrictions = InfluencerRestriction.objects.filter(
        tenant=tenant,
        influencer_id__in=[blocked.id, duplicate.id],
    )
    assert restrictions.count() == 2
    assert set(restrictions.values_list("is_blacklisted", flat=True)) == {True}
    assert InfluencerRestrictEvent.objects.filter(
        tenant=tenant,
        influencer_id__in=[blocked.id, duplicate.id],
        action=InfluencerRestrictEvent.Action.BLACKLIST,
    ).count() == 2

    set_influencer_blacklist(
        user=user,
        influencer=blocked,
        blacklisted=False,
        reason="sync unblacklist",
    )
    restrictions = InfluencerRestriction.objects.filter(
        tenant=tenant,
        influencer_id__in=[blocked.id, duplicate.id],
    )
    assert set(restrictions.values_list("is_blacklisted", flat=True)) == {False}

    duplicate_restriction = restrictions.get(influencer=duplicate)
    duplicate_restriction.is_blacklisted = True
    duplicate_restriction.save()

    with pytest.raises(ValidationError, match="Blacklisted influencers"):
        create_sample_fulfillment(
            user=user,
            request_key="canonical-restriction-sync-sample",
            validated_data={
                "influencer": blocked,
                "store": store,
                "link_type": "YYJL",
                "external_product_id": "CANONICAL-RESTRICTION-SYNC-PRODUCT",
            },
            item_payloads=[],
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (("handle", "changed.creator"), ("platform", "Instagram")),
)
def test_blacklisted_identity_cannot_change_handle_or_platform(field, value):
    _, user, _, influencer = _records(f"canonical-change-{field}")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.manage")
    influencer.handle = "locked.creator"
    influencer.save(update_fields=["handle"])
    set_influencer_blacklist(
        user=user,
        influencer=influencer,
        blacklisted=True,
        reason="locked identity",
    )

    setattr(influencer, field, value)
    expected = "locked.creator" if field == "handle" else "tiktok"
    with pytest.raises(DjangoValidationError, match="Blacklisted influencer identities"):
        influencer.save(update_fields=[field])
    influencer.refresh_from_db()
    assert getattr(influencer, field) == expected

    client = APIClient()
    client.force_authenticate(user)
    response = client.patch(
        f"/api/internal/influencers/{influencer.pk}/",
        {field: value},
        format="json",
    )
    assert response.status_code == 400, response.data
    influencer.refresh_from_db()
    assert getattr(influencer, field) == expected


def test_handle_identity_is_tenant_scoped_and_empty_handle_has_no_shared_identity():
    tenant, _, _, influencer = _records("canonical-scope")
    influencer.handle = ""
    influencer.save(update_fields=["handle"])
    other_tenant, _, _, foreign = _records("canonical-scope-other")
    foreign.handle = "＠ＭＨＡＩＮＥ＿９４"
    foreign.save(update_fields=["handle"])

    assert influencer.handle == ""
    assert foreign.handle == "mhaine_94"
    assert foreign.tenant_id == other_tenant.id


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
            "external_product_id": "EDIT-STATUS-PRODUCT",
        },
        item_payloads=[],
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.patch(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment.pk}/",
        {"notes": "edited", "status": SampleFulfillment.Status.SHIPPED},
        format="json",
        HTTP_IF_MATCH=f'"{fulfillment.version}"',
    )

    assert response.status_code == 200, response.data
    fulfillment.refresh_from_db()
    assert fulfillment.notes == "edited"
    assert fulfillment.status == SampleFulfillment.Status.SHIPPED
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
            "external_product_id": "ROLLBACK-STATUS-PRODUCT",
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


def test_terminal_sample_status_requires_explicit_confirmation_on_generic_patch():
    tenant, user, store, influencer = _records("sample-terminal-confirmation")
    role = Role.objects.get(tenant=tenant, code="bd")
    _grant_all_scope(role, "influencers.fulfillment.manage")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-terminal-confirmation-key",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "external_product_id": "TERMINAL-STATUS-PRODUCT",
        },
        item_payloads=[],
    )
    client = APIClient()
    client.force_authenticate(user)

    denied = client.patch(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment.pk}/",
        {"status": SampleFulfillment.Status.CANCELLED},
        format="json",
        HTTP_IF_MATCH=f'"{fulfillment.version}"',
    )

    assert denied.status_code == 400
    fulfillment.refresh_from_db()
    assert fulfillment.status == SampleFulfillment.Status.PENDING
    assert fulfillment.version == 1

    confirmed = client.patch(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment.pk}/",
        {
            "status": SampleFulfillment.Status.CANCELLED,
            "confirm_terminal": True,
        },
        format="json",
        HTTP_IF_MATCH=f'"{fulfillment.version}"',
    )

    assert confirmed.status_code == 200, confirmed.data
    assert confirmed.data["data"]["status"] == SampleFulfillment.Status.CANCELLED


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
        request_key="sample-product-snapshot-idempotency",
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
    missing_product = SampleFulfillmentSerializer(
        data={
            "influencer": influencer.pk,
            "store": store.pk,
            "product_name_snapshot": "Standalone product",
            "link_type": "YYJL",
        }
    )
    assert missing_product.is_valid() is False
    assert "external_product_id" in missing_product.errors

    serializer = SampleFulfillmentSerializer(
        data={
            "influencer": influencer.pk,
            "store": store.pk,
            "product_name_snapshot": "Standalone product",
            "external_product_id": "1730000000000000001",
            "link_type": "YYJL",
            "items": [{"site_code": "PH", "requested_sku": "", "quantity": 1}],
        }
    )
    assert serializer.is_valid(), serializer.errors

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="standalone-sample-key",
        validated_data=serializer.validated_data,
        item_payloads=[{"site_code": "PH", "requested_sku": "", "quantity": 1}],
    )

    assert created is True
    assert fulfillment.outreach_task_id is None
    assert fulfillment.owner_id == user.pk
    assert fulfillment.store_id == store.pk
    assert fulfillment.external_product_id == "1730000000000000001"
    assert fulfillment.items.get().requested_sku is None
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
    second_influencer.handle = "target.creator"
    second_influencer.save(update_fields=["handle"])
    assert OutreachTargetSerializer(target).data["influencer_handle"] == "target.creator"

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
    influencer.handle = "option.creator"
    influencer.save(update_fields=["handle"])
    task = _task(
        user,
        store,
        influencer,
        notes="must-not-leak",
        external_id="external-secret",
    )

    other_tenant, other_user, other_store, other_influencer = _records("other-options")
    other_task = _task(other_user, other_store, other_influencer)

    response = client.get("/api/internal/influencers/sample-fulfillment-options/")

    assert response.status_code == 200
    payload = response.json()["data"]
    assert {item["id"] for item in payload["tasks"]} == {task.id}
    assert other_task.id not in {item["id"] for item in payload["tasks"]}
    assert {item["id"] for item in payload["influencers"]} == {influencer.id}
    assert payload["influencers"][0]["handle"] == "option.creator"
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

    outreach_permission, _ = Permission.objects.get_or_create(
        code="influencers.outreach.view",
        defaults={"name": "influencers.outreach.view", "module": "influencers", "action": "view"},
    )
    role.permissions.add(outreach_permission)
    outreach_response = client.get("/api/internal/influencers/outreach-task-options/")
    assert outreach_response.status_code == 200
    outreach_payload = outreach_response.json()["data"]
    assert {item["id"] for item in outreach_payload["influencers"]} == {influencer.id}
    assert outreach_payload["influencers"][0]["handle"] == "option.creator"


def test_blacklist_cascade_requires_profile_and_fulfillment_manage_permissions():
    tenant, user, store, influencer = _records("blacklist-permission")
    role = Role.objects.get(tenant=tenant, code="bd")
    _grant_all_scope(role, "influencers.manage")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="blacklist-permission-sample-key",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "external_product_id": "BLACKLIST-PERMISSION-PRODUCT",
        },
        item_payloads=[],
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        f"/api/internal/influencers/{influencer.pk}/blacklist/",
        {"is_blacklisted": True, "reason": "missing fulfillment permission"},
        format="json",
    )

    assert response.status_code == 403
    assert not InfluencerRestriction.objects.filter(
        tenant=tenant,
        influencer=influencer,
    ).exists()
    assert not InfluencerRestrictEvent.objects.filter(
        tenant=tenant,
        influencer=influencer,
    ).exists()
    fulfillment.refresh_from_db()
    assert fulfillment.status == SampleFulfillment.Status.PENDING


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


def test_fulfillment_account_resolve_rejects_display_name_as_tiktok_handle():
    _, user, _, _ = _records("resolve-display-name")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "She deserve ✨"},
        format="json",
    )

    assert response.status_code == 400
    assert not Influencer.objects.filter(tenant=user.tenant, name="She deserve ✨").exists()


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


def test_account_resolve_reuses_normalized_legacy_handle_and_does_not_bypass_blacklist():
    tenant, user, _, _ = _records("resolve-legacy-handle")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    clean = Influencer.objects.create(
        tenant=tenant,
        code="legacy-clean",
        name="Clean auxiliary name",
        handle="legacy.creator",
        platform="tiktok",
    )
    blocked = Influencer.objects.create(
        tenant=tenant,
        code="legacy-blocked",
        name="Blocked auxiliary name",
        handle="＠ＬＥＧＡＣＹ．ＣＲＥＡＴＯＲ",
        platform="TikTok",
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
        {"handle": " ＠Ｌｅｇａｃｙ．Ｃｒｅａｔｏｒ "},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["data"]["id"] == blocked.id
    assert response.data["data"]["is_blacklisted"] is True
    assert Influencer.objects.filter(tenant=tenant).count() == 3
    assert clean.id != blocked.id


def test_account_resolve_keeps_tenant_and_platform_scope():
    tenant, user, _, _ = _records("resolve-scope")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    other_platform = Influencer.objects.create(
        tenant=tenant,
        code="instagram-scope-creator",
        name="scoped.creator",
        handle="",
        platform="Instagram",
    )
    other_tenant, _, _, _ = _records("resolve-scope-other")
    foreign = Influencer.objects.create(
        tenant=other_tenant,
        code="foreign-scope-creator",
        name="scoped.creator",
        handle="",
        platform="TikTok",
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "@scoped.creator"},
        format="json",
    )

    assert response.status_code == 201, response.data
    resolved_id = response.data["data"]["id"]
    resolved = Influencer.objects.get(pk=resolved_id)
    assert resolved.tenant_id == tenant.id
    assert resolved.platform == "TikTok"
    assert resolved_id not in {other_platform.id, foreign.id}
    assert Influencer.objects.filter(
        tenant=tenant,
        name="scoped.creator",
        platform__iexact="TikTok",
    ).count() == 1


def test_account_resolve_prefers_normalized_handle_over_another_profile_code():
    tenant, user, _, code_match = _records("resolve-handle-priority")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    code_match.code = "mhaine_94"
    code_match.name = "mhaine_94"
    code_match.handle = "different.creator"
    code_match.save(update_fields=["code", "name", "handle"])
    handle_match = Influencer.objects.create(
        tenant=tenant,
        code="handle-priority-creator",
        name="Handle match",
        handle="mhaine_94",
        platform="tiktok",
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "＠ＭＨＡＩＮＥ＿９４"},
        format="json",
    )

    assert response.status_code == 200
    assert response.json()["data"]["id"] == handle_match.id
    assert response.json()["data"]["handle"] == "mhaine_94"


def test_account_resolve_ignores_auxiliary_name_and_display_name():
    tenant, user, _, _ = _records("resolve-auxiliary-name")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    legacy = Influencer.objects.create(
        tenant=tenant,
        code="auxiliary-name-creator",
        name="Shedeserve",
        handle="canonical.creator",
        platform="TikTok",
    )
    InfluencerProfile.objects.create(
        tenant=tenant,
        influencer=legacy,
        display_name="Shedeserve ✨",
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "Shedeserve ✨"},
        format="json",
    )

    assert response.status_code == 400, response.data
    assert Influencer.objects.filter(tenant=tenant).count() == 2
    assert Influencer.objects.get(pk=legacy.pk).handle == "canonical.creator"


def test_account_resolve_scans_legacy_candidates_beyond_the_old_fallback_bound():
    tenant, user, _, _ = _records("resolve-legacy-overflow")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    for index in range(1001):
        Influencer.objects.create(
            tenant=tenant,
            code=f"legacy-preceding-{index}",
            name=f"Unrelated legacy creator {index}",
            handle="",
            platform="TikTok",
        )
    legacy = Influencer.objects.create(
        tenant=tenant,
        code="legacy-overflow-target",
        name="Legacy display only",
        handle="＠Ｌｅｇａｃｙ．Ｔａｒｇｅｔ",
        platform="TikTok",
    )
    count_before = Influencer.objects.filter(tenant=tenant).count()
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": "legacy.target"},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.data["data"]["id"] == legacy.id
    assert Influencer.objects.filter(tenant=tenant).count() == count_before
