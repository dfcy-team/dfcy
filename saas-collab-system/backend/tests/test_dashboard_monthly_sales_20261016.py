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
        tenant=tenant, platform="shopee", account_alias=f"auth-{suffix}", created_by=user
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
    assert currencies["PHP"]["previous"] == {"amount": "7", "quantity": 4}
    assert currencies["PHP"]["daily"] == [
        {"date": first_day.isoformat(), "amount": "25.5", "quantity": 3},
        {"date": today.isoformat(), "amount": "12", "quantity": 1},
    ]
    assert currencies["THB"]["previous"] == {"amount": "0", "quantity": 0}
    assert currencies["THB"]["daily"] == [{"date": today.isoformat(), "amount": "40", "quantity": 5}]
    assert currencies["MYR"] == {"currency": "MYR", "previous": {"amount": "13", "quantity": 2}, "daily": []}
    assert cancelled.normalized_status == "cancelled"
    assert php_order.store_id == visible_php.id and thb_order.store_id == visible_thb.id
    assert php_baseline.store_id == visible_php.id


@pytest.mark.django_db
def test_dashboard_monthly_sales_requires_sales_view_permission():
    tenant = Tenant.objects.create(name="dashboard-permission", code="dashboard-permission")
    user = _user(tenant, "no-sales-permission")
    client = APIClient()
    client.force_authenticate(user=user)

    response = client.get("/api/internal/commerce/dashboard/monthly-sales/")

    assert response.status_code == 403
