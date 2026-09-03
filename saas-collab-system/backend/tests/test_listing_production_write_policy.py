from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.test import override_settings
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from apps.accounts.models import CustomUser
from apps.integrations import production_settings
from apps.integrations.production_settings import (
    assert_listing_production_allowed,
    get_listing_write_policy,
    validate_runtime_config,
)
from apps.listings import services as listing_services
from apps.listings import permissions as listing_permissions
from apps.listings.models import ListingProfile, ListingTask, ListingTaskStepLog, ListingVariant
from apps.listings.services import queue_listing_publication
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _runtime_config(**listing_overrides):
    listing_write = {
        "mode": "controlled",
        "emergency_stop": False,
        "require_batch_approval": True,
        "allowed_platforms": ["shopee"],
        "allowed_actions": ["create", "update", "pause"],
        "allowed_store_ids": [101],
        "max_batch_size": 20,
    }
    listing_write.update(listing_overrides)
    return {
        "network": {
            "mode": "approved-live-test",
            "security_approved": True,
            "allowed_hosts": ["partner.shopeemobile.com"],
        },
        "custody": {
            "backend": "http",
            "service_url": "https://custody.example.test",
            "service_host": "custody.example.test",
        },
        "platforms": {"shopee": {"contract_approved": True}},
        "listing_write": listing_write,
    }


def test_listing_write_defaults_fail_closed():
    policy = get_listing_write_policy({})
    assert policy == {
        "mode": "disabled",
        "emergency_stop": True,
        "require_batch_approval": True,
        "allowed_platforms": [],
        "allowed_actions": [],
        "allowed_store_ids": [],
        "max_batch_size": 20,
    }
    with pytest.raises(DjangoValidationError, match="controlled"):
        assert_listing_production_allowed(
            platform="shopee",
            action="create",
            store_id=101,
            confirm_production=True,
            config={},
        )


def test_production_publish_permission_does_not_fallback_to_profile_permission(monkeypatch):
    user = SimpleNamespace(is_authenticated=True, is_active=True, user_type="internal")
    factory = APIRequestFactory()
    request = APIView().initialize_request(
        factory.post("/api/internal/listings/profiles/1/publish/", {"execution_mode": "production"}, format="json")
    )
    request.user = user
    monkeypatch.setattr(
        listing_permissions,
        "check_user_permission",
        lambda _user, code: code == "listings.profile.publish",
    )
    monkeypatch.setattr(listing_permissions, "get_permission_data_scopes", lambda _user, _code: [{"scope_type": "tenant"}])
    assert listing_permissions.CanPublishListingEndpoint().has_permission(request, None) is False

    dry_run = APIView().initialize_request(
        factory.post("/api/internal/listings/profiles/1/publish/", {"execution_mode": "dry_run"}, format="json")
    )
    dry_run.user = user
    assert listing_permissions.CanPublishListingEndpoint().has_permission(dry_run, None) is True


@pytest.mark.parametrize(
    "listing_overrides, message",
    [
        ({"unknown": True}, "unsupported fields"),
        ({"mode": "live"}, "disabled or controlled"),
        ({"allowed_platforms": ["amazon"]}, "unsupported value"),
        ({"allowed_actions": ["delete"]}, "unsupported value"),
        ({"allowed_store_ids": [0]}, "positive integer"),
        ({"max_batch_size": 101}, "between 1 and 100"),
        ({"mode": "controlled", "require_batch_approval": False}, "per-batch approval"),
    ],
)
def test_listing_write_schema_rejects_unsafe_policy_fields(listing_overrides, message):
    with pytest.raises(DjangoValidationError, match=message):
        validate_runtime_config({"listing_write": listing_overrides})


@override_settings(DEBUG=False)
def test_controlled_policy_requires_all_gates_and_returns_queue_only_contract(monkeypatch):
    monkeypatch.setattr("apps.integrations.capability.approved_custody_configured", lambda: True)
    result = assert_listing_production_allowed(
        platform="SHOPEE",
        action="CREATE",
        store_id=101,
        batch_size=2,
        confirm_production=True,
        config=_runtime_config(),
    )
    assert result["platform"] == "shopee"
    assert result["action"] == "create"
    assert result["external_platform_call"] is False

    for overrides, message in (
        ({"emergency_stop": True}, "emergency stop"),
        ({"allowed_platforms": []}, "platform allowlist"),
        ({"allowed_actions": ["update"]}, "action allowlist"),
        ({"allowed_store_ids": []}, "store allowlist"),
        ({"max_batch_size": 1}, "batch exceeds"),
    ):
        with pytest.raises(DjangoValidationError, match=message):
            assert_listing_production_allowed(
                platform="shopee",
                action="create",
                store_id=101,
                batch_size=2,
                confirm_production=True,
                config=_runtime_config(**overrides),
            )

    with pytest.raises(DjangoValidationError, match="explicit confirmation"):
        assert_listing_production_allowed(
            platform="shopee",
            action="create",
            store_id=101,
            confirm_production=False,
            config=_runtime_config(),
        )


@override_settings(DEBUG=False)
def test_production_queue_uses_platform_type_and_keeps_external_call_false(monkeypatch):
    tenant = Tenant.objects.create(name="Listing policy", code="listing-policy")
    actor = CustomUser.objects.create_user(
        username="listing-policy-actor",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    approver = CustomUser.objects.create_user(
        username="listing-policy-approver",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant,
        code="shopee-G",
        name="Shopee",
        platform_type="shopee",
    )
    store = StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code="store-G",
        name="SG",
        country_code="SG",
        currency="SGD",
    )
    spu = ProductSPU.objects.create(
        tenant=tenant,
        spu_code="SPU-POLICY",
        product_name="Policy bag",
    )
    sku = ProductSKU.objects.create(
        tenant=tenant,
        spu=spu,
        sku_code="SKU-POLICY",
        purchase_price=Decimal("5.00"),
    )
    profile = ListingProfile.objects.create(
        tenant=tenant,
        profile_no="POLICY-1",
        product=spu,
        store=store,
        title="Policy bag",
        currency="SGD",
        price=Decimal("19.00"),
        media=["https://example.invalid/policy.jpg"],
        status=ListingProfile.Status.APPROVED,
        approved_by=approver,
        created_by=actor,
    )
    ListingVariant.objects.create(profile=profile, sku=sku, seller_sku=sku.sku_code, price=Decimal("19.00"))
    monkeypatch.setattr(
        production_settings,
        "runtime_snapshot",
        lambda: {"valid": True, "config": _runtime_config(allowed_store_ids=[store.id])},
    )
    monkeypatch.setattr("apps.integrations.capability.approved_custody_configured", lambda: True)
    job, replayed = queue_listing_publication(
        profile_id=profile.id,
        actor=actor,
        idempotency_key="listing-production-policy-1",
        action="create",
        execution_mode="production",
        execution_channel="api",
        confirm_production=True,
    )
    assert replayed is False
    assert job.execution_mode == "production"
    assert job.execution_channel == "api"
    step = ListingTaskStepLog.objects.get(task__publication_job=job, step_name="queued")
    assert step.detail["boundary"] == "queue_only"
    assert step.detail["external_platform_call"] is False
    assert step.detail["production_policy"]["platform"] == "shopee"
    assert step.detail["production_policy"]["store_id"] == store.id


def test_production_queue_requires_different_content_approver_and_rechecks_replay_policy(monkeypatch):
    tenant = Tenant.objects.create(name="Listing replay policy", code="listing-replay-policy")
    actor = CustomUser.objects.create_user(
        username="listing-replay-actor",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    approver = CustomUser.objects.create_user(
        username="listing-replay-approver",
        tenant=tenant,
        user_type=CustomUser.UserType.INTERNAL,
    )
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee-R", name="Shopee", platform_type="shopee")
    store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="store-R", name="SG", country_code="SG", currency="SGD")
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="SPU-REPLAY", product_name="Replay bag")
    sku = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="SKU-REPLAY", purchase_price=Decimal("5.00"))
    profile = ListingProfile.objects.create(
        tenant=tenant,
        profile_no="REPLAY-1",
        product=spu,
        store=store,
        title="Replay bag",
        currency="SGD",
        price=Decimal("19.00"),
        media=["https://example.invalid/replay.jpg"],
        status=ListingProfile.Status.APPROVED,
        approved_by=approver,
        created_by=actor,
    )
    ListingVariant.objects.create(profile=profile, sku=sku, seller_sku=sku.sku_code, price=Decimal("19.00"))
    allowed = lambda **kwargs: {"platform": "shopee", "action": "create", "store_id": store.id, "batch_size": 1}
    monkeypatch.setattr(listing_services, "assert_listing_production_allowed", allowed)
    job, _ = queue_listing_publication(
        profile_id=profile.id,
        actor=actor,
        idempotency_key="listing-replay-policy-1",
        execution_mode="production",
        confirm_production=True,
    )
    assert ListingTask.objects.filter(publication_job=job).exists()

    def stopped(**kwargs):
        raise DRFValidationError({"listing_write.emergency_stop": "listing production is blocked by the emergency stop"})

    monkeypatch.setattr(listing_services, "assert_listing_production_allowed", stopped)
    with pytest.raises(DRFValidationError, match="emergency stop"):
        queue_listing_publication(
            profile_id=profile.id,
            actor=actor,
            idempotency_key="listing-replay-policy-1",
            execution_mode="production",
            confirm_production=True,
        )

    profile.approved_by = actor
    profile.status = ListingProfile.Status.APPROVED
    profile.save(update_fields=["approved_by", "status"])
    monkeypatch.setattr(listing_services, "assert_listing_production_allowed", allowed)
    with pytest.raises(DRFValidationError) as exc_info:
        queue_listing_publication(
            profile_id=profile.id,
            actor=actor,
            idempotency_key="listing-production-policy-2",
            execution_mode="production",
            confirm_production=True,
        )
    assert "same profile" in str(exc_info.value).lower()
