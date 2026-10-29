import pytest
from decimal import Decimal
from types import SimpleNamespace

from apps.common.exceptions import DataScopeDenied
from apps.masterdata.models import StoreMaster
from apps.permissions.models import Role, RoleResourcePolicy
from apps.reports.advertising_dataset import filter_advertising_stores
from apps.sales_management.dashboard_advertising import dashboard_advertising
from tests.test_sales_realtime_board import _fixture, _grant
from tests.test_dashboard_advertising import START, _stores, _tiktok_mapping


@pytest.mark.django_db
@pytest.mark.parametrize("config", [{}, {"unknown": [1]}, {"store_ids": [True]}, {"store_ids": []}])
def test_corrupt_resource_policy_fails_closed_at_read(config):
    user, tenant, platform, store, _, _ = _fixture("ads-corrupt")
    _grant(user, "analytics.view")
    role = Role.objects.get(tenant=tenant, permissions__code="analytics.view")
    policy = RoleResourcePolicy.objects.create(tenant=tenant, role=role,
        resource_code="analytics.advertising", scope_type="custom", config={"store_ids": [store.pk]})
    # Simulate historical DB corruption bypassing the policy write validator.
    RoleResourcePolicy.objects.filter(pk=policy.pk).update(config=config)
    with pytest.raises(DataScopeDenied):
        filter_advertising_stores(user, StoreMaster.objects.all())


@pytest.mark.django_db
def test_advertising_policy_union_is_per_granting_role_and_revocation_removes_access():
    user, tenant, platform, first, _, _ = _fixture("ads-union")
    second = StoreMaster.objects.create(tenant=tenant, platform=platform, code="second", name="Second", country_code="PH", currency="PHP")
    third = StoreMaster.objects.create(tenant=tenant, platform=platform, code="third", name="Third", country_code="PH", currency="PHP")
    _grant(user, "analytics.view", {"analytics_dimensions": [{"store_id": str(first.pk)}]})
    first_role = Role.objects.get(tenant=tenant, permissions__code="analytics.view")
    RoleResourcePolicy.objects.create(tenant=tenant, role=first_role,
        resource_code="analytics.advertising", scope_type="custom", config={"store_ids": [second.pk]})
    _grant(user, "analytics.view", {"analytics_dimensions": [{"store_id": str(third.pk)}]})
    assert set(filter_advertising_stores(user, StoreMaster.objects.all()).values_list("pk", flat=True)) == {second.pk, third.pk}
    first_role.permissions.clear()
    assert set(filter_advertising_stores(user, StoreMaster.objects.all()).values_list("pk", flat=True)) == {third.pk}


@pytest.mark.django_db
def test_tiktok_dashboard_resource_scope_overrides_broad_analytics_scope():
    from apps.integrations.models import TikTokAdsDailySpend
    from apps.masterdata.models import PlatformMaster

    user, tenant, _, _, _, _ = _fixture("ads-tiktok-resource-override")
    # The generic grant is broad for TikTok. The advertising resource policy
    # must replace it for this granting role, while integration visibility is
    # still checked independently by the dashboard.
    _grant(user, "analytics.view", {"analytics_dimensions": [{"platform": "tiktok"}]})
    role = Role.objects.get(tenant=tenant, permissions__code="analytics.view")
    allowed_platform = PlatformMaster.objects.create(
        tenant=tenant, code="tk-allowed", name="TikTok", platform_type="tiktok",
    )
    other_platform = PlatformMaster.objects.create(
        tenant=tenant, code="tk-other", name="TikTok other", platform_type="tiktok",
    )
    allowed = StoreMaster.objects.create(
        tenant=tenant, platform=allowed_platform, code="allowed", name="Allowed",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    excluded = StoreMaster.objects.create(
        tenant=tenant, platform=other_platform, code="excluded", name="Excluded",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    allowed_mapping = _tiktok_mapping(user, allowed, advertiser="201")
    excluded_mapping = _tiktok_mapping(user, excluded, advertiser="202")
    _grant(user, "integrations.store.view")
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code="analytics.advertising",
        scope_type="custom", config={"store_ids": [allowed.pk]},
    )
    TikTokAdsDailySpend.objects.create(
        tenant=tenant, mapping=allowed_mapping, date=START, spend="9", currency="PHP",
    )
    TikTokAdsDailySpend.objects.create(
        tenant=tenant, mapping=excluded_mapping, date=START, spend="4", currency="PHP",
    )

    request = SimpleNamespace(user=user)
    status, allowed_result = dashboard_advertising(request, _stores(allowed), START, START)
    _, excluded_result = dashboard_advertising(request, _stores(excluded), START, START)

    assert status == "available"
    assert allowed_result[("PHP", START.isoformat())] == Decimal("9")
    assert excluded_result[("PHP", START.isoformat())] is None


@pytest.mark.django_db
def test_tiktok_dashboard_honors_shopee_only_override_over_generic_all():
    from apps.integrations.models import TikTokAdsDailySpend
    from apps.masterdata.models import PlatformMaster

    user, tenant, _, _, _, _ = _fixture("ads-tiktok-shopee-override")
    _grant(user, "analytics.view")  # generic ALL scope
    role = Role.objects.get(tenant=tenant, permissions__code="analytics.view")
    shopee_platform = PlatformMaster.objects.create(
        tenant=tenant, code="shopee-override", name="Shopee", platform_type="shopee",
    )
    shopee_store = StoreMaster.objects.create(
        tenant=tenant, platform=shopee_platform, code="shopee-store", name="Shopee store",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant, code="tk-shopee-override", name="TikTok", platform_type="tiktok",
    )
    store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="tk-store", name="TikTok shop",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    mapping = _tiktok_mapping(user, store, advertiser="301")
    _grant(user, "integrations.store.view")
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code="analytics.advertising",
        scope_type="custom", config={"platform_ids": [shopee_platform.pk]},
    )
    TikTokAdsDailySpend.objects.create(
        tenant=tenant, mapping=mapping, date=START, spend="12", currency="PHP",
    )

    status, result = dashboard_advertising(SimpleNamespace(user=user), _stores(store), START, START)

    assert status == "available"
    assert result[("PHP", START.isoformat())] is None


@pytest.mark.django_db
@pytest.mark.parametrize("dimension", ["platform_ids", "site_ids"])
def test_tiktok_dashboard_accepts_platform_and_site_resource_scopes(dimension):
    from apps.integrations.models import TikTokAdsDailySpend
    from apps.masterdata.models import CountrySiteMaster, PlatformMaster

    user, tenant, _, _, _, _ = _fixture(f"ads-tiktok-{dimension}")
    _grant(user, "analytics.view")  # generic ALL is replaced by resource scope
    role = Role.objects.get(tenant=tenant, permissions__code="analytics.view")
    allowed_platform = PlatformMaster.objects.create(
        tenant=tenant, code=f"tk-allowed-{dimension}", name="TikTok", platform_type="tiktok",
    )
    excluded_platform = PlatformMaster.objects.create(
        tenant=tenant, code=f"tk-excluded-{dimension}", name="TikTok other", platform_type="tiktok",
    )
    allowed_site = CountrySiteMaster.objects.create(
        tenant=tenant, code=f"ph-{dimension}", name="Philippines", country_code="PH",
    )
    excluded_site = CountrySiteMaster.objects.create(
        tenant=tenant, code=f"us-{dimension}", name="United States", country_code="US",
    )
    allowed = StoreMaster.objects.create(
        tenant=tenant, platform=allowed_platform, code=f"allowed-{dimension}", name="Allowed",
        country_code="PH", currency="PHP", timezone="Asia/Manila",
    )
    excluded = StoreMaster.objects.create(
        tenant=tenant, platform=excluded_platform, code=f"excluded-{dimension}", name="Excluded",
        country_code="US", currency="PHP", timezone="Asia/Manila",
    )
    allowed_mapping = _tiktok_mapping(user, allowed, advertiser="401")
    excluded_mapping = _tiktok_mapping(user, excluded, advertiser="402")
    _grant(user, "integrations.store.view")
    dimension_id = allowed_platform.pk if dimension == "platform_ids" else allowed_site.pk
    RoleResourcePolicy.objects.create(
        tenant=tenant, role=role, resource_code="analytics.advertising",
        scope_type="custom", config={dimension: [dimension_id]},
    )
    TikTokAdsDailySpend.objects.create(
        tenant=tenant, mapping=allowed_mapping, date=START, spend="7", currency="PHP",
    )
    TikTokAdsDailySpend.objects.create(
        tenant=tenant, mapping=excluded_mapping, date=START, spend="3", currency="PHP",
    )

    request = SimpleNamespace(user=user)
    status, allowed_result = dashboard_advertising(request, _stores(allowed), START, START)
    _, excluded_result = dashboard_advertising(request, _stores(excluded), START, START)

    assert status == "available"
    assert allowed_result[("PHP", START.isoformat())] == Decimal("7")
    assert excluded_result[("PHP", START.isoformat())] is None
