from datetime import UTC, date, datetime
import pytest
from django.core.exceptions import ValidationError

from apps.accounts.models import CustomUser
from apps.commerce.models import SalesOrder
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.sales_management.nine_snapshot_capture import capture_store
from apps.sales_management.snapshot_models import SalesNineSnapshot
from apps.tenants.models import Tenant


def make_store(suffix, zone="Asia/Manila"):
    tenant = Tenant.objects.create(name=suffix, code=suffix)
    platform = PlatformMaster.objects.create(
        tenant=tenant, code=f"platform-{suffix}", name="Shopee", platform_type="shopee"
    )
    store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code=f"store-{suffix}", name=suffix,
        country_code="PH", currency="PHP", timezone=zone,
    )
    user = CustomUser.objects.create_user(username=f"user-{suffix}", tenant=tenant, user_type="internal")
    config = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform="shopee", account_alias=f"auth-{suffix}", created_by=user
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=config, resource_type="sales_order")
    run = SyncRun.objects.create(
        tenant=tenant, sync_job=job, run_id=f"run-{suffix}", idempotency_key=f"key-{suffix}"
    )
    return tenant, platform, store, config, run


def add_order(scope, ext_id, created_at, amount="10.0000", currency="PHP", status="completed"):
    tenant, platform, store, config, run = scope
    return SalesOrder.objects.create(
        tenant=tenant, platform=platform, store=store, authorization=config, source_run=run,
        external_order_id=ext_id, region="PH", raw_status=status.upper(), normalized_status=status,
        status_mapping_version="1.0", created_at_utc=created_at, updated_at_utc=created_at,
        business_date=created_at.date(), currency=currency, order_total_amount=amount,
        payload_hash=(str(len(ext_id)) * 64)[:64],
    )


@pytest.mark.django_db
def test_store_local_date_window_and_half_open_09_boundary():
    scope = make_store("nine-boundary")
    tenant, _, store, *_ = scope
    add_order(scope, "midnight", datetime(2026, 10, 23, 16, 0, tzinfo=UTC))  # Oct 24 local midnight
    add_order(scope, "before09", datetime(2026, 10, 24, 0, 59, 59, tzinfo=UTC), "2.0000")
    add_order(scope, "at09", datetime(2026, 10, 24, 1, 0, tzinfo=UTC), "100.0000")
    add_order(scope, "cancelled", datetime(2026, 10, 24, 0, 30, tzinfo=UTC), "500.0000", status="cancelled")

    snapshot, created = capture_store(store, datetime(2026, 10, 24, 1, 2, tzinfo=UTC))

    assert created is True
    assert snapshot.tenant_id == tenant.pk
    assert snapshot.business_date == date(2026, 10, 24)
    assert snapshot.timezone_name == "Asia/Manila"
    assert snapshot.target_at == datetime(2026, 10, 24, 1, 0, tzinfo=UTC)
    assert snapshot.groups == [{"currency": "PHP", "sales_amount": "12.0000", "order_count": 2}]
    assert snapshot.integrity_status == "unverified"


@pytest.mark.django_db
@pytest.mark.parametrize("instant", [
    datetime(2026, 10, 24, 0, 59, 59, tzinfo=UTC),
    datetime(2026, 10, 24, 1, 5, tzinfo=UTC),
])
def test_capture_only_within_09_00_to_09_05_window(instant):
    store = make_store("nine-window-" + str(instant.minute) + str(instant.second))[2]
    assert capture_store(store, instant) == (None, False)


@pytest.mark.django_db
def test_immutable_retry_returns_original_snapshot_without_replacing_values():
    scope = make_store("nine-retry")
    store = scope[2]
    first, created = capture_store(store, datetime(2026, 10, 24, 1, 1, tzinfo=UTC))
    add_order(scope, "late-arrival", datetime(2026, 10, 24, 0, 30, tzinfo=UTC), "99.0000")

    repeated, created_again = capture_store(store, datetime(2026, 10, 24, 1, 3, tzinfo=UTC))

    assert created and not created_again
    assert repeated.pk == first.pk
    assert repeated.groups == []
    with pytest.raises(ValidationError, match="immutable"):
        repeated.save()


@pytest.mark.django_db
@pytest.mark.parametrize("zone", ["", "Mars/Olympus_Mons"])
def test_missing_or_unknown_timezone_is_safely_skipped(zone):
    store = make_store("nine-bad-zone-" + str(bool(zone)), zone=zone)[2]
    assert capture_store(store, datetime(2026, 10, 24, 1, 1, tzinfo=UTC)) == (None, False)


@pytest.mark.django_db
def test_capture_is_scoped_to_store_and_tenant_and_keeps_currency_groups():
    scope_a = make_store("nine-tenant-a")
    scope_b = make_store("nine-tenant-b")
    instant = datetime(2026, 10, 24, 1, 1, tzinfo=UTC)
    add_order(scope_a, "only-a", datetime(2026, 10, 24, 0, 15, tzinfo=UTC), "1.2500", "PHP")
    add_order(scope_b, "only-b", datetime(2026, 10, 24, 0, 15, tzinfo=UTC), "9.0000", "USD")

    snapshot_a, _ = capture_store(scope_a[2], instant)
    snapshot_b, _ = capture_store(scope_b[2], instant)

    assert snapshot_a.tenant_id != snapshot_b.tenant_id
    assert snapshot_a.groups == [{"currency": "PHP", "sales_amount": "1.2500", "order_count": 1}]
    assert snapshot_b.groups == [{"currency": "USD", "sales_amount": "9.0000", "order_count": 1}]
    assert SalesNineSnapshot.objects.filter(tenant=scope_a[0], store=scope_a[2]).count() == 1


@pytest.mark.django_db
def test_empty_observed_snapshot_is_saved_without_fake_zero_groups():
    scope = make_store("nine-empty")
    saved, created = capture_store(scope[2], datetime(2026, 10, 24, 1, 1, tzinfo=UTC))
    assert created is True
    assert saved.groups == []
    assert saved.integrity_status == "unverified"
