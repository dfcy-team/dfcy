from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

import pytest
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.commerce.models import SalesOrder
from apps.integrations.models import PlatformIntegrationConfig, SyncJob, SyncRun
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.sales_management.services import upsert_normalized_order
from apps.tenants.models import Tenant
from django.utils import timezone


def _user(tenant, name):
    return CustomUser.objects.create_user(username=name, tenant=tenant, user_type=CustomUser.UserType.INTERNAL)


def _store(tenant, platform, code, currency, country, store_timezone):
    return StoreMaster.objects.create(
        tenant=tenant,
        platform=platform,
        code=code,
        name=code,
        country_code=country,
        currency=currency,
        timezone=store_timezone,
    )


def _order(tenant, store, suffix, amount, status="completed", *, local_day, quantity=2):
    user = _user(tenant, f"source-{suffix}")
    authorization = PlatformIntegrationConfig.objects.create(
        tenant=tenant, platform=store.platform.platform_type, account_alias=f"auth-{suffix}", created_by=user
    )
    job = SyncJob.objects.create(tenant=tenant, integration_config=authorization, resource_type="sales_order")
    run = SyncRun.objects.create(tenant=tenant, sync_job=job, run_id=f"run-{suffix}", idempotency_key=f"key-{suffix}")
    zone = ZoneInfo(store.timezone)
    created = datetime.combine(local_day, time(hour=12), tzinfo=zone).astimezone(UTC)
    return upsert_normalized_order(
        tenant=tenant,
        source_run=run,
        payload={
            "contract_version": "1.0",
            "store_id": store.id,
            "external_order_id": f"ORDER-{suffix}",
            "region": store.country_code,
            "raw_status": status.upper(),
            "normalized_status": status,
            "created_at_utc": created.isoformat(),
            "updated_at_utc": created.isoformat(),
            "currency": store.currency,
            "order_total_amount": str(amount),
            "lines": [{
                "external_line_id": f"LINE-{suffix}",
                "platform_product_id": f"PRODUCT-{suffix}",
                "seller_sku": f"SKU-{suffix}",
                "quantity": quantity,
                "sale_unit_price": str(amount),
                "line_total_amount": str(amount),
                "currency": store.currency,
            }],
        },
    )


def _grant(user, *, scope_type=DataScope.ScopeType.ALL, config=None):
    permission, _ = Permission.objects.get_or_create(
        code="sales_management.view",
        defaults={"name": "Sales view", "module": "sales_management", "action": "view"},
    )
    role = Role.objects.create(tenant=user.tenant, name="sales-view", code=f"sales-view-{user.id}")
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=scope_type, config=config or {})


@pytest.mark.django_db
def test_dashboard_monthly_sales_is_scoped_currency_separated_and_excludes_cancelled(monkeypatch):
    today = date(2026, 10, 2)
    first_day = date(2026, 10, 1)
    yesterday = date(2026, 9, 30)
    monkeypatch.setattr("apps.sales_management.views.timezone.localdate", lambda **_kwargs: today)
    tenant = Tenant.objects.create(name="dashboard-sales", code="dashboard-sales")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    visible_php = _store(tenant, platform, "visible-php", "PHP", "PH", "Asia/Manila")
    visible_thb = _store(tenant, platform, "visible-thb", "THB", "TH", "Asia/Bangkok")
    visible_myr = _store(tenant, platform, "visible-myr", "MYR", "MY", "Asia/Kuala_Lumpur")
    hidden = _store(tenant, platform, "hidden-php", "PHP", "PH", "Asia/Manila")
    php_baseline = _order(tenant, visible_php, "baseline-php", "7", local_day=yesterday, quantity=4)
    _order(tenant, visible_myr, "baseline-myr", "13", local_day=yesterday, quantity=2)
    php_order = _order(tenant, visible_php, "visible-php", "25.50", local_day=first_day, quantity=3)
    _order(tenant, visible_php, "visible-php-today", "12", local_day=today, quantity=1)
    thb_order = _order(tenant, visible_thb, "visible-thb", "40", local_day=today, quantity=5)
    cancelled = _order(tenant, visible_php, "cancelled", "500", status="cancelled", local_day=today)
    _order(tenant, hidden, "hidden", "900", local_day=today)

    viewer = _user(tenant, "viewer")
    StoreMaster.objects.filter(pk__in=[visible_php.pk, visible_thb.pk, visible_myr.pk, hidden.pk]).update(operator=viewer)
    _grant(viewer, scope_type=DataScope.ScopeType.CUSTOM, config={"store_ids": [str(visible_php.id), str(visible_thb.id), str(visible_myr.id)]})
    client = APIClient()
    client.force_authenticate(user=viewer)
    response = client.get("/api/internal/commerce/dashboard/monthly-sales/")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["month"] == today.strftime("%Y-%m")
    assert data["through"] == today.isoformat()
    assert data["previous_day"] == yesterday.isoformat()
    currencies = {item["currency"]: item for item in data["currencies"]}
    assert set(currencies) == {"PHP", "THB", "MYR"}
    assert currencies["PHP"]["previous"] == {"amount": "7", "quantity": 4, "ad_spend": None}
    assert currencies["PHP"]["daily"] == [
        {"date": first_day.isoformat(), "amount": "25.5", "quantity": 3, "ad_spend": None},
        {"date": today.isoformat(), "amount": "12", "quantity": 1, "ad_spend": None},
    ]
    assert currencies["THB"]["previous"] == {"amount": "0", "quantity": 0, "ad_spend": None}
    assert currencies["THB"]["daily"] == [{"date": today.isoformat(), "amount": "40", "quantity": 5, "ad_spend": None}]
    assert currencies["MYR"] == {"currency": "MYR", "previous": {"amount": "13", "quantity": 2, "ad_spend": None}, "daily": []}
    assert cancelled.normalized_status == "cancelled"
    assert php_order.store_id == visible_php.id and thb_order.store_id == visible_thb.id
    assert php_baseline.store_id == visible_php.id
    assert {row["id"] for row in data["stores"]} == {visible_php.id, visible_thb.id, visible_myr.id}
    assert data["selected_store_id"] is None

    selected = client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": visible_php.pk})
    assert selected.status_code == 200
    assert selected.json()["data"]["selected_store_id"] == visible_php.pk
    assert selected.json()["data"]["currencies"] == [currencies["PHP"]]
    assert client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": hidden.pk}).status_code == 403


@pytest.mark.django_db
def test_dashboard_monthly_sales_requires_sales_view_permission():
    tenant = Tenant.objects.create(name="dashboard-permission", code="dashboard-permission")
    user = _user(tenant, "no-sales-permission")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/internal/commerce/dashboard/monthly-sales/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_store_choices_intersect_personnel_and_permission_without_order_scan():
    from apps.sales_management.dashboard_scope import dashboard_stores

    tenant = Tenant.objects.create(name="managed-stores", code="managed-stores")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    viewer = _user(tenant, "managed-viewer")
    stores = [_store(tenant, platform, f"managed-{i}", "PHP", "PH", "Asia/Manila") for i in range(5)]
    for store, field in zip(stores, ["operator", "bd", "leader", "operator"]):
        setattr(store, field, viewer)
        store.save()
    # A second personnel match on the same store must not duplicate the option.
    stores[0].leader = viewer
    stores[0].save()
    _grant(viewer, scope_type="custom", config={"store_ids": [s.pk for s in stores[:3]] + [stores[4].pk]})
    client = APIClient()
    client.force_authenticate(user=viewer)
    response = client.get("/api/internal/commerce/dashboard/monthly-sales/")
    data = response.json()["data"]
    assert response.status_code == 200
    assert [s["id"] for s in data["stores"]] == [s.pk for s in stores[:3]]
    assert data["currencies"] == []  # Options exist even without order facts.
    for inaccessible in stores[3:]:
        assert client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": inaccessible.pk}).status_code == 403
    # Warm only request-local permission resolution. The option query touches
    # master data alone, independent of the number of historical orders.
    cache = {}
    list(dashboard_stores(viewer, "sales_management.view", cache))
    from django.db import connection
    from django.test.utils import CaptureQueriesContext
    with CaptureQueriesContext(connection) as queries:
        list(dashboard_stores(viewer, "sales_management.view", cache).values("id"))
    assert len(queries) == 2  # Store projection plus effective-admin role lookup.
    assert all("sales_order" not in query["sql"] for query in queries)


@pytest.mark.django_db
def test_dashboard_tenant_admin_skips_personnel_filter_but_keeps_sales_scope():
    from apps.permissions.models import RoleResourcePolicy
    from apps.permissions.role_catalog import sync_tenant_administrator_role
    from apps.sales_management.dashboard_scope import dashboard_stores

    tenant = Tenant.objects.create(name="admin-store-scope", code="admin-store-scope")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    admin = _user(tenant, "store-scope-admin")
    unrestricted = _store(tenant, platform, "admin-unassigned", "PHP", "PH", "Asia/Manila")
    scoped = _store(tenant, platform, "admin-sales-scope", "PHP", "PH", "Asia/Manila")
    other = Tenant.objects.create(name="admin-store-other", code="admin-store-other")
    other_platform = PlatformMaster.objects.create(tenant=other, code="shopee", name="Shopee", platform_type="shopee")
    foreign = _store(other, other_platform, "admin-foreign", "PHP", "PH", "Asia/Manila")
    admin_role = sync_tenant_administrator_role(tenant)
    UserRole.objects.create(tenant=tenant, user=admin, role=admin_role)
    # The administrator ALL scope includes every store in the tenant.
    assert set(dashboard_stores(admin, "sales_management.view").values_list("pk", flat=True)) == {unrestricted.pk, scoped.pk}

    # A resource policy explicitly narrows this administrator permission;
    # the user-level custom grant remains independent and applies as a union.
    RoleResourcePolicy.objects.create(tenant=tenant, role=admin_role,
        resource_code="sales_management.sales", permission_code="sales_management.view",
        scope_type="custom", config={"store_ids": [scoped.pk]})
    _grant(admin, scope_type=DataScope.ScopeType.CUSTOM, config={"store_ids": [scoped.pk]})

    visible = list(dashboard_stores(admin, "sales_management.view").values_list("pk", flat=True))
    assert visible == [scoped.pk]
    assert unrestricted.pk not in visible
    assert foreign.pk not in visible


@pytest.mark.django_db
def test_dashboard_expired_admin_role_does_not_skip_personnel_filter():
    from datetime import timedelta
    from apps.permissions.role_catalog import sync_tenant_administrator_role
    from apps.sales_management.dashboard_scope import dashboard_stores

    tenant = Tenant.objects.create(name="expired-admin-scope", code="expired-admin-scope")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    admin = _user(tenant, "expired-store-admin")
    assigned = _store(tenant, platform, "expired-admin-assigned", "PHP", "PH", "Asia/Manila")
    unassigned = _store(tenant, platform, "expired-admin-unassigned", "PHP", "PH", "Asia/Manila")
    admin_role = sync_tenant_administrator_role(tenant)
    UserRole.objects.create(tenant=tenant, user=admin, role=admin_role, valid_until=timezone.now() - timedelta(seconds=1))
    _grant(admin)

    assert list(dashboard_stores(admin, "sales_management.view").values_list("pk", flat=True)) == []
    StoreMaster.objects.filter(pk=assigned.pk).update(operator=admin)
    assert list(dashboard_stores(admin, "sales_management.view").values_list("pk", flat=True)) == [assigned.pk]
    assert unassigned.pk not in dashboard_stores(admin, "sales_management.view").values_list("pk", flat=True)


@pytest.mark.django_db
@pytest.mark.parametrize("store_id", ["", "0", "-1", "1.5", "abc", "９", "9223372036854775808"])
def test_dashboard_rejects_invalid_store_id(store_id):
    tenant = Tenant.objects.create(name="invalid-store", code="invalid-store")
    viewer = _user(tenant, "invalid-store-viewer")
    _grant(viewer)
    client = APIClient()
    client.force_authenticate(user=viewer)
    assert client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": store_id}).status_code == 400


@pytest.mark.django_db
def test_dashboard_no_assignments_does_not_fall_back_to_all_and_superuser_can_switch():
    tenant = Tenant.objects.create(name="empty-managed", code="empty-managed")
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    store = _store(tenant, platform, "unassigned", "PHP", "PH", "Asia/Manila")
    foreign_tenant = Tenant.objects.create(name="superuser-other-tenant", code="superuser-other-tenant")
    foreign_platform = PlatformMaster.objects.create(
        tenant=foreign_tenant, code="shopee", name="Shopee", platform_type="shopee"
    )
    foreign_store = _store(foreign_tenant, foreign_platform, "foreign-unassigned", "PHP", "PH", "Asia/Manila")
    viewer = _user(tenant, "unassigned-viewer")
    _grant(viewer)
    client = APIClient()
    client.force_authenticate(user=viewer)
    data = client.get("/api/internal/commerce/dashboard/monthly-sales/").json()["data"]
    assert data["stores"] == [] and data["currencies"] == []
    assert client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": store.pk}).status_code == 403
    viewer.is_superuser = True
    viewer.save()
    response = client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": store.pk})
    assert response.status_code == 200
    assert response.json()["data"]["stores"][0]["id"] == store.pk
    assert client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": foreign_store.pk}).status_code == 403


@pytest.mark.django_db
def test_dashboard_personnel_cannot_expand_platform_scope_or_cross_tenant():
    tenant = Tenant.objects.create(name="platform-boundary", code="platform-boundary")
    viewer = _user(tenant, "platform-boundary-viewer")
    shopee = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    tiktok = PlatformMaster.objects.create(tenant=tenant, code="tiktok", name="TikTok", platform_type="tiktok")
    hidden = _store(tenant, shopee, "shopee-managed", "PHP", "PH", "Asia/Manila")
    visible = _store(tenant, tiktok, "tk-managed", "PHP", "PH", "Asia/Manila")
    StoreMaster.objects.filter(pk__in=[hidden.pk, visible.pk]).update(operator=viewer)
    _grant(viewer, scope_type="custom", config={"platforms": ["tiktok"]})
    other = Tenant.objects.create(name="other-platform", code="other-platform")
    other_platform = PlatformMaster.objects.create(tenant=other, code="tiktok", name="TikTok", platform_type="tiktok")
    foreign = _store(other, other_platform, "foreign", "PHP", "PH", "Asia/Manila")
    # Even inconsistent historical personnel references must not cross tenants.
    StoreMaster.objects.filter(pk=foreign.pk).update(operator=viewer)
    client = APIClient()
    client.force_authenticate(user=viewer)
    response = client.get("/api/internal/commerce/dashboard/monthly-sales/")
    assert [row["id"] for row in response.json()["data"]["stores"]] == [visible.pk]
    for store in (hidden, foreign):
        assert client.get("/api/internal/commerce/dashboard/monthly-sales/", {"store_id": store.pk}).status_code == 403
    assert client.get(f"/api/internal/commerce/dashboard/monthly-sales/?store_id={visible.pk}&store_id={hidden.pk}").status_code == 400


@pytest.mark.django_db
def test_platform_switch_filters_choices_and_facts_and_rejects_cross_platform_store(monkeypatch):
    monkeypatch.setattr("apps.sales_management.views.timezone.localdate", lambda **kwargs: date(2026, 10, 2))
    tenant = Tenant.objects.create(name="switch", code="switch")
    viewer = _user(tenant, "switch-viewer")
    _grant(viewer)
    client = APIClient()
    client.force_authenticate(user=viewer)
    platforms = [PlatformMaster.objects.create(tenant=tenant, code=code, name=code, platform_type=code)
                 for code in ("shopee", "tiktok")]
    stores = [_store(tenant, platform, platform.code, "PHP", "PH", "Asia/Manila") for platform in platforms]
    StoreMaster.objects.filter(pk__in=[s.pk for s in stores]).update(operator=viewer)
    for i, store in enumerate(stores):
        _order(tenant, store, f"switch-{i}", str(10 + i), local_day=date(2026, 10, 2))
    url = "/api/internal/commerce/dashboard/monthly-sales/"
    for platform, store in zip(platforms, stores):
        response = client.get(url, {"platform_id": platform.pk})
        assert response.status_code == 200
        data = response.json()["data"]
        assert {p["id"] for p in data["platforms"]} == {p.pk for p in platforms}
        assert [s["id"] for s in data["stores"]] == [store.pk]
        assert data["selected_platform_id"] == platform.pk
        assert len(data["currencies"][0]["daily"]) == 1
        assert data["currencies"][0]["daily"][0]["amount"] == str(10 + stores.index(store))
    assert client.get(url, {"platform_id": platforms[0].pk, "store_id": stores[1].pk}).status_code == 403
    assert client.get(url, {"platform_id": 9999999}).status_code == 403
    assert client.get(url + "?platform_id=1&platform_id=2").status_code == 400
    for value in ("", "0", "-1", "1.5", "abc", "９", "9223372036854775808"):
        assert client.get(url, {"platform_id": value}).status_code == 400


@pytest.mark.django_db
def test_advertising_only_currency_and_previous_day_are_included(monkeypatch):
    from decimal import Decimal
    monkeypatch.setattr("apps.sales_management.views.timezone.localdate", lambda **kwargs: date(2026, 10, 2))
    tenant = Tenant.objects.create(name="ad-projection", code="ad-projection")
    viewer = _user(tenant, "ad-projection-viewer")
    _grant(viewer)
    platform = PlatformMaster.objects.create(tenant=tenant, code="shopee", name="Shopee", platform_type="shopee")
    store = _store(tenant, platform, "ads-only", "PHP", "PH", "Asia/Manila")
    store.operator = viewer
    store.save()
    def ads(request, selected_stores, start, end, *, comparison=False):
        assert comparison is True
        assert [s["id"] for s in selected_stores] == [store.pk]
        assert start == date(2026, 9, 30) and end == date(2026, 10, 2)
        return "available", {("PHP", "2026-09-30"): Decimal("10"),
                             ("PHP", "2026-10-01"): Decimal("0"),
                             ("PHP", "2026-10-02"): None}, {("PHP", "2026-10-02"): {"current": "20", "previous": "10", "covered_stores": 1, "total_stores": 2}}
    monkeypatch.setattr("apps.sales_management.dashboard_advertising.dashboard_advertising", ads)
    client = APIClient()
    client.force_authenticate(user=viewer)
    data = client.get("/api/internal/commerce/dashboard/monthly-sales/", {"platform_id": platform.pk}).json()["data"]
    assert data["advertising_status"] == "available"
    assert data["currencies"] == [{"currency": "PHP",
        "previous": {"amount": "0", "quantity": 0, "ad_spend": "10"},
        "daily": [{"date": "2026-10-01", "amount": "0", "quantity": 0, "ad_spend": "0"},
                  {"date": "2026-10-02", "amount": "0", "quantity": 0, "ad_spend": None,
                   "ad_comparison": {"current": "20", "previous": "10", "covered_stores": 1, "total_stores": 2}}]}]
