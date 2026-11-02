from datetime import date
from unittest.mock import patch

import pytest

from apps.integrations.models import ShopeeAdvertisingRecord
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.permissions.models import DataScope, Permission, Role, RoleResourcePolicy, UserRole
from apps.reports.advertising_dataset import advertising_store_scope, advertising_queryset
from apps.integrations.feishu_reports import build_report
from apps.reports.datasets import query_dataset, scope_fingerprint, DATASETS
from tests.test_sales_realtime_board import _fixture, _grant, DAY
from apps.tenants.models import Tenant


def _role(user, code, permission, *, config=None, policy=None):
    perm, _ = Permission.objects.get_or_create(code=permission, defaults={"name": permission, "module": "reports", "action": "view"})
    role = Role.objects.create(tenant=user.tenant, code=code, name=code)
    role.permissions.add(perm)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    if config is not None:
        DataScope.objects.create(tenant=user.tenant, role=role, scope_type="custom", config=config)
    if policy is not None:
        RoleResourcePolicy.objects.create(tenant=user.tenant, role=role, resource_code="masterdata.stores",
            permission_code="*", scope_type="custom", config=policy)
    return role


@pytest.mark.django_db
def test_assigned_store_union_precedes_role_fallback_and_is_platform_neutral():
    user, tenant, shopee, assigned_shopee, run, _ = _fixture("ads-assignment-first")
    _grant(user, "analytics.view")
    DataScope.objects.filter(role__permissions__code="analytics.view", tenant=tenant).update(
        scope_type="custom", config={"warehouse_ids": [1]})
    fallback = StoreMaster.objects.create(tenant=tenant, platform=shopee, code="fallback", name="Fallback", country_code="PH", currency="PHP")
    tiktok = PlatformMaster.objects.create(tenant=tenant, code="tt-assigned", name="TikTok", platform_type="tiktok")
    assigned_tiktok = StoreMaster.objects.create(tenant=tenant, platform=tiktok, code="tt-store", name="TT", country_code="PH", currency="PHP")
    _role(user, "store-fallback", "masterdata.stores.view", config={"store_ids": [fallback.pk]})
    assigned_shopee.operator = user
    assigned_shopee.save(update_fields=["operator"])
    assigned_tiktok.leader = user
    assigned_tiktok.save(update_fields=["leader"])
    mode, ids = advertising_store_scope(user)
    assert mode == "assigned" and set(ids) == {assigned_shopee.pk, assigned_tiktok.pk}
    assert fallback.pk not in ids
    # If the only assignment is on another platform, do not fall back to role scope.
    assigned_shopee.operator = None
    assigned_shopee.save(update_fields=["operator"])
    mode, ids = advertising_store_scope(user)
    assert mode == "assigned" and ids == [assigned_tiktok.pk]
    assert not advertising_queryset(type("Request", (), {"user": user})(), {"date_from": DAY, "date_to": DAY}, "analytics.view").exists()


@pytest.mark.django_db
def test_no_assignment_uses_all_role_store_scope_union_and_policy_overrides_data_scope():
    user, tenant, platform, store_a, run, _ = _fixture("ads-role-union")
    _grant(user, "analytics.view")
    DataScope.objects.filter(role__permissions__code="analytics.view", tenant=tenant).update(
        scope_type="custom", config={"warehouse_ids": [1]})
    DataScope.objects.filter(role__permissions__code="sales_management.view", tenant=tenant).update(
        scope_type="custom", config={"warehouse_ids": [1]})
    store_b = StoreMaster.objects.create(tenant=tenant, platform=platform, code="role-b", name="B", country_code="PH", currency="PHP")
    store_c = StoreMaster.objects.create(tenant=tenant, platform=platform, code="role-c", name="C", country_code="PH", currency="PHP")
    _role(user, "stores-a", "masterdata.stores.view", config={"store_ids": [store_b.pk]}, policy={"store_ids": [store_a.pk]})
    _role(user, "stores-c", "masterdata.stores.view", config={"store_ids": [store_c.pk]})
    mode, ids = advertising_store_scope(user)
    assert mode == "roles" and set(ids) == {store_a.pk, store_c.pk}
    ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=store_a, source_run=run, kind="shop_daily", record_key="a",
        report_date=date.fromisoformat(DAY), currency="PHP", report_timezone="Asia/Manila", dimensions={}, data={"expense": "1"})
    assert set(advertising_queryset(type("Request", (), {"user": user})(), {"date_from": DAY, "date_to": DAY}, "analytics.view").values_list("store_id", flat=True)) == {store_a.pk}
    _grant(user, "reports.view")
    DataScope.objects.filter(role__permissions__code="reports.view", tenant=tenant).update(
        scope_type="custom", config={"warehouse_ids": [1]})
    report = {"dataset": "advertising", "dimensions": ["store_id", "currency"], "metrics": ["record_count"],
        "filters": {"date_from": DAY, "date_to": DAY}}
    first = query_dataset(type("Request", (), {"user": user})(), report)
    assert {row["store_id"] for row in first["rows"]} == {store_a.pk}
    before = scope_fingerprint(user, DATASETS["advertising"], "analytics.view", "advertising")
    RoleResourcePolicy.objects.filter(resource_code="masterdata.stores", role__tenant=tenant).update(config={"store_ids": [store_c.pk]})
    after = scope_fingerprint(user, DATASETS["advertising"], "analytics.view", "advertising")
    assert before != after
    narrowed = query_dataset(type("Request", (), {"user": user})(), report)
    assert narrowed["rows"] == [] and narrowed["cached"] is False


@pytest.mark.django_db
def test_feishu_advertising_anomaly_does_not_require_store_assignment():
    user, tenant, platform, store, run, _ = _fixture("ads-feishu-no-assignment")
    with patch("apps.integrations.feishu_anomaly_reports.build_anomaly_report", return_value={"items": [], "status": "available"}) as build:
        report = build_report({"config": {"report_type": "advertising_anomalies"}}, user)
    assert report["status"] == "available"
    assert build.call_args.kwargs["delivery_store_ids"] is None


@pytest.mark.django_db
def test_inactive_role_and_foreign_tenant_stores_do_not_expand_scope():
    user, tenant, platform, store, run, _ = _fixture("ads-inactive-isolation")
    _grant(user, "analytics.view")
    DataScope.objects.filter(role__permissions__code__in=["analytics.view", "sales_management.view"], tenant=tenant).update(
        scope_type="custom", config={"warehouse_ids": [1]})
    inactive_store = StoreMaster.objects.create(tenant=tenant, platform=platform, code="inactive-role-store", name="I", country_code="PH", currency="PHP")
    role = _role(user, "inactive-store-scope", "masterdata.stores.view", config={"store_ids": [inactive_store.pk]})
    UserRole.objects.filter(user=user, role=role).update(status="inactive")
    foreign = Tenant.objects.create(name="Foreign ads", code="ads-foreign-scope")
    foreign_platform = PlatformMaster.objects.create(tenant=foreign, code="foreign-platform", name="Shopee", platform_type="shopee")
    StoreMaster.objects.create(tenant=foreign, platform=foreign_platform, code="foreign-store", name="Foreign", country_code="PH", currency="PHP", operator=user)
    mode, ids = advertising_store_scope(user)
    assert mode == "roles" and ids == []
