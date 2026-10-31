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


def test_russia_migration_adds_missing_country_without_overwriting_existing():
    import importlib
    from django.apps import apps
    migration = importlib.import_module('apps.masterdata.migrations.0021_seed_russia')
    fresh = Tenant.objects.create(name='New RU tenant', code='ru-new')
    existing = Tenant.objects.create(name='Existing RU tenant', code='ru-existing')
    row = CountrySiteMaster.objects.create(tenant=existing, code='custom-ru', country_code='ru',
        name='俄罗斯业务区', currency='RUB', timezone='Asia/Vladivostok', status='inactive')
    migration.seed_russia(apps, None)
    migration.seed_russia(apps, None)
    created = CountrySiteMaster.objects.get(tenant=fresh, country_code='RU')
    assert (created.name, created.currency, created.timezone) == ('俄罗斯', 'RUB', 'Europe/Moscow')
    row.refresh_from_db()
    assert (row.name, row.timezone, row.status) == ('俄罗斯业务区', 'Asia/Vladivostok', 'inactive')
    assert CountrySiteMaster.objects.filter(tenant=existing, country_code__iexact='RU').count() == 1
    seed_country_sites(tenant=fresh)
    assert CountrySiteMaster.objects.filter(tenant=fresh, country_code__iexact='RU').count() == 1
