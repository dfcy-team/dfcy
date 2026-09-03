import importlib
import re
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.db.migrations.exceptions import IrreversibleError
from django.db.migrations.state import ProjectState
from django.db.models import Exists
from django.db.models.query import QuerySet
from django.utils import timezone
import pytest
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers import models as influencer_models
from apps.influencers import services as influencer_services
from apps.influencers import views as influencer_views
from apps.influencers.management.commands.import_affiliate_orders_csv import (
    _column_map as affiliate_column_map,
    _parse_row as parse_affiliate_row,
)
from apps.influencers.models import (
    Influencer,
    InfluencerProfile,
    InfluencerRestrictEvent,
    InfluencerRestriction,
    BdSampleAttributionSnapshot,
    OutreachTarget,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
    normalize_tiktok_username,
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


def test_affiliate_import_preserves_missing_commissions_as_null():
    row = {
        "data_time": "2026-09-01",
        "shop_abbr": "TK1PH",
        "site": "PH",
        "order_id": "ORDER-1",
        "product_id": "PRODUCT-1",
        "sku_id": "SKU-1",
        "creator_username": "creator.account",
        "payment_amount": "10.0000",
        "quantity": "1",
        "currency": "PHP",
        "fully_returned": "否",
        "order_status": "completed",
        "actual_paid_commission": "",
        "estimated_paid_commission": "2.5000",
    }
    mapping = affiliate_column_map(list(row))

    parsed = parse_affiliate_row(row, mapping, "test")

    assert parsed["actual_paid_commission"] is None
    assert parsed["estimated_paid_commission"] == Decimal("2.5000")


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
    DataScope.objects.get_or_create(
        tenant=role.tenant,
        role=role,
        scope_type=DataScope.ScopeType.ALL,
        defaults={"config": {"all": True}},
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
    influencer.handle = " @MHAINE_94 "
    influencer.save(update_fields=["handle"])

    influencer.refresh_from_db()
    assert influencer.handle == "mhaine_94"

    influencer.platform = "Instagram"
    influencer.handle = "Visible.Account"
    influencer.save(update_fields=["platform", "handle"])
    influencer.refresh_from_db()
    assert influencer.handle == "Visible.Account"


def test_tiktok_handle_normalization_canonicalizes_fullwidth_aliases():
    _, _, _, influencer = _records("strict-canonical-handle")

    assert normalize_tiktok_username(" @MHAINE_94 ") == "mhaine_94"
    assert normalize_tiktok_username("＠ＭＨＡＩＮＥ＿９４") == "mhaine_94"

    influencer.handle = "＠ＭＨＡＩＮＥ＿９４"
    influencer.save(update_fields=["handle"])
    influencer.refresh_from_db()
    assert influencer.handle == "mhaine_94"


def test_switching_to_tiktok_validates_an_existing_handle():
    _, _, _, influencer = _records("tiktok-platform-validation")
    influencer.platform = "Instagram"
    influencer.handle = "Display Name"
    influencer.save(update_fields=["platform", "handle"])

    serializer = InfluencerSerializer(
        influencer,
        data={"platform": "TikTok"},
        partial=True,
    )

    assert serializer.is_valid() is False
    assert "handle" in serializer.errors

    influencer.platform = "TikTok"
    with pytest.raises(DjangoValidationError, match="TikTok username"):
        influencer.save(update_fields=["platform"])


def test_influencer_api_exposes_handle_but_not_identity_helpers():
    _, _, _, influencer = _records("handle-output")
    influencer.handle = "mhaine_94"
    influencer.save(update_fields=["handle"])

    payload = InfluencerSerializer(influencer).data

    assert payload["handle"] == "mhaine_94"
    assert "canonical_handle" not in payload
    assert "canonical_handle_digest" not in payload


def test_influencer_detail_compact_mode_omits_duplicate_relation_payloads():
    _, user, _, influencer = _records("compact-influencer-detail")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.view")
    client = APIClient()
    client.force_authenticate(user)

    response = client.get(
        f"/api/internal/influencers/{influencer.pk}/?include_relations=false"
    )

    assert response.status_code == 200
    payload = response.json()["data"]
    assert payload["id"] == influencer.pk
    assert "profile" in payload
    assert "contacts" not in payload
    assert "blacklist_history" not in payload


def test_influencer_collection_uses_compact_rows():
    _, user, _, influencer = _records("compact-influencer-list")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.view")
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/internal/influencers/?page=1&page_size=20")

    assert response.status_code == 200
    row = next(item for item in response.json()["data"]["results"] if item["id"] == influencer.pk)
    assert "profile" in row
    assert "contacts" not in row
    assert "blacklist_history" not in row


@pytest.mark.parametrize("ordering", [
    "profile__average_video_views",
    "-profile__average_video_views",
    "profile__historical_gmv",
    "-profile__historical_gmv",
])
def test_influencer_collection_supports_performance_ordering(ordering):
    _, user, _, _ = _records(f"performance-ordering-{ordering.startswith('-')}-{ordering[-3:]}")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.view")
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/internal/influencers/", {"ordering": ordering})

    assert response.status_code == 200


def test_influencer_contacts_support_multiple_platforms():
    _, user, _, influencer = _records("multiple-contact-platforms")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.view")
    _grant_all_scope(role, "influencers.manage")
    client = APIClient()
    client.force_authenticate(user)

    response = client.patch(
        f"/api/internal/influencers/{influencer.pk}/contacts/",
        {
            "contacts": [
                {"channel": "whatsapp", "value": "+63000000001", "is_primary": True},
                {"channel": "instagram", "value": "creator.account", "label": "备用"},
            ]
        },
        format="json",
        HTTP_IF_MATCH=influencer.updated_at.isoformat(),
    )

    assert response.status_code == 200, response.data
    assert [item["channel"] for item in response.data["data"]] == ["whatsapp", "instagram"]
    fetched = client.get(f"/api/internal/influencers/{influencer.pk}/contacts/")
    assert fetched.status_code == 200, fetched.data
    assert {item["channel"] for item in fetched.data["data"]} == {"whatsapp", "instagram"}


def test_duplicate_tiktok_handle_shares_blacklist_identity_and_blocks_sampling():
    tenant, user, store, blocked = _records("canonical-blacklist")
    blocked.handle = " @MHAINE_94 "
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
    foreign.handle = " @FOREIGN.CREATOR "
    foreign.save(update_fields=["handle"])

    assert influencer.handle == ""
    assert foreign.handle == "foreign.creator"
    assert foreign.tenant_id == other_tenant.id


def test_identity_edit_api_locks_old_and_new_groups_in_id_order(monkeypatch):
    tenant, user, store, first = _records("identity-edit-lock-order")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.manage")
    first.handle = "shared.creator"
    first.save(update_fields=["handle"])
    selected = Influencer.objects.create(
        tenant=tenant,
        code="identity-edit-lock-order-selected",
        name="Selected duplicate",
        platform="TikTok",
        handle="SHARED.CREATOR",
    )
    prospective = Influencer.objects.create(
        tenant=tenant,
        code="identity-edit-lock-order-prospective",
        name="Prospective duplicate",
        platform="TikTok",
        handle="changed.creator",
    )
    fulfillment = SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no="identity-edit-lock-order-sample",
        request_key="identity-edit-lock-order-sample-request",
        request_hash="identity-edit-lock-order-sample-hash",
        link_type="YYJL",
        influencer=first,
        store=store,
        owner=user,
    )
    snapshot = BdSampleAttributionSnapshot.objects.create(
        tenant=tenant,
        fulfillment=fulfillment,
        owner=user,
        influencer=first,
        store=store,
        creator_username="shared.creator",
        shop_abbr=store.code,
        site="PH",
        product_id="identity-edit-product",
        product_name="Identity edit product",
        sku_id="identity-edit-sku",
        sampled_at=timezone.now(),
        sample_status=SampleFulfillment.Status.PENDING,
        currency="PHP",
        pricing_status="pending",
    )
    observed_orders = []
    original_lock = influencer_views.lock_influencer_identity_change

    def observe_lock(*args, **kwargs):
        locked = original_lock(*args, **kwargs)
        observed_orders.append(
            list(
                Influencer.objects.filter(
                    tenant=tenant,
                    pk__in=[first.pk, selected.pk, prospective.pk],
                ).order_by("pk").values_list("pk", flat=True)
            )
        )
        return locked

    monkeypatch.setattr(influencer_views, "lock_influencer_identity_change", observe_lock)
    client = APIClient()
    client.force_authenticate(user)

    response = client.patch(
        f"/api/internal/influencers/{selected.pk}/",
        {"handle": "changed.creator"},
        format="json",
        HTTP_IF_MATCH=selected.updated_at.isoformat(),
    )

    assert response.status_code == 200, response.data
    assert observed_orders == [[first.pk, selected.pk, prospective.pk]]
    first.refresh_from_db()
    selected.refresh_from_db()
    prospective.refresh_from_db()
    snapshot.refresh_from_db()
    assert first.handle == "changed.creator"
    assert selected.handle == "changed.creator"
    assert prospective.handle == "changed.creator"
    assert snapshot.creator_username == "changed.creator"
    assert first.name != selected.name


def test_identity_edit_cannot_join_blacklisted_handle_group():
    tenant, user, _, selected = _records("identity-edit-blacklisted-target")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.manage")
    selected.handle = "clean.creator"
    selected.save(update_fields=["handle"])
    blocked = Influencer.objects.create(
        tenant=tenant,
        code="identity-edit-blacklisted-target-blocked",
        name="Blocked target identity",
        platform="TikTok",
        handle="blocked.creator",
    )
    set_influencer_blacklist(
        user=user,
        influencer=blocked,
        blacklisted=True,
        reason="blocked target identity",
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.patch(
        f"/api/internal/influencers/{selected.pk}/",
        {"handle": " @BLOCKED.CREATOR "},
        format="json",
    )

    assert response.status_code == 422, response.data
    assert response.data["code"] == "BUSINESS_RULE_VIOLATION"
    selected.refresh_from_db()
    assert selected.handle == "clean.creator"

    selected.handle = "blocked.creator"
    with pytest.raises(DjangoValidationError, match="Blacklisted influencer identities"):
        selected.save(update_fields=["handle"])
    selected.refresh_from_db()
    assert selected.handle == "clean.creator"


def test_duplicate_handle_targets_share_capacity_progress_and_terminal_completion():
    tenant, user, store, first = _records("logical-target-identity")
    first.handle = "shared.creator"
    first.save(update_fields=["handle"])
    duplicate = Influencer.objects.create(
        tenant=tenant,
        code="logical-target-identity-duplicate",
        name="Duplicate creator",
        platform="TikTok",
        handle=" @SHARED.CREATOR ",
    )
    task = _task(user, store, first, target_count=2)
    first_target = OutreachTarget.objects.get(task=task, influencer=first)

    reused, created = influencer_services.add_outreach_target(
        user=user,
        task=task,
        influencer=duplicate,
    )
    assert created is False
    assert reused.pk == first_target.pk

    historical_duplicate = OutreachTarget.objects.create(
        tenant=tenant,
        task=task,
        influencer=duplicate,
    )
    assert task.linked_count == 1
    progress = influencer_services.outreach_task_progress(user=user, task=task)
    assert progress["linked_count"] == 1
    assert progress["remaining_count"] == 1

    influencer_services.update_outreach_target(
        user=user,
        task=task,
        target=first_target,
        expected_version=first_target.version,
        outreach_result=OutreachTarget.OutreachResult.SUCCESS,
    )
    influencer_services.update_outreach_target(
        user=user,
        task=task,
        target=historical_duplicate,
        expected_version=historical_duplicate.version,
        outreach_result=OutreachTarget.OutreachResult.SUCCESS,
    )
    task.refresh_from_db()
    assert task.status == OutreachTask.Status.PENDING

    second_identity = Influencer.objects.create(
        tenant=tenant,
        code="logical-target-identity-second",
        name="Second creator",
        platform="TikTok",
        handle="second.creator",
    )
    _, created = influencer_services.add_outreach_target(
        user=user,
        task=task,
        influencer=second_identity,
    )
    assert created is True
    assert task.linked_count == 2

    overflow = Influencer.objects.create(
        tenant=tenant,
        code="logical-target-identity-overflow",
        name="Overflow creator",
        platform="TikTok",
        handle="overflow.creator",
    )
    with pytest.raises(ValidationError, match="target count"):
        influencer_services.add_outreach_target(
            user=user,
            task=task,
            influencer=overflow,
        )


def test_each_sample_record_counts_toward_task_completion_even_for_duplicate_handles():
    tenant, user, store, first = _records("logical-sample-identity")
    first.handle = "sample.creator"
    first.save(update_fields=["handle"])
    duplicate = Influencer.objects.create(
        tenant=tenant,
        code="logical-sample-identity-duplicate",
        name="Duplicate sample creator",
        platform="TikTok",
        handle="SAMPLE.CREATOR",
    )
    task = _task(user, store, target_count=2)
    first_target, _ = influencer_services.add_outreach_target(
        user=user,
        task=task,
        influencer=first,
    )
    duplicate_target = OutreachTarget.objects.create(
        tenant=tenant,
        task=task,
        influencer=duplicate,
    )
    fulfillments = []
    for suffix, target in (("first", first_target), ("duplicate", duplicate_target)):
        fulfillment, _ = create_sample_fulfillment(
            user=user,
            request_key=f"logical-sample-identity-{suffix}",
            validated_data={
                "outreach_task": task,
                "outreach_target": target,
            },
            item_payloads=[],
        )
        for status in (
            SampleFulfillment.Status.SHIPPED,
            SampleFulfillment.Status.DELIVERED,
            SampleFulfillment.Status.COMPLETED,
        ):
            fulfillment = influencer_services.transition_sample_fulfillment(
                user=user,
                fulfillment=fulfillment,
                status=status,
                expected_version=fulfillment.version,
                confirm_terminal=status == SampleFulfillment.Status.COMPLETED,
            )
        fulfillments.append(fulfillment)

    task.refresh_from_db()
    payload = OutreachTaskSerializer(task).data
    assert task.status == OutreachTask.Status.COMPLETED
    assert payload["sample_fulfillment_count"] == 2
    assert payload["sample_fulfillment_completed_count"] == 2
    assert payload["completion_validation"]["target_reached"] is True


def test_pending_sample_record_auto_completes_task_when_target_is_reached():
    tenant, user, store, influencer = _records("pending-sample-auto-complete")
    task = _task(user, store, influencer, target_count=1)

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="pending-sample-auto-complete-key",
        validated_data={"outreach_task": task, "influencer": influencer},
        item_payloads=[],
    )

    task.refresh_from_db()
    assert created is True
    assert fulfillment.status == SampleFulfillment.Status.PENDING
    assert task.status == OutreachTask.Status.COMPLETED
    assert task.finalized_at is not None


def test_sample_order_number_auto_ships_and_returns_current_database_state():
    _, user, store, influencer = _records("sample-order-auto-ship")
    task = _task(user, store, influencer, target_count=2)

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="sample-order-auto-ship-key",
        validated_data={
            "outreach_task": task,
            "influencer": influencer,
            "sample_order_no": "ORDER-1001",
        },
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.status == SampleFulfillment.Status.SHIPPED
    assert fulfillment.shipped_at is not None
    assert fulfillment.version == 2


def test_completed_task_accepts_additional_samples_but_cancelled_task_does_not():
    tenant, user, store, influencer = _records("completed-task-extra-sample")
    task = _task(user, store, influencer, target_count=1)
    QuerySet.update(OutreachTask.objects.filter(pk=task.pk), status=OutreachTask.Status.COMPLETED)
    task.refresh_from_db()

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="completed-task-extra-sample-key",
        validated_data={"outreach_task": task, "influencer": influencer},
        item_payloads=[],
    )
    assert created is True
    assert fulfillment.outreach_task_id == task.pk

    QuerySet.update(OutreachTask.objects.filter(pk=task.pk), status=OutreachTask.Status.CANCELLED)
    task.refresh_from_db()
    with pytest.raises(ValidationError, match="cannot change targets or samples"):
        create_sample_fulfillment(
            user=user,
            request_key="cancelled-task-extra-sample-key",
            validated_data={"outreach_task": task, "influencer": influencer},
            item_payloads=[],
        )


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


def test_sample_edit_can_mark_pending_record_completed_atomically():
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
        {
            "notes": "edited",
            "status": SampleFulfillment.Status.COMPLETED,
            "confirm_terminal": True,
        },
        format="json",
        HTTP_IF_MATCH=f'"{fulfillment.version}"',
    )

    assert response.status_code == 200, response.data
    fulfillment.refresh_from_db()
    assert fulfillment.notes == "edited"
    assert fulfillment.status == SampleFulfillment.Status.COMPLETED
    assert fulfillment.finalized_at is not None


def test_sample_edit_rejects_manual_intermediate_status():
    tenant, user, store, influencer = _records("sample-edit-intermediate-status")
    role = Role.objects.get(tenant=tenant, code="bd")
    _grant_all_scope(role, "influencers.fulfillment.manage")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="sample-edit-intermediate-status-key",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "external_product_id": "INTERMEDIATE-STATUS-PRODUCT",
        },
        item_payloads=[],
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.patch(
        f"/api/internal/influencers/sample-fulfillments/{fulfillment.pk}/",
        {"status": SampleFulfillment.Status.SHIPPED},
        format="json",
        HTTP_IF_MATCH=f'"{fulfillment.version}"',
    )

    assert response.status_code == 400
    fulfillment.refresh_from_db()
    assert fulfillment.status == SampleFulfillment.Status.PENDING


def test_target_creation_reads_influencer_before_identity_group_lock(monkeypatch):
    _, user, store, influencer = _records("target-lock-order")
    influencer.handle = "shared.creator"
    influencer.save(update_fields=["handle"])
    task = _task(user, store)
    events = []

    original_tenant_influencer = influencer_services._tenant_influencer
    original_identity_queryset = influencer_services.influencer_identity_queryset
    original_locked_task = influencer_services._locked_task

    def observe_tenant_influencer(*args, **kwargs):
        assert kwargs["for_update"] is False
        events.append("influencer_read")
        return original_tenant_influencer(*args, **kwargs)

    def observe_identity_queryset(*args, **kwargs):
        assert kwargs["for_update"] is True
        events.append("identity_group")
        return original_identity_queryset(*args, **kwargs)

    def observe_locked_task(*args, **kwargs):
        events.append("task")
        return original_locked_task(*args, **kwargs)

    monkeypatch.setattr(influencer_services, "_tenant_influencer", observe_tenant_influencer)
    monkeypatch.setattr(
        influencer_services,
        "influencer_identity_queryset",
        observe_identity_queryset,
    )
    monkeypatch.setattr(influencer_services, "_locked_task", observe_locked_task)
    monkeypatch.setattr(
        influencer_services,
        "_locked_influencer",
        lambda *args, **kwargs: pytest.fail("target creation must not lock the selected influencer row"),
    )

    target, created = influencer_services.add_outreach_target(
        user=user,
        task=task,
        influencer=influencer,
    )

    assert created is True
    assert target.influencer_id == influencer.pk
    assert events == ["influencer_read", "identity_group", "task"]


def test_task_sample_creation_locks_identity_before_task_and_target(monkeypatch):
    _, user, store, influencer = _records("task-sample-lock-order")
    task = _task(user, store)
    target, _ = influencer_services.add_outreach_target(
        user=user,
        task=task,
        influencer=influencer,
    )
    events = []
    original_identity_queryset = influencer_services.influencer_identity_queryset
    original_locked_task = influencer_services._locked_task
    original_locked_target = influencer_services._locked_target

    def observe_identity_queryset(*args, **kwargs):
        assert kwargs["for_update"] is True
        events.append("identity_group")
        return original_identity_queryset(*args, **kwargs)

    def observe_locked_task(*args, **kwargs):
        events.append("task")
        return original_locked_task(*args, **kwargs)

    def observe_locked_target(*args, **kwargs):
        events.append("target")
        return original_locked_target(*args, **kwargs)

    monkeypatch.setattr(
        influencer_services,
        "influencer_identity_queryset",
        observe_identity_queryset,
    )
    monkeypatch.setattr(influencer_services, "_locked_task", observe_locked_task)
    monkeypatch.setattr(influencer_services, "_locked_target", observe_locked_target)

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="outreach-sample-lock-order-key",
        validated_data={
            "outreach_task": task,
            "outreach_target": target,
        },
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.outreach_target_id == target.pk
    assert events[:3] == ["identity_group", "task", "target"]


def test_standalone_sample_creation_locks_identity_before_store_and_owner(monkeypatch):
    _, user, store, influencer = _records("standalone-sample-lock-order")
    events = []
    original_identity_queryset = influencer_services.influencer_identity_queryset
    original_locked_store = influencer_services._locked_store
    original_locked_user = influencer_services._locked_user

    def observe_identity_queryset(*args, **kwargs):
        assert kwargs["for_update"] is True
        events.append("identity_group")
        return original_identity_queryset(*args, **kwargs)

    def observe_locked_store(*args, **kwargs):
        events.append("store")
        return original_locked_store(*args, **kwargs)

    def observe_locked_user(*args, **kwargs):
        events.append("owner")
        return original_locked_user(*args, **kwargs)

    monkeypatch.setattr(
        influencer_services,
        "influencer_identity_queryset",
        observe_identity_queryset,
    )
    monkeypatch.setattr(influencer_services, "_locked_store", observe_locked_store)
    monkeypatch.setattr(influencer_services, "_locked_user", observe_locked_user)

    fulfillment, created = create_sample_fulfillment(
        user=user,
        request_key="standalone-sample-lock-order-key",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "external_product_id": "STANDALONE-LOCK-ORDER-PRODUCT",
        },
        item_payloads=[],
    )

    assert created is True
    assert fulfillment.influencer_id == influencer.pk
    assert events[:3] == ["identity_group", "store", "owner"]


def test_influencer_task_creation_locks_identity_before_store_and_owner(monkeypatch):
    _, user, store, influencer = _records("influencer-task-lock-order")
    influencer.handle = "task.creator"
    influencer.save(update_fields=["handle"])
    events = []
    original_identity_queryset = influencer_services.influencer_identity_queryset
    original_locked_store = influencer_services._locked_store
    original_locked_user = influencer_services._locked_user

    def observe_identity_queryset(*args, **kwargs):
        assert kwargs["for_update"] is True
        events.append("identity_group")
        return original_identity_queryset(*args, **kwargs)

    def observe_locked_store(*args, **kwargs):
        events.append("store")
        return original_locked_store(*args, **kwargs)

    def observe_locked_user(*args, **kwargs):
        events.append("owner")
        return original_locked_user(*args, **kwargs)

    monkeypatch.setattr(
        influencer_services,
        "influencer_identity_queryset",
        observe_identity_queryset,
    )
    monkeypatch.setattr(influencer_services, "_locked_store", observe_locked_store)
    monkeypatch.setattr(influencer_services, "_locked_user", observe_locked_user)

    task = _task(user, store, influencer)

    assert task.influencer_id == influencer.pk
    assert OutreachTarget.objects.filter(task=task, influencer=influencer).exists()
    assert events[:3] == ["identity_group", "store", "owner"]


def test_task_creation_without_influencer_locks_store_before_owner(monkeypatch):
    _, user, store, _ = _records("outreach-without-influencer-lock-order")
    events = []
    original_locked_store = influencer_services._locked_store
    original_locked_user = influencer_services._locked_user

    def observe_locked_store(*args, **kwargs):
        events.append("store")
        return original_locked_store(*args, **kwargs)

    def observe_locked_user(*args, **kwargs):
        events.append("owner")
        return original_locked_user(*args, **kwargs)

    monkeypatch.setattr(influencer_services, "_locked_store", observe_locked_store)
    monkeypatch.setattr(influencer_services, "_locked_user", observe_locked_user)

    task = _task(user, store)

    assert task.influencer_id is None
    assert events[:2] == ["store", "owner"]


@pytest.mark.parametrize("restore", [False, True])
def test_sample_mutation_locks_identity_group_before_fulfillment(monkeypatch, restore):
    _, user, store, influencer = _records(
        "sample-lock-order-restore" if restore else "sample-lock-order-edit"
    )
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key=f"sample-lock-order-{restore}",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "external_product_id": "SAMPLE-LOCK-ORDER-PRODUCT",
        },
        item_payloads=[],
    )
    if restore:
        fulfillment = influencer_services.soft_delete_sample_fulfillment(
            user=user,
            fulfillment=fulfillment,
            expected_version=fulfillment.version,
        )

    events = []
    original_tenant_influencer = influencer_services._tenant_influencer
    original_identity_queryset = influencer_services.influencer_identity_queryset
    original_locked_sample = influencer_services._locked_sample_fulfillment

    def observe_tenant_influencer(*args, **kwargs):
        assert kwargs["for_update"] is False
        events.append("influencer_read")
        return original_tenant_influencer(*args, **kwargs)

    def observe_identity_queryset(*args, **kwargs):
        assert kwargs["for_update"] is True
        events.append("identity_group")
        return original_identity_queryset(*args, **kwargs)

    def observe_locked_sample(*args, **kwargs):
        events.append("sample")
        return original_locked_sample(*args, **kwargs)

    monkeypatch.setattr(influencer_services, "_tenant_influencer", observe_tenant_influencer)
    monkeypatch.setattr(
        influencer_services,
        "influencer_identity_queryset",
        observe_identity_queryset,
    )
    monkeypatch.setattr(
        influencer_services,
        "_locked_sample_fulfillment",
        observe_locked_sample,
    )

    if restore:
        result = influencer_services.restore_sample_fulfillment(
            user=user,
            fulfillment=fulfillment,
            expected_version=fulfillment.version,
        )
    else:
        result = influencer_services.update_sample_fulfillment(
            user=user,
            fulfillment=fulfillment,
            expected_version=fulfillment.version,
            validated_data={"notes": "identity-first edit"},
        )

    assert result.pk == fulfillment.pk
    assert events == ["influencer_read", "identity_group", "sample"]


@pytest.mark.parametrize("mutation", ["status", "influencer"])
def test_sample_edit_revalidates_status_and_influencer_after_identity_lock(monkeypatch, mutation):
    tenant, user, store, influencer = _records(f"sample-revalidate-{mutation}")
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key=f"sample-revalidate-{mutation}",
        validated_data={
            "influencer": influencer,
            "store": store,
            "link_type": "YYJL",
            "external_product_id": "SAMPLE-REVALIDATE-PRODUCT",
        },
        item_payloads=[],
    )
    other_influencer = Influencer.objects.create(
        tenant=tenant,
        code=f"sample-revalidate-{mutation}-other",
        name="Other creator",
        platform="TikTok",
        handle="other.creator",
    )
    original_locked_sample = influencer_services._locked_sample_fulfillment

    def return_stale_sample(*args, **kwargs):
        locked = original_locked_sample(*args, **kwargs)
        if mutation == "status":
            locked.status = SampleFulfillment.Status.SHIPPED
        else:
            locked.influencer_id = other_influencer.pk
        return locked

    monkeypatch.setattr(
        influencer_services,
        "_locked_sample_fulfillment",
        return_stale_sample,
    )

    with pytest.raises(ValidationError) as exc_info:
        influencer_services.update_sample_fulfillment(
            user=user,
            fulfillment=fulfillment,
            expected_version=fulfillment.version,
            validated_data={"notes": "must not overwrite stale state"},
        )

    assert exc_info.value.get_codes() == {mutation: "conflict"}
    fulfillment.refresh_from_db()
    assert fulfillment.notes == ""
    assert fulfillment.status == SampleFulfillment.Status.PENDING
    assert fulfillment.influencer_id == influencer.pk


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


def test_fulfillment_options_use_manage_permission_tenant_scope_and_minimal_task_fields(monkeypatch):
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

    def reject_influencer_scan(*args, **kwargs):
        raise AssertionError("Core outreach task options must not scan influencers or blacklist state.")

    monkeypatch.setattr(influencer_views, "_influencer_candidates", reject_influencer_scan)
    edit_options_response = client.get(
        "/api/internal/influencers/outreach-task-options/?include_influencers=false"
    )
    assert edit_options_response.status_code == 200
    edit_options_payload = edit_options_response.json()["data"]
    assert "influencers" not in edit_options_payload
    assert {item["id"] for item in edit_options_payload["stores"]} == {store.id}
    assert {item["id"] for item in edit_options_payload["bd_users"]} == {user.id}


def test_fulfillment_options_do_not_merge_same_handle_across_platforms():
    tenant, user, _, influencer = _records("option-platform-scope")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    influencer.handle = "shared.creator"
    influencer.save(update_fields=["handle"])
    instagram = Influencer.objects.create(
        tenant=tenant,
        code="instagram-shared-creator",
        name="Instagram creator",
        handle="shared.creator",
        platform="Instagram",
    )
    client = APIClient()
    client.force_authenticate(user)

    response = client.get("/api/internal/influencers/sample-fulfillment-options/")

    assert response.status_code == 200
    candidate_ids = {item["id"] for item in response.json()["data"]["influencers"]}
    assert {influencer.id, instagram.id}.issubset(candidate_ids)


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


def test_blacklist_endpoint_rejects_string_boolean_values():
    tenant, user, _, influencer = _records("blacklist-boolean")
    role = Role.objects.get(tenant=tenant, code="bd")
    _grant_all_scope(role, "influencers.manage")
    _grant_all_scope(role, "influencers.fulfillment.manage")
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        f"/api/internal/influencers/{influencer.pk}/blacklist/",
        {"is_blacklisted": "false"},
        format="json",
    )

    assert response.status_code == 400
    assert not InfluencerRestriction.objects.filter(
        tenant=tenant,
        influencer=influencer,
    ).exists()


@pytest.mark.django_db(transaction=True)
def test_blacklist_recomputes_related_tasks_inside_a_new_transaction(monkeypatch):
    _, user, store, influencer = _records("blacklist-on-commit")
    task = _task(user, store, influencer)
    create_sample_fulfillment(
        user=user,
        request_key="blacklist-on-commit-sample-key",
        validated_data={
            "outreach_task": task,
            "influencer": influencer,
        },
        item_payloads=[],
    )

    observed_atomic_states = []
    observed_savepoint_states = []
    locked_task = influencer_services._locked_task

    def observe_locked_task(*args, **kwargs):
        observed_atomic_states.append(connection.in_atomic_block)
        observed_savepoint_states.append(bool(connection.savepoint_ids))
        return locked_task(*args, **kwargs)

    monkeypatch.setattr(influencer_services, "_locked_task", observe_locked_task)
    set_influencer_blacklist(
        user=user,
        influencer=influencer,
        blacklisted=True,
        reason="on-commit task recompute",
    )

    assert observed_atomic_states == [True]
    assert observed_savepoint_states == [True]


@pytest.mark.django_db(transaction=True)
def test_blacklist_rolls_back_every_change_when_task_recompute_fails(monkeypatch):
    tenant, user, store, influencer = _records("blacklist-rollback")
    task = _task(user, store, influencer)
    QuerySet.update(OutreachTask.objects.filter(pk=task.pk), target_count=2)
    task.refresh_from_db()
    fulfillment, _ = create_sample_fulfillment(
        user=user,
        request_key="blacklist-rollback-sample-key",
        validated_data={
            "outreach_task": task,
            "influencer": influencer,
        },
        item_payloads=[],
    )
    completed_influencer = Influencer.objects.create(
        tenant=tenant,
        code="blacklist-rollback-completed",
        name="Completed creator",
        platform="TikTok",
        handle="blacklist.rollback.completed",
    )
    QuerySet.update(OutreachTask.objects.filter(pk=task.pk), influencer=None)
    task.refresh_from_db()
    completed_sample = SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no="blacklist-rollback-completed-sample",
        request_key="blacklist-rollback-completed-key",
        request_hash="blacklist-rollback-completed-hash",
        link_type="YYJL",
        outreach_task=task,
        influencer=completed_influencer,
        store=store,
        owner=user,
    )
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=completed_sample.pk),
        status=SampleFulfillment.Status.PUBLISHED,
    )
    original_updated_at = influencer.updated_at
    original_task_status = task.status
    original_task_version = task.version
    recompute = influencer_services.recompute_outreach_task_completion
    recompute_mutated_task = []

    def fail_recompute(*args, **kwargs):
        mutated = recompute(*args, **kwargs)
        recompute_mutated_task.append(
            (mutated.status, mutated.version, mutated.finalized_at is not None)
        )
        assert mutated.status == OutreachTask.Status.COMPLETED
        assert mutated.version == original_task_version + 1
        raise RuntimeError("injected recompute failure")

    monkeypatch.setattr(influencer_services, "recompute_outreach_task_completion", fail_recompute)

    with pytest.raises(RuntimeError, match="injected recompute failure"):
        set_influencer_blacklist(
            user=user,
            influencer=influencer,
            blacklisted=True,
            reason="rollback all changes",
        )

    influencer.refresh_from_db()
    fulfillment.refresh_from_db()
    task.refresh_from_db()
    assert influencer.updated_at == original_updated_at
    assert fulfillment.status == SampleFulfillment.Status.PENDING
    assert task.status == original_task_status
    assert task.version == original_task_version
    assert recompute_mutated_task == [(OutreachTask.Status.COMPLETED, original_task_version + 1, True)]
    assert not InfluencerRestriction.objects.filter(tenant=tenant, influencer=influencer).exists()
    assert not InfluencerRestrictEvent.objects.filter(tenant=tenant, influencer=influencer).exists()
    assert not OperationLog.objects.filter(
        tenant=tenant,
        action="outreach_sample_auto_complete",
        object_type="outreach_task",
        object_id=str(task.pk),
    ).exists()


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


def test_canonical_handle_migration_normalizes_tiktok_records_and_snapshots():
    tenant, user, store, influencer = _records("canonical-migration")
    table = connection.ops.quote_name(Influencer._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET handle = %s WHERE id = %s",
            [" @MHAINE_94 ", influencer.pk],
        )
    snapshot = BdSampleAttributionSnapshot.objects.create(
        tenant=tenant,
        fulfillment=SampleFulfillment.objects.create(
            tenant=tenant,
            fulfillment_no="migration-sample",
            request_key="migration-sample-request",
            request_hash="migration-sample-hash",
            link_type="YYJL",
            influencer=influencer,
            store=store,
            owner=user,
        ),
        owner=user,
        influencer=influencer,
        store=store,
        creator_username=" @MHAINE_94 ",
        shop_abbr=store.code,
        site="PH",
        product_id="migration-product",
        product_name="Migration product",
        sku_id="migration-sku",
        sampled_at=timezone.now(),
        sample_status=SampleFulfillment.Status.PENDING,
        currency="PHP",
        pricing_status="pending",
    )
    migration = importlib.import_module(
        "apps.influencers.migrations.0013_canonical_tiktok_handle"
    )

    migration.normalize_existing_tiktok_identities(
        importlib.import_module("django.apps").apps,
        None,
    )

    influencer.refresh_from_db()
    snapshot.refresh_from_db()
    assert influencer.handle == "mhaine_94"
    assert snapshot.creator_username == "mhaine_94"


def test_canonical_handle_migration_rejects_unapply_before_field_ddl(monkeypatch):
    migration_module = importlib.import_module(
        "apps.influencers.migrations.0013_canonical_tiktok_handle"
    )
    migration = migration_module.Migration(
        "0013_canonical_tiktok_handle",
        "influencers",
    )
    operation = migration.operations[0]
    backwards_calls = []
    for alter_field in migration.operations[1:]:
        monkeypatch.setattr(
            alter_field,
            "database_backwards",
            lambda *args, field_name=alter_field.name, **kwargs: backwards_calls.append(
                field_name
            ),
        )
    schema_editor = SimpleNamespace(
        atomic_migration=True,
        connection=SimpleNamespace(alias="default"),
    )

    assert migration_module._normalize_tiktok_username(None) == ""
    assert operation.code is migration_module.normalize_existing_tiktok_identities
    assert operation.reverse_code is None
    assert operation.reversible is False
    assert [operation.name for operation in migration.operations[1:]] == [
        "handle",
        "creator_username",
    ]
    with pytest.raises(IrreversibleError, match="is not reversible"):
        migration.unapply(ProjectState(), schema_editor)
    assert backwards_calls == []


def test_canonical_handle_migration_does_not_guess_identity_from_code_or_name():
    tenant, user, store, influencer = _records("canonical-migration-empty")
    influencer.handle = ""
    influencer.code = "looks.like.a.handle"
    influencer.name = "also.looks.valid"
    influencer.save(update_fields=["handle", "code", "name"])
    fulfillment = SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no="migration-empty-sample",
        request_key="migration-empty-request",
        request_hash="migration-empty-hash",
        link_type="YYJL",
        influencer=influencer,
        store=store,
        owner=user,
    )
    snapshot = BdSampleAttributionSnapshot.objects.create(
        tenant=tenant,
        fulfillment=fulfillment,
        owner=user,
        influencer=influencer,
        store=store,
        creator_username="looks.like.a.handle",
        shop_abbr=store.code,
        site="PH",
        product_id="migration-empty-product",
        product_name="Migration product",
        sku_id="migration-empty-sku",
        sampled_at=timezone.now(),
        sample_status=SampleFulfillment.Status.PENDING,
        currency="PHP",
        pricing_status="pending",
    )
    migration = importlib.import_module(
        "apps.influencers.migrations.0013_canonical_tiktok_handle"
    )

    migration.normalize_existing_tiktok_identities(
        importlib.import_module("django.apps").apps,
        None,
    )

    snapshot.refresh_from_db()
    assert snapshot.creator_username == "looks.like.a.handle"


@pytest.mark.django_db(transaction=True)
def test_canonical_handle_migration_propagates_blacklist_across_normalized_aliases():
    tenant, user, store, clean = _records("canonical-blacklist-alias")
    clean.handle = "duplicate.creator"
    clean.save(update_fields=["handle"])
    alias = Influencer.objects.create(
        tenant=tenant,
        code="canonical-blacklist-fullwidth",
        name="Auxiliary display name",
        handle="duplicate.creator",
        platform="TikTok",
    )
    table = connection.ops.quote_name(Influencer._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET handle = %s WHERE id = %s",
            ["＠ＤＵＰＬＩＣＡＴＥ．ＣＲＥＡＴＯＲ", alias.pk],
        )
    restriction = InfluencerRestriction.objects.create(
        tenant=tenant,
        influencer=clean,
        is_blacklisted=True,
        reason="legacy restriction",
        created_by=user,
    )
    fulfillment = SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no="canonical-blacklist-sample",
        request_key="canonical-blacklist-request",
        request_hash="canonical-blacklist-hash",
        link_type="YYJL",
        influencer=alias,
        store=store,
        owner=user,
    )
    item = SampleItem.objects.create(
        tenant=tenant,
        fulfillment=fulfillment,
        site_code="PH",
        requested_sku="canonical-blacklist-sku",
        quantity=2,
        unit_cost=Decimal("4.0000"),
        cost_amount=Decimal("8.0000"),
    )
    QuerySet.update(
        InfluencerRestriction.objects.filter(pk=restriction.pk),
        updated_at=fulfillment.created_at - timedelta(days=1),
    )
    original_updated_at = fulfillment.created_at + timedelta(days=1)
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk),
        updated_at=original_updated_at,
    )
    fulfillment_table = connection.ops.quote_name(SampleFulfillment._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {fulfillment_table} SET status = %s WHERE id = %s",
            [SampleFulfillment.Status.SHIPPED, fulfillment.pk],
        )
    migration = importlib.import_module(
        "apps.influencers.migrations.0013_canonical_tiktok_handle"
    )

    migration.normalize_existing_tiktok_identities(
        importlib.import_module("django.apps").apps,
        None,
    )

    alias.refresh_from_db()
    fulfillment.refresh_from_db()
    item.refresh_from_db()
    assert alias.handle == "duplicate.creator"
    assert InfluencerRestriction.objects.filter(
        tenant=tenant,
        influencer=alias,
        is_blacklisted=True,
    ).exists()
    assert fulfillment.finalized_at >= fulfillment.created_at
    assert fulfillment.updated_at >= fulfillment.created_at
    assert fulfillment.finalized_at == fulfillment.created_at
    assert fulfillment.updated_at == original_updated_at
    assert item.unit_cost == Decimal("4.0000")
    assert item.cost_amount == Decimal("8.0000")
    assert fulfillment.status == SampleFulfillment.Status.BLACKLISTED
    assert fulfillment.version == 2
    assert fulfillment.status_events.filter(
        from_status=SampleFulfillment.Status.SHIPPED,
        to_status=SampleFulfillment.Status.BLACKLISTED,
        actor=user,
        reason="legacy restriction",
    ).exists()


def test_canonical_handle_migration_normalizes_fullwidth_handle_and_snapshot():
    tenant, user, store, influencer = _records("canonical-migration-invalid")
    table = connection.ops.quote_name(Influencer._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET handle = %s WHERE id = %s",
            ["＠ＭＨＡＩＮＥ＿９４", influencer.pk],
        )
    fulfillment = SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no="migration-invalid-sample",
        request_key="migration-invalid-request",
        request_hash="migration-invalid-hash",
        link_type="YYJL",
        influencer=influencer,
        store=store,
        owner=user,
    )
    snapshot = BdSampleAttributionSnapshot.objects.create(
        tenant=tenant,
        fulfillment=fulfillment,
        owner=user,
        influencer=influencer,
        store=store,
        creator_username="＠ＭＨＡＩＮＥ＿９４",
        shop_abbr=store.code,
        site="PH",
        product_id="migration-invalid-product",
        product_name="Migration product",
        sku_id="migration-invalid-sku",
        sampled_at=timezone.now(),
        sample_status=SampleFulfillment.Status.PENDING,
        currency="PHP",
        pricing_status="pending",
    )
    migration = importlib.import_module(
        "apps.influencers.migrations.0013_canonical_tiktok_handle"
    )

    migration.normalize_existing_tiktok_identities(
        importlib.import_module("django.apps").apps,
        None,
    )

    influencer.refresh_from_db()
    snapshot.refresh_from_db()
    assert influencer.handle == "mhaine_94"
    assert snapshot.creator_username == "mhaine_94"


def test_canonical_handle_migration_clears_invalid_handle_and_snapshot():
    tenant, user, store, influencer = _records("canonical-migration-invalid-display")
    table = connection.ops.quote_name(Influencer._meta.db_table)
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET handle = %s WHERE id = %s",
            ["Legacy Display Name", influencer.pk],
        )
    fulfillment = SampleFulfillment.objects.create(
        tenant=tenant,
        fulfillment_no="migration-invalid-display-sample",
        request_key="migration-invalid-display-request",
        request_hash="migration-invalid-display-hash",
        link_type="YYJL",
        influencer=influencer,
        store=store,
        owner=user,
    )
    snapshot = BdSampleAttributionSnapshot.objects.create(
        tenant=tenant,
        fulfillment=fulfillment,
        owner=user,
        influencer=influencer,
        store=store,
        creator_username="Legacy Display Name",
        shop_abbr=store.code,
        site="PH",
        product_id="migration-invalid-display-product",
        product_name="Migration product",
        sku_id="migration-invalid-display-sku",
        sampled_at=timezone.now(),
        sample_status=SampleFulfillment.Status.PENDING,
        currency="PHP",
        pricing_status="pending",
    )
    migration = importlib.import_module(
        "apps.influencers.migrations.0013_canonical_tiktok_handle"
    )

    migration.normalize_existing_tiktok_identities(
        importlib.import_module("django.apps").apps,
        None,
    )

    influencer.refresh_from_db()
    snapshot.refresh_from_db()
    assert influencer.handle == ""
    assert snapshot.creator_username == ""


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


def test_outreach_manager_search_normalizes_tiktok_handle_alias():
    _, user, _, influencer = _records("outreach-resolve-normalized")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.outreach.manage")
    influencer.handle = "mhaine_94"
    influencer.save(update_fields=["handle"])
    client = APIClient()
    client.force_authenticate(user)

    response = client.get(
        "/api/internal/influencers/resolve/",
        {"q": " ＠ＭＨＡＩＮＥ＿９４ "},
    )

    assert response.status_code == 200
    assert response.json()["data"]["query"] == "mhaine_94"
    assert response.json()["data"]["candidates"][0]["id"] == influencer.id


def test_candidate_resolver_fills_limit_after_normalized_handle_dedup():
    tenant, _, _, first = _records("resolve-candidate-dedup")
    duplicates = []
    for index in range(8):
        duplicates.append(
            Influencer.objects.create(
                tenant=tenant,
                code=f"candidate-dedup-duplicate-{index}",
                name=f"Duplicate creator {index}",
                handle="duplicate.creator",
                platform="TikTok",
            )
        )
    target = Influencer.objects.create(
        tenant=tenant,
        code="candidate-dedup-target",
        name="Unique candidate",
        handle="unique.creator",
        platform="TikTok",
    )
    blacklist_subquery = influencer_models.active_influencer_restriction_subquery(tenant)
    queryset = Influencer.objects.filter(
        tenant=tenant,
        platform__iexact="TikTok",
    ).annotate(is_blacklisted=Exists(blacklist_subquery))

    rows = influencer_views._influencer_candidates(
        queryset,
        limit=3,
        include_handle=True,
    )

    assert [row["id"] for row in rows] == [first.id, duplicates[0].id, target.id]


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


def test_account_resolve_matches_fullwidth_alias_after_nfkc_normalization():
    tenant, user, _, _ = _records("resolve-legacy-handle")
    role = user.user_roles.get().role
    _grant_all_scope(role, "influencers.fulfillment.manage")
    Influencer.objects.create(
        tenant=tenant,
        code="legacy-clean",
        name="Clean auxiliary name",
        handle="legacy.creator",
        platform="tiktok",
    )
    count_before = Influencer.objects.filter(tenant=tenant).count()
    client = APIClient()
    client.force_authenticate(user)

    response = client.post(
        "/api/internal/influencers/resolve/",
        {"handle": " ＠Ｌｅｇａｃｙ．Ｃｒｅａｔｏｒ "},
        format="json",
    )

    assert response.status_code == 200, response.data
    assert response.json()["data"]["handle"] == "legacy.creator"
    assert Influencer.objects.filter(tenant=tenant).count() == count_before


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
        {"handle": " @MHAINE_94 "},
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
        handle="LEGACY.TARGET",
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
