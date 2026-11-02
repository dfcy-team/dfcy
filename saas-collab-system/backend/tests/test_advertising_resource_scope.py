import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import PermissionDenied

from apps.common.exceptions import DataScopeDenied
from apps.integrations.models import ShopeeAdvertisingRecord
from apps.masterdata.models import CountrySiteMaster, StoreMaster
from apps.permissions.models import DataScope, Role, RoleResourcePolicy, UserRole
from apps.reports.advertising_dataset import advertising_queryset, filter_advertising_stores
from apps.tenants.models import Tenant
from tests.test_sales_realtime_board import DAY, _fixture, _grant, _order

SALES_OPERATIONS_URL = "/api/internal/commerce/sales-operations/"
BOARD_URL = "/api/internal/commerce/realtime-board/"


@pytest.mark.django_db
def test_resource_policy_store_choices_include_authorized_shops_without_ads():
    user, tenant, platform, store, run, client = _fixture("ads-scope-no-facts")
    _grant(user, "analytics.view")
    expected = StoreMaster.objects.create(tenant=tenant, platform=platform, code="expected", name="Expected",
        country_code="PH", currency="PHP", timezone="Asia/Manila")
    role = Role.objects.filter(tenant=tenant, permissions__code="analytics.view").first()
    RoleResourcePolicy.objects.create(tenant=tenant, role=role, resource_code="masterdata.stores",
        permission_code="*", scope_type="custom", config={"store_ids": [store.pk, expected.pk]})

    choices = filter_advertising_stores(user, StoreMaster.objects.all())
    assert set(choices.values_list("pk", flat=True)) == {store.pk, expected.pk}
    _order(tenant, platform, store, run, "with-ad", amount="100")
    _order(tenant, platform, expected, run, "without-ad", amount="200")
    ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=store, kind="shop_daily", record_key="present",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=run,
        dimensions={"store_id": str(store.pk), "platform": "shopee", "country": "PH"}, data={"expense": "10"})
    data = client.get(BOARD_URL, {"date_from": DAY, "date_to": DAY}).json()["data"]
    coverage = data["currency_groups"][0]["ad_coverage"]
    assert coverage["expected_store_count"] == 2


@pytest.mark.django_db
def test_no_analytics_view_cannot_be_granted_by_advertising_policy():
    user, tenant, platform, store, run, client = _fixture("ads-scope-no-permission")
    role = Role.objects.create(tenant=tenant, name="policy-only", code="policy-only")
    UserRole.objects.create(tenant=tenant, user=user, role=role)
    RoleResourcePolicy.objects.create(tenant=tenant, role=role, resource_code="masterdata.stores",
        permission_code="*", scope_type="all", config={"all": True})
    with pytest.raises(PermissionDenied):
        advertising_queryset(type("Request", (), {"user": user})(),
            {"date_from": DAY, "date_to": DAY}, "analytics.view")


@pytest.mark.django_db
def test_store_scope_is_tenant_limited_and_ignores_legacy_site_policy():
    user, tenant, platform, store, run, client = _fixture("ads-scope-site")
    _grant(user, "analytics.view")
    role = Role.objects.filter(tenant=tenant, permissions__code="analytics.view").first()
    site = CountrySiteMaster.objects.create(tenant=tenant, code="ph", name="Philippines", country_code="PH")
    other = StoreMaster.objects.create(tenant=tenant, platform=platform, code="malaysia", name="Malaysia",
        country_code="MY", currency="MYR", timezone="Asia/Kuala_Lumpur")
    DataScope.objects.create(tenant=tenant, role=role, scope_type="custom", config={"store_ids": [store.pk]})
    assert set(filter_advertising_stores(user, StoreMaster.objects.all()).values_list("pk", flat=True)) == {store.pk, other.pk}
    foreign = Tenant.objects.create(name="foreign", code="ads-scope-site-foreign")
    foreign_site = CountrySiteMaster.objects.create(tenant=foreign, code="ph", name="Philippines", country_code="PH")
    # Even a malformed legacy scope cannot expose a store from another tenant.
    assert not StoreMaster.objects.filter(tenant=tenant, pk=foreign_site.pk).filter(tenant=foreign).exists()


@pytest.mark.django_db
def test_mixed_legacy_role_scope_is_overridden_only_by_ad_policy():
    user, tenant, platform, store, run, client = _fixture("ads-scope-mixed")
    # Advertising now reads masterdata.stores scopes, independently of the
    # analytics dimension scope.
    _grant(user, "analytics.view", {"store_ids": [store.pk]})
    other = StoreMaster.objects.create(tenant=tenant, platform=platform, code="out-of-scope", name="Out",
        country_code="PH", currency="PHP", timezone="Asia/Manila")
    role = Role.objects.filter(tenant=tenant, permissions__code="analytics.view").first()
    assert store.pk in set(filter_advertising_stores(user, StoreMaster.objects.all()).values_list("pk", flat=True))
    RoleResourcePolicy.objects.create(tenant=tenant, role=role, resource_code="masterdata.stores",
        permission_code="*", scope_type="custom", config={"store_ids": [store.pk]})
    DataScope.objects.filter(role=role).update(config={"warehouse_ids": [2]})
    visible = filter_advertising_stores(user, StoreMaster.objects.all())
    assert store.pk in set(visible.values_list("pk", flat=True))
    ShopeeAdvertisingRecord.objects.create(tenant=tenant, store=store, kind="shop_daily", record_key="mixed-fact",
        report_date=DAY, currency="PHP", report_timezone="Asia/Manila", source_run=run,
        dimensions={"store_id": str(store.pk), "platform": "shopee", "country": "PH"}, data={"expense": "10"})
    facts = advertising_queryset(type("Request", (), {"user": user})(),
        {"date_from": DAY, "date_to": DAY}, "analytics.view")
    assert set(facts.values_list("store_id", flat=True)) == {store.pk}
    assert facts.get().data["expense"] == "10"
    _order(tenant, platform, store, run, "mixed-authorized-sale", amount="100")
    response = client.get(BOARD_URL, {"date_from": DAY, "date_to": DAY})
    assert response.status_code == 200
    assert response.json()["data"]["currency_groups"][0]["ad_spend"] == "10"
