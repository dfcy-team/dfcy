import pytest

from apps.masterdata.country_seed import seed_country_sites
from apps.masterdata.models import CountrySiteMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db


def test_country_seed_is_idempotent_and_preserves_human_values():
    tenant = Tenant.objects.create(name="Seed tenant", code="country-seed")
    first = seed_country_sites(tenant=tenant)
    second = seed_country_sites(tenant=tenant)

    assert first["created"] == first["total"]
    assert second["created"] == 0
    assert CountrySiteMaster.objects.filter(tenant=tenant).count() == first["total"]

    row = CountrySiteMaster.objects.get(tenant=tenant, country_code="TH")
    row.name = "人工泰国名称"
    row.currency = "XTH"
    row.timezone = "Etc/GMT-7"
    row.save(update_fields=["name", "currency", "timezone", "updated_at"])
    seed_country_sites(tenant=tenant)
    row.refresh_from_db()
    assert (row.name, row.currency, row.timezone) == ("人工泰国名称", "XTH", "Etc/GMT-7")


def test_country_seed_deduplicates_by_tenant_and_country_code():
    tenant = Tenant.objects.create(name="Existing tenant", code="existing-country")
    existing = CountrySiteMaster.objects.create(
        tenant=tenant,
        code="legacy-th",
        name="Legacy TH",
        country_code="th",
        currency="",
        timezone="",
    )
    result = seed_country_sites(tenant=tenant, seeds=({"name": "泰国", "country_code": "TH", "currency": "THB", "timezone": "Asia/Bangkok"},))
    assert result["created"] == 0
    assert CountrySiteMaster.objects.filter(tenant=tenant, country_code__iexact="TH").count() == 1
    existing.refresh_from_db()
    assert existing.currency == "THB"
