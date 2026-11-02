from datetime import date
from types import SimpleNamespace

import pytest
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.integrations.models import ShopeeAdvertisingRecord, SyncRun
from apps.masterdata.models import StoreMaster
from apps.permissions.models import DataScope, Permission, Role, RoleResourcePolicy, UserRole
from apps.reports.datasets import DATASETS, query_dataset, scope_fingerprint, selected_permission, source_queryset
from tests.test_sync_capability_gate import make_job
from tests.test_sales_management import create_scope


@pytest.mark.django_db
def test_advertising_report_uses_masterdata_store_scope_union_and_explicit_filter():
    job, authorization = make_job()
    user, store_a = job.integration_config.created_by, authorization.store
    store_b = StoreMaster.objects.create(tenant=user.tenant, platform=store_a.platform, code="report-ads-b", name="B", country_code="PH", currency="PHP")
    store_c = StoreMaster.objects.create(tenant=user.tenant, platform=store_a.platform, code="report-ads-c", name="C", country_code="PH", currency="PHP")
    reports, _ = Permission.objects.get_or_create(code="reports.view", defaults={"name": "Reports", "module": "reports", "action": "view"})
    analytics, _ = Permission.objects.get_or_create(code="analytics.view", defaults={"name": "Analytics", "module": "analytics", "action": "view"})
    report_role = Role.objects.create(tenant=user.tenant, code="report-ads-dedicated", name="Advertising reports")
    report_role.permissions.add(reports)
    UserRole.objects.create(tenant=user.tenant, user=user, role=report_role)
    DataScope.objects.create(tenant=user.tenant, role=report_role, scope_type="custom", config={"store_ids": [store_a.pk, store_c.pk]})
    business_role = Role.objects.create(tenant=user.tenant, code="report-ads-business", name="Advertising business")
    business_role.permissions.add(analytics)
    UserRole.objects.create(tenant=user.tenant, user=user, role=business_role)
    DataScope.objects.create(tenant=user.tenant, role=business_role, scope_type="custom", config={"store_ids": [store_b.pk]})
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job, run_id="report-ads-scope", idempotency_key="report-ads-scope")
    for store in (store_a, store_b, store_c):
        ShopeeAdvertisingRecord.objects.create(tenant=job.tenant, store=store, source_run=run, kind="shop_daily",
            record_key=f"report-ads-{store.pk}", report_date=date(2026, 10, 1), currency="PHP", report_timezone="Asia/Manila",
            dimensions={"store_id": str(store.pk), "platform": "shopee", "country": "PH"}, data={"expense": "1"})

    assert selected_permission(user, DATASETS["advertising"]) == "analytics.view"
    base = {"dataset": "advertising", "filters": {"date_from": "2026-10-01", "date_to": "2026-10-01"}}
    request = SimpleNamespace(user=user)
    initial = query_dataset(request, {**base, "dimensions": ["store_id", "currency"], "metrics": ["record_count"]})
    assert {row["store_id"] for row in initial["rows"]} == {store_a.pk, store_b.pk, store_c.pk}
    assert query_dataset(request, {**base, "dimensions": ["store_id", "currency"], "metrics": ["record_count"]})["cached"] is True
    explicit = {**base, "filters": {**base["filters"], "store_ids": f"{store_a.pk},{store_b.pk}"}}
    rows = source_queryset(request, explicit, "analytics.view")
    assert set(rows.values_list("store_id", flat=True)) == {store_a.pk, store_b.pk}
    with pytest.raises(ValidationError):
        source_queryset(request, {**explicit, "filters": {**explicit["filters"], "date_from": "2026-10-02"}}, "analytics.view")
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["sales"])


@pytest.mark.django_db
def test_advertising_report_requires_business_grant_and_active_dedicated_binding():
    job, authorization = make_job()
    user, store = job.integration_config.created_by, authorization.store
    reports, _ = Permission.objects.get_or_create(code="reports.view", defaults={"name": "Reports", "module": "reports", "action": "view"})
    analytics, _ = Permission.objects.get_or_create(code="analytics.view", defaults={"name": "Analytics", "module": "analytics", "action": "view"})
    role = Role.objects.create(tenant=user.tenant, code="ads-report-gates", name="Report gates")
    role.permissions.add(reports)
    binding = UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    RoleResourcePolicy.objects.create(tenant=user.tenant, role=role, permission_code="*", resource_code="reports.advertising",
        scope_type="custom", config={"store_ids": [store.pk]})
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
        config={"report_types": ["analytics_summary"]})
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["advertising"])
    business = Role.objects.create(tenant=user.tenant, code="ads-report-business-gate", name="Analytics business")
    business.permissions.add(analytics)
    UserRole.objects.create(tenant=user.tenant, user=user, role=business)
    DataScope.objects.create(tenant=user.tenant, role=business, scope_type=DataScope.ScopeType.ALL, config={"all": True})
    assert selected_permission(user, DATASETS["advertising"]) == "analytics.view"
    binding.valid_until = "2020-01-01T00:00:00Z"
    binding.save(update_fields=["valid_until"])
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["advertising"])


@pytest.mark.django_db
def test_advertising_report_explicit_policy_rejects_foreign_or_malformed_store_ids():
    job, authorization = make_job()
    user, store = job.integration_config.created_by, authorization.store
    _, _, foreign_store, _ = create_scope("ads-report-foreign")
    reports, _ = Permission.objects.get_or_create(code="reports.view", defaults={"name": "Reports", "module": "reports", "action": "view"})
    analytics, _ = Permission.objects.get_or_create(code="analytics.view", defaults={"name": "Analytics", "module": "analytics", "action": "view"})
    role = Role.objects.create(tenant=user.tenant, code="ads-report-invalid", name="Invalid report policy")
    role.permissions.add(reports)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(tenant=user.tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM, config={"report_types": ["analytics_summary"]})
    business = Role.objects.create(tenant=user.tenant, code="ads-report-invalid-business", name="Analytics business")
    business.permissions.add(analytics)
    UserRole.objects.create(tenant=user.tenant, user=user, role=business)
    DataScope.objects.create(tenant=user.tenant, role=business, scope_type=DataScope.ScopeType.ALL, config={"all": True})
    policy = RoleResourcePolicy.objects.create(tenant=user.tenant, role=role, permission_code="*", resource_code="masterdata.stores",
        scope_type="custom", config={"store_ids": [store.pk]})
    RoleResourcePolicy.objects.filter(pk=policy.pk).update(config={"store_ids": [True]})
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["advertising"])
    RoleResourcePolicy.objects.filter(pk=policy.pk).update(config={"store_ids": [foreign_store.pk]})
    with pytest.raises(PermissionDenied):
        selected_permission(user, DATASETS["advertising"])


@pytest.mark.django_db
def test_legacy_report_type_authorization_still_allows_advertising_without_explicit_policy():
    job, _ = make_job()
    user = job.integration_config.created_by
    reports, _ = Permission.objects.get_or_create(code="reports.view", defaults={"name": "Reports", "module": "reports", "action": "view"})
    analytics, _ = Permission.objects.get_or_create(code="analytics.view", defaults={"name": "Analytics", "module": "analytics", "action": "view"})
    reports_role = Role.objects.create(tenant=user.tenant, code="ads-report-legacy", name="Legacy report")
    reports_role.permissions.add(reports)
    UserRole.objects.create(tenant=user.tenant, user=user, role=reports_role)
    DataScope.objects.create(tenant=user.tenant, role=reports_role, scope_type=DataScope.ScopeType.CUSTOM,
        config={"report_types": ["analytics_summary"]})
    analytics_role = Role.objects.create(tenant=user.tenant, code="ads-business-legacy", name="Analytics business")
    analytics_role.permissions.add(analytics)
    UserRole.objects.create(tenant=user.tenant, user=user, role=analytics_role)
    DataScope.objects.create(tenant=user.tenant, role=analytics_role, scope_type=DataScope.ScopeType.ALL, config={"all": True})
    assert selected_permission(user, DATASETS["advertising"]) == "analytics.view"

