from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone as django_timezone

from apps.accounts.models import CustomUser
from apps.influencers.attribution import (
    _bd_reporting_scope,
    build_bd_performance,
    default_performance_dates,
    rule_version_for,
)
from apps.influencers.models import (
    AffiliateOrderSnapshot,
    BdOrderAttributionSnapshot,
    BdSampleAttributionSnapshot,
    OutreachTask,
    SampleFulfillment,
    SampleItem,
)
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def _fixture(code="bd-country-scope"):
    tenant = Tenant.objects.create(name=code, code=code)
    user = CustomUser.objects.create_user(
        username=f"{code}-user", tenant=tenant, user_type=CustomUser.UserType.INTERNAL,
    )
    role = Role.objects.create(tenant=tenant, name="BD", code=code)
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    permissions = {}
    for permission_code in ("influencers.outreach.view", "influencers.fulfillment.view"):
        permission, _ = Permission.objects.get_or_create(
            code=permission_code,
            defaults={"name": permission_code, "module": "influencers", "action": "view"},
        )
        role.permissions.add(permission)
        permissions[permission_code] = permission_code
    platform = PlatformMaster.objects.create(
        tenant=tenant, code=f"platform-{code}", name="TikTok",
        platform_type=PlatformMaster.PlatformType.TIKTOK,
    )
    ph_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code=f"ph-{code}", name="PH", country_code="PH", currency="PHP",
    )
    th_store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code=f"th-{code}", name="TH", country_code="TH", currency="THB",
    )
    ph_wh = WarehouseMaster.objects.create(
        tenant=tenant, code=f"ph-wh-{code}", name="PH warehouse", country_code="PH",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    other_ph_wh = WarehouseMaster.objects.create(
        tenant=tenant, code=f"other-ph-wh-{code}", name="Other PH warehouse", country_code="PH",
        warehouse_type=WarehouseMaster.WarehouseType.THIRD_PARTY,
    )
    scope = DataScope.objects.create(
        tenant=tenant, role=role, scope_type=DataScope.ScopeType.CUSTOM,
        config={"store_ids": [ph_store.pk, th_store.pk], "warehouse_ids": [ph_wh.pk]},
    )
    scopes = {permission_code: scope for permission_code in permissions}
    influencer = __import__("apps.influencers.models", fromlist=["Influencer"]).Influencer.objects.create(
        tenant=tenant, code=f"creator-{code}", name="Creator", platform="tiktok", handle=f"creator-{code}",
    )
    task = OutreachTask.objects.create(
        tenant=tenant, task_no=f"task-{code}", store=ph_store, influencer=influencer,
        dispatcher=user, owner=user,
    )
    good_sample = _sample(tenant, user, influencer, ph_store, task, ph_wh, f"good-{code}")
    forbidden_sample = _sample(tenant, user, influencer, ph_store, task, other_ph_wh, f"forbidden-{code}")
    foreign_country_sample = _sample(tenant, user, influencer, th_store, None, None, f"th-{code}")
    return tenant, user, role, ph_store, th_store, ph_wh, other_ph_wh, scopes, good_sample, forbidden_sample, foreign_country_sample


def _sample(tenant, user, influencer, store, task, warehouse, key):
    fulfillment = SampleFulfillment.objects.create(
        tenant=tenant, fulfillment_no=f"ful-{key}", request_key=f"request-{key}",
        request_hash=f"hash-{key}", influencer=influencer, store=store, owner=user,
        outreach_task=task, sample_sent_at=django_timezone.now() - timedelta(days=2),
    )
    if warehouse:
        SampleItem.objects.create(
            tenant=tenant, fulfillment=fulfillment, warehouse=warehouse, site_code=store.country_code,
            requested_sku=f"sku-{key}", quantity=1,
        )
    return BdSampleAttributionSnapshot.objects.create(
        tenant=tenant, fulfillment=fulfillment, owner=user, influencer=influencer, store=store,
        creator_username=influencer.handle, shop_abbr=store.code, site=store.country_code,
        product_id=f"product-{key}", product_name="Test", sku_id=f"sku-{key}",
        sampled_at=fulfillment.sample_sent_at, sample_status=fulfillment.status,
        cost_amount=Decimal("1.0000"), currency=store.currency, pricing_status="pending",
    )


def _order(tenant, user, influencer, store, sample, key, data_time):
    order = AffiliateOrderSnapshot.objects.create(
        tenant=tenant, source="test", source_row_key=key, row_hash=key, data_time=data_time,
        shop_abbr=store.code, site=store.country_code, store=store, order_id=key,
        product_id="product", sku_id="sku", currency=store.currency, quantity=1,
        fully_returned="否", settlement_status="已结算", order_status="completed",
        creator_username=influencer.handle, creator_username_normalized=influencer.handle,
        estimated_commission_base=Decimal("10.0000"),
        actual_paid_commission=Decimal("1.0000"), actual_paid_shop_ads_commission=Decimal("0.0000"),
    )
    BdOrderAttributionSnapshot.objects.create(
        tenant=tenant, order_snapshot=order, sample_attribution=sample, owner=user,
        influencer=influencer, store=store, order_id=key, sku_id="sku", product_id="product",
        rule="strict", rule_version=rule_version_for("strict"),
    )
    return order


def test_scope_intersects_store_and_explicit_warehouse_and_hides_diagnostics():
    tenant, user, role, ph_store, th_store, ph_wh, other_ph_wh, scopes, good, forbidden, foreign = _fixture()
    visible_store_ids, visible_samples = _bd_reporting_scope(user, tenant)
    assert set(visible_store_ids.values_list("pk", flat=True)) == {ph_store.pk}
    assert set(visible_samples.values_list("pk", flat=True)) == {good.pk}

    # Even a caller-supplied unscoped maximum date is ignored for a user report.
    outside_date = django_timezone.now() - timedelta(days=2)
    start, end = default_performance_dates(tenant=tenant, user=user, max_data_time=outside_date)
    assert end == django_timezone.localdate() - timedelta(days=1)
    report = build_bd_performance(
        tenant=tenant, user=user, start_date=start, end_date=end,
        max_data_time=outside_date,
    )
    assert report["data_as_of"] is None
    assert report["source_status"] == "not_imported"
    assert report["eligibility_diagnostic"]["order_row_count"] == 0
    assert report["totals"]["sample_count"] == 1


def test_all_scopes_keep_all_samples_but_custom_scopes_keep_order_facts_isolated():
    tenant, user, role, ph_store, th_store, ph_wh, other_ph_wh, scopes, good, forbidden, foreign = _fixture("bd-scope-all")
    for scope in scopes.values():
        scope.scope_type = DataScope.ScopeType.ALL
        scope.config = {"all": True}
        scope.save()
    all_store_ids, all_samples = _bd_reporting_scope(user, tenant)
    assert all_store_ids is None and all_samples is None

    for scope in scopes.values():
        scope.scope_type = DataScope.ScopeType.CUSTOM
        scope.config = {"store_ids": [ph_store.pk, th_store.pk], "warehouse_ids": [ph_wh.pk]}
        scope.save()
    influencer = good.influencer
    now = django_timezone.now()
    visible_order = _order(tenant, user, influencer, ph_store, good, "VISIBLE", now - timedelta(days=2))
    hidden_warehouse_order = _order(tenant, user, influencer, ph_store, forbidden, "HIDDEN-WH", now)
    foreign_country_order = _order(tenant, user, influencer, th_store, foreign, "HIDDEN-COUNTRY", now)

    end = django_timezone.localdate()
    start = end - timedelta(days=6)
    report = build_bd_performance(tenant=tenant, user=user, start_date=start, end_date=end)
    assert report["data_as_of"] == django_timezone.localtime(visible_order.data_time).date().isoformat()
    assert report["eligibility_diagnostic"]["order_row_count"] == 1
    assert report["eligibility_diagnostic"]["verified_attributed_line_count"] == 1
    assert "HIDDEN-WH" not in str(report)
    assert "HIDDEN-COUNTRY" not in str(report)

    # Trusted background callers preserve legacy all-tenant-in-tenant behavior.
    unscoped = build_bd_performance(tenant=tenant, start_date=start, end_date=end)
    assert unscoped["eligibility_diagnostic"]["order_row_count"] == 3


def test_samples_require_same_country_warehouse_in_both_permission_scopes():
    tenant, user, outreach_role, ph_store, _, ph_wh, other_ph_wh, _, good, _, _ = _fixture("bd-scope-warehouse-intersection")
    outreach_permission = Permission.objects.get(code="influencers.outreach.view")
    fulfillment_permission = Permission.objects.get(code="influencers.fulfillment.view")
    outreach_role.permissions.remove(fulfillment_permission)
    outreach_scope = DataScope.objects.get(tenant=tenant, role=outreach_role)
    outreach_scope.config = {
        "store_ids": [ph_store.pk], "warehouse_ids": [other_ph_wh.pk],
    }
    outreach_scope.save()

    fulfillment_role = Role.objects.create(
        tenant=tenant, name="Fulfillment scope", code="bd-scope-warehouse-fulfillment",
    )
    fulfillment_role.permissions.add(fulfillment_permission)
    UserRole.objects.create(tenant=tenant, user=user, role=fulfillment_role)
    DataScope.objects.create(
        tenant=tenant, role=fulfillment_role, scope_type=DataScope.ScopeType.CUSTOM,
        config={"store_ids": [ph_store.pk], "warehouse_ids": [ph_wh.pk]},
    )

    # Each grant independently authorizes the same country, but a warehouse
    # authorized by only one permission must not make its sample reportable.
    visible_stores, visible_samples = _bd_reporting_scope(user, tenant)
    assert set(visible_stores.values_list("pk", flat=True)) == {ph_store.pk}
    assert list(visible_samples.values_list("pk", flat=True)) == []
