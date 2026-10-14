"""Synthetic FX governance/report tests; use settlement_test and disposable SQLite."""

from datetime import date, timedelta
from decimal import Decimal, localcontext
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import connection, migrations
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError as APIValidationError

from apps.accounts.models import CustomUser
from apps.configcenter.models import ConfigChangeLog, SystemConfigDefinition, TenantConfigVersion
from apps.configcenter.services import (
    activate_due_config_versions, approve_config_version, create_config_version, rollback_config_version,
)
from apps.influencers.attribution import _RateResolver, build_bd_performance
from apps.influencers.bd_exchange_rates import BD_EXCHANGE_RATES_CONFIG_KEY, validate_bd_exchange_rates
from apps.influencers.models import AffiliateOrderSnapshot, BdOrderAttributionSnapshot, BdSampleAttributionSnapshot, ExchangeRate
from apps.influencers.settlement import TO_SETTLE
from apps.permissions.models import DataScope
from apps.tenants.models import Tenant
from tests.test_bd_settlement_rule import AUGUST, attribution, fact, instant, sample_context  # noqa: F401
from tests.test_phase3_config_center import client_for, create_user, grant


def rate_row(*, rate="0.25", currency="PHP", effective_from="2026-08-01", **extra):
    return {"currency": currency, "rate": rate, "effective_from": effective_from, **extra}


@pytest.fixture
def fx_context(db, sample_context):
    creator = sample_context.user
    for code in ("config.manage", "config.approve", "config.rollback", "config.view",
                 "influencers.outreach.view", "influencers.fulfillment.view"):
        grant(creator, code)
    approver = create_user(sample_context.tenant, "synthetic-fx-approver")
    grant(approver, "config.approve")
    return SimpleNamespace(
        **vars(sample_context), approver=approver,
        definition=SystemConfigDefinition.objects.get(config_key=BD_EXCHANGE_RATES_CONFIG_KEY),
    )


def configure(context, *, value=None, effective_at=None, approve=True):
    previous_effective = list(TenantConfigVersion.objects.filter(
        tenant=context.user.tenant, config_key=BD_EXCHANGE_RATES_CONFIG_KEY, status="effective",
    ))
    version = create_config_version(
        definition=context.definition, actor=context.user,
        value=value if value is not None else {"rates": [rate_row()]},
        effective_at=effective_at or timezone.now(),
    )
    # Retain synthetic legacy pending/future histories for compatibility probes.
    if not approve or (effective_at is not None and effective_at > timezone.now()):
        corrupt(version, status="approved" if approve else "pending_approval",
                approved_by_id=context.approver.pk if approve else None,
                effective_at=effective_at or version.effective_at)
        for previous in previous_effective:
            corrupt(previous, status="effective")
        version.refresh_from_db()
    return version


def corrupt(version, **values):
    # Deliberately bypass immutability only to simulate corrupted persisted rows.
    assert connection.vendor == "sqlite", "Corruption probes require a disposable SQLite DB."
    QuerySet.update(TenantConfigVersion.objects.filter(pk=version.pk), **values)


@pytest.mark.parametrize("rate", ["1", "0.0000000001", "0001.01000", "9999999999.9999999999"])
def test_validator_preserves_decimal_strings_without_rounding(rate):
    value = {"rates": [rate_row(rate=rate, note="synthetic schedule")]}
    result = validate_bd_exchange_rates(value)
    assert result == value and result is not value and result["rates"][0] is not value["rates"][0]
    assert result["rates"][0]["rate"] == rate


@pytest.mark.parametrize("currency", ["PHP", "MYR", "THB", "USD"])
@pytest.mark.parametrize("effective_from", ["1900-01-01", "2000-02-29", "2100-12-31"])
def test_validator_accepts_supported_currencies_and_inclusive_date_bounds(currency, effective_from):
    validate_bd_exchange_rates({"rates": [rate_row(currency=currency, effective_from=effective_from, note="a" * 240)]})


def test_validator_accepts_empty_schedule_and_1000_distinct_dates():
    assert validate_bd_exchange_rates({"rates": []}) == {"rates": []}
    rows = [rate_row(effective_from=(date(2026, 1, 1) + timedelta(days=day)).isoformat()) for day in range(1000)]
    assert len(validate_bd_exchange_rates({"rates": rows})["rates"]) == 1000
    with pytest.raises(ValidationError, match="at most 1000"):
        validate_bd_exchange_rates({"rates": rows + [rate_row()]})


@pytest.mark.parametrize("rate", [
    None, True, False, 1, 0.125, Decimal("0.125"), "", "0", "0.0000000000", "-0.1", "+1",
    "1e-1", "NaN", "Infinity", " 0.1", "0.1 ", ".1", "1.", "1,1", "10000000000",
    "1.12345678901", "\uff11", "1\n",
])
def test_validator_rejects_invalid_rates(rate):
    with pytest.raises(ValidationError):
        validate_bd_exchange_rates({"rates": [rate_row(rate=rate)]})


@pytest.mark.parametrize("effective_from", [
    None, True, date(2026, 8, 1), "20260801", "2026-W31-6", "2026-8-01", "2026-08-1",
    "2026-08-01T00:00:00Z", "2026-02-30", "1900-02-29", "2100-02-29", "1899-12-31",
    "2101-01-01", "2026-08-01 ", "\uff12\uff10\uff12\uff16-08-01",
])
def test_validator_rejects_invalid_dates(effective_from):
    with pytest.raises(ValidationError):
        validate_bd_exchange_rates({"rates": [rate_row(effective_from=effective_from)]})


@pytest.mark.parametrize("value", [
    None, [], "rates", {}, {"rates": None}, {"rates": {}}, {"rates": [], "extra": 1},
    {"rates": [None]}, {"rates": [{}]}, {"rates": [rate_row(extra=True)]},
    {"rates": [rate_row(currency="CNY")]}, {"rates": [rate_row(currency="EUR")]},
    {"rates": [rate_row(currency="php")]}, {"rates": [rate_row(currency=["PHP"])]},
    {"rates": [rate_row(note=None)]}, {"rates": [rate_row(note=True)]},
    {"rates": [rate_row(note="a" * 241)]}, {"rates": [rate_row(note="token=synthetic-placeholder")]},
])
def test_validator_rejects_unknown_fields_shapes_currencies_and_notes(value):
    with pytest.raises(ValidationError):
        validate_bd_exchange_rates(value)


def test_validator_rejects_duplicate_currency_dates_not_different_currencies():
    with pytest.raises(ValidationError, match="Duplicate"):
        validate_bd_exchange_rates({"rates": [rate_row(), rate_row(rate="0.3")]})
    assert len(validate_bd_exchange_rates({"rates": [rate_row(), rate_row(currency="MYR")]})["rates"]) == 2


def test_migration_seeds_definition_only_idempotently(fx_context):
    module = import_module("apps.influencers.migrations.0035_seed_bd_exchange_rates")
    operations = module.Migration.operations
    assert len(operations) == 1 and isinstance(operations[0], migrations.RunPython)
    assert operations[0].reverse_code is migrations.RunPython.noop
    rates_before = list(ExchangeRate.objects.values())
    versions_before = list(TenantConfigVersion.objects.values())
    performance_before = SystemConfigDefinition.objects.get(config_key="influencers.bd.performance").default_value
    with CaptureQueriesContext(connection) as queries:
        module.seed_bd_exchange_rates(apps, None)
        module.seed_bd_exchange_rates(apps, None)
    item = SystemConfigDefinition.objects.get(config_key=BD_EXCHANGE_RATES_CONFIG_KEY)
    assert item.scope_type == "tenant" and item.value_type == "json" and item.requires_approval
    assert item.default_value == {"rates": []} and not item.is_sensitive
    assert list(ExchangeRate.objects.values()) == rates_before
    assert list(TenantConfigVersion.objects.values()) == versions_before
    assert SystemConfigDefinition.objects.get(config_key="influencers.bd.performance").default_value == performance_before
    writes = [query["sql"] for query in queries if query["sql"].split()[0] in {"INSERT", "UPDATE", "DELETE"}]
    assert writes and all('"configcenter_systemconfigdefinition"' in sql for sql in writes)


@pytest.mark.parametrize("value", [{"rates": [rate_row(rate=0.25)]}, {"rates": [rate_row(rate="0")]}, {"rates": [], "extra": 1}])
def test_invalid_create_is_atomic_and_api_returns_clean_rule_error(fx_context, value):
    c = fx_context
    before = (TenantConfigVersion.objects.count(), ConfigChangeLog.objects.count())
    with pytest.raises(ValidationError):
        configure(c, value=value)
    response = client_for(c.user).post("/api/internal/config/values/", {
        "config_key": BD_EXCHANGE_RATES_CONFIG_KEY, "value": value, "effective_at": timezone.now().isoformat(),
    }, format="json")
    assert response.status_code == 422 and response.json()["code"] == "BUSINESS_RULE_VIOLATION"
    assert (TenantConfigVersion.objects.count(), ConfigChangeLog.objects.count()) == before


@pytest.mark.parametrize("stage", ["approve", "activate", "rollback"])
def test_immutable_values_are_revalidated_from_database_without_transition_or_log(fx_context, stage):
    c = fx_context
    due = timezone.now() + timedelta(hours=1)
    version = configure(c, effective_at=due, approve=stage != "approve")
    old_status = version.status
    before = (TenantConfigVersion.objects.count(), ConfigChangeLog.objects.count())
    corrupt(version, value={"rates": [rate_row(rate="0")]})
    if stage == "activate":
        assert activate_due_config_versions(now=due, config_key=BD_EXCHANGE_RATES_CONFIG_KEY) == {"activated": 0, "superseded": 0, "invalid": 1}
    else:
        with pytest.raises(ValidationError):
            if stage == "approve":
                approve_config_version(version=version, actor=c.approver)
            else:
                rollback_config_version(target_version=version, actor=c.user)
    version.refresh_from_db()
    assert version.status == old_status
    assert (TenantConfigVersion.objects.count(), ConfigChangeLog.objects.count()) == before


def test_fx_two_person_approval_action_permissions_and_all_scope(fx_context):
    c = fx_context
    version = configure(c, approve=False)
    with pytest.raises(ValidationError, match="creator cannot approve"):
        approve_config_version(version=version, actor=c.user)
    unprivileged = create_user(c.tenant, "synthetic-fx-unprivileged")
    with pytest.raises(PermissionDenied):
        create_config_version(definition=c.definition, actor=unprivileged, value={"rates": []}, effective_at=timezone.now())
    with pytest.raises(PermissionDenied):
        approve_config_version(version=version, actor=unprivileged)
    with pytest.raises(PermissionDenied):
        rollback_config_version(target_version=version, actor=unprivileged)
    assert client_for(unprivileged).post(f"/api/internal/config/values/{version.pk}/approve/").status_code == 403
    DataScope.objects.filter(role__user_roles__user=c.approver).update(scope_type=DataScope.ScopeType.OWN)
    with pytest.raises(PermissionDenied, match="all-tenant"):
        approve_config_version(version=version, actor=c.approver)
    assert client_for(c.approver).post(f"/api/internal/config/values/{version.pk}/approve/").status_code == 403
    version.refresh_from_db()
    assert version.status == TenantConfigVersion.Status.PENDING_APPROVAL


@pytest.mark.parametrize("user_type", [CustomUser.UserType.EXTERNAL, CustomUser.UserType.RPA])
def test_fx_external_and_rpa_cannot_manage_approve_or_rollback(fx_context, user_type):
    c = fx_context
    version = configure(c, approve=False)
    c.approver.user_type = user_type
    c.approver.save(update_fields=["user_type"])
    for code in ("config.manage", "config.rollback"):
        grant(c.approver, code)
    with pytest.raises(PermissionDenied):
        create_config_version(definition=c.definition, actor=c.approver, value={"rates": []}, effective_at=timezone.now())
    with pytest.raises(PermissionDenied):
        approve_config_version(version=version, actor=c.approver)
    with pytest.raises(PermissionDenied):
        rollback_config_version(target_version=version, actor=c.approver)


def test_resolver_selects_inclusive_business_date_and_config_beats_newer_legacy(fx_context):
    c = fx_context
    version = configure(c, value={"rates": [rate_row(rate="0.5", effective_from="2026-08-15"), rate_row()]})
    ExchangeRate.objects.create(tenant=c.tenant, created_by=c.user, base_currency="PHP", quote_currency="CNY",
                                rate=Decimal("0.9"), effective_from=date(2026, 8, 16), source="synthetic-newer")
    resolver = _RateResolver(c.tenant)
    for day, expected in ((date(2026, 7, 31), "0.125"), (date(2026, 8, 1), "0.25"),
                          (date(2026, 8, 14), "0.25"), (date(2026, 8, 15), "0.5"), (date(2026, 8, 31), "0.5")):
        rate, detail = resolver.to_cny("PHP", day)
        assert rate == Decimal(expected)
        assert detail["business_date"] == day.isoformat()
        assert detail["config_key"] == BD_EXCHANGE_RATES_CONFIG_KEY
        assert detail["config_version"] == version.version and detail["config_version_id"] == version.pk
    assert resolver.to_cny("PHP", date(2026, 7, 31))[1]["fallback_reason"] == "before_configured_schedule"
    assert resolver.to_cny("PHP", date(2026, 8, 15))[1]["rate_effective_date"] == "2026-08-15"
    assert resolver.to_cny("CNY", date(2026, 8, 15))[0] == Decimal("1")
    assert resolver.metadata()["rate_source"] == "mixed"


def test_resolver_pins_full_schedule_and_uses_at_most_two_queries(fx_context):
    c = fx_context
    first = configure(c, value={"rates": [rate_row(), rate_row(rate="0.5", effective_from="2026-08-20"),
                                          rate_row(currency="USD", rate="7.1000000001")]})
    with CaptureQueriesContext(connection) as queries:
        resolver = _RateResolver(c.tenant)
        resolver.to_cny("PHP", date(2026, 8, 1))
    assert len(queries) == 2
    configure(c, value={"rates": [rate_row(rate="0.9"), rate_row(currency="USD", rate="8")]})
    with CaptureQueriesContext(connection) as queries:
        for day in range(1, 32):
            resolver.convert(Decimal("100"), "PHP", "USD", date(2026, 8, day))
        assert resolver.to_cny("USD", date(2026, 8, 31))[0] == Decimal("7.1000000001")
        assert resolver.to_cny("PHP", date(2026, 8, 31))[0] == Decimal("0.5")
        assert resolver.metadata()["rate_config_version_id"] == first.pk
    assert len(queries) == 0
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 31))[0] == Decimal("0.9")


def test_pending_and_future_versions_do_not_affect_reports(fx_context, monkeypatch):
    c = fx_context
    due = timezone.now() + timedelta(hours=1)
    future = configure(c, effective_at=due)
    assert future.status == TenantConfigVersion.Status.APPROVED
    pending = configure(c, value={"rates": [rate_row(rate="0.8")]}, approve=False)
    resolver = _RateResolver(c.tenant)
    assert resolver.to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.125")
    assert resolver.metadata()["rate_config_version"] is None
    assert activate_due_config_versions(now=due - timedelta(seconds=1), config_key=BD_EXCHANGE_RATES_CONFIG_KEY) == {"activated": 0, "superseded": 0}
    assert activate_due_config_versions(now=due, config_key=BD_EXCHANGE_RATES_CONFIG_KEY) == {"activated": 1, "superseded": 0}
    monkeypatch.setattr(timezone, "now", lambda: due)
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.25")
    pending.refresh_from_db()
    assert pending.status == TenantConfigVersion.Status.PENDING_APPROVAL
    assert ConfigChangeLog.objects.filter(config_key=BD_EXCHANGE_RATES_CONFIG_KEY, action="activate", to_version=future.version).count() == 1


def test_higher_effective_fx_version_blocks_older_delayed_activation(fx_context):
    c = fx_context
    due = timezone.now() + timedelta(hours=1)
    older = configure(c, effective_at=due)
    higher = configure(c, value={"rates": [rate_row(rate="0.5")]})
    result = activate_due_config_versions(now=due, config_key=BD_EXCHANGE_RATES_CONFIG_KEY)
    older.refresh_from_db()
    higher.refresh_from_db()
    assert result == {"activated": 0, "superseded": 1}
    assert older.status == TenantConfigVersion.Status.SUPERSEDED
    assert higher.status == TenantConfigVersion.Status.EFFECTIVE
    assert activate_due_config_versions(now=due, config_key=BD_EXCHANGE_RATES_CONFIG_KEY) == {"activated": 0, "superseded": 0}
    assert _RateResolver(c.tenant).metadata()["rate_config_version_id"] == higher.pk


def test_invalid_due_fx_does_not_block_another_tenant_or_expose_value(fx_context, caplog):
    c = fx_context
    due = timezone.now() + timedelta(hours=1)
    invalid = configure(c, effective_at=due)
    corrupt(invalid, value={"rates": [rate_row(rate="private-corrupt-value")]})
    other_tenant = Tenant.objects.create(name="Other FX Tenant", code="synthetic-other-fx")
    creator = create_user(other_tenant, "synthetic-other-fx-creator")
    approver = create_user(other_tenant, "synthetic-other-fx-approver")
    grant(creator, "config.manage")
    grant(approver, "config.approve")
    valid = configure(SimpleNamespace(user=creator, approver=approver, definition=c.definition), effective_at=due)
    result = activate_due_config_versions(now=due)
    invalid.refresh_from_db()
    valid.refresh_from_db()
    assert result == {"activated": 1, "superseded": 0, "invalid": 1}
    assert invalid.status == TenantConfigVersion.Status.APPROVED
    assert valid.status == TenantConfigVersion.Status.EFFECTIVE
    assert "version_id=" + str(invalid.pk) in caplog.text
    assert "private-corrupt-value" not in caplog.text
    assert not ConfigChangeLog.objects.filter(tenant=c.tenant, action="activate").exists()


def test_invalid_older_due_fx_is_superseded_by_valid_higher_effective_version(fx_context):
    c = fx_context
    due = timezone.now() + timedelta(hours=1)
    older = configure(c, effective_at=due)
    corrupt(older, value={"rates": [rate_row(rate="0")]})
    higher = configure(c, value={"rates": [rate_row(rate="0.5")]})
    assert activate_due_config_versions(now=due) == {"activated": 0, "superseded": 1}
    older.refresh_from_db()
    higher.refresh_from_db()
    assert older.status == TenantConfigVersion.Status.SUPERSEDED
    assert higher.status == TenantConfigVersion.Status.EFFECTIVE


def test_latest_effective_version_wins_but_future_effective_is_ignored(fx_context):
    c = fx_context
    first = configure(c)
    second = configure(c, value={"rates": [rate_row(rate="0.5")]})
    corrupt(first, status=TenantConfigVersion.Status.EFFECTIVE)
    assert _RateResolver(c.tenant).metadata()["rate_config_version_id"] == second.pk
    corrupt(second, effective_at=timezone.now() + timedelta(days=1))
    assert _RateResolver(c.tenant).metadata()["rate_config_version_id"] == first.pk


def test_empty_reset_and_rollback_are_immediate_new_versions_with_legacy_provenance(fx_context):
    c = fx_context
    first = configure(c)
    reset = configure(c, value={"rates": []}, approve=False)
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.25")
    reset = approve_config_version(version=reset, actor=c.approver)
    rate, detail = _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))
    assert rate == Decimal("0.125") and detail["fallback_reason"] == "empty_schedule"
    assert detail["config_version_id"] == reset.pk
    rollback = rollback_config_version(target_version=first, actor=c.user)
    assert rollback.status == TenantConfigVersion.Status.EFFECTIVE and rollback.version == 3
    assert rollback.value == first.value and rollback.pk != first.pk
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.25")
    first.refresh_from_db()
    assert first.status == TenantConfigVersion.Status.SUPERSEDED and first.value == {"rates": [rate_row()]}
    log = ConfigChangeLog.objects.get(config_key=BD_EXCHANGE_RATES_CONFIG_KEY, action="rollback")
    assert log.from_version == first.version and log.to_version == rollback.version


def test_undefined_currency_uses_legacy_or_explicit_missing_not_static_defaults(fx_context):
    c = fx_context
    configure(c)
    ExchangeRate.objects.create(tenant=c.tenant, created_by=c.user, base_currency="MYR", quote_currency="CNY",
                                rate=Decimal("1.65"), effective_from=date(2026, 8, 1), source="synthetic")
    resolver = _RateResolver(c.tenant)
    rate, detail = resolver.to_cny("MYR", date(2026, 8, 16))
    assert rate == Decimal("1.65") and detail["source"] == "tenant_exchange_rate"
    assert detail["fallback_reason"] == "currency_not_configured" and detail["id"] is not None
    assert detail["rate_effective_date"] == "2026-08-01"
    missing, detail = resolver.to_cny("USD", date(2026, 8, 16))
    assert missing is None and detail["source"] == "missing" and detail["rate_effective_date"] is None


def test_fx_tenant_scope_isolation_and_cross_tenant_actions(fx_context):
    c = fx_context
    other = Tenant.objects.create(name="Synthetic FX foreign", code="synthetic-fx-foreign")
    manager = create_user(other, "synthetic-fx-foreign-manager")
    approver = create_user(other, "synthetic-fx-foreign-approver")
    for code in ("config.manage", "config.approve", "config.rollback"):
        grant(manager, code)
    grant(approver, "config.approve")
    foreign = create_config_version(definition=c.definition, actor=manager, value={"rates": [rate_row(rate="0.9")]}, effective_at=timezone.now())
    assert foreign.status == TenantConfigVersion.Status.EFFECTIVE
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.125")
    assert _RateResolver(other).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.9")
    own = configure(c, approve=False)
    with pytest.raises(PermissionDenied, match="outside"):
        approve_config_version(version=own, actor=manager)
    with pytest.raises(PermissionDenied, match="outside"):
        rollback_config_version(target_version=foreign, actor=c.user)
    assert client_for(c.user).post(f"/api/internal/config/values/{foreign.pk}/approve/").status_code == 403
    assert client_for(c.user).post(f"/api/internal/config/values/{foreign.pk}/rollback/", {}, format="json").status_code == 403
    assert [row["id"] for row in client_for(c.user).get("/api/internal/config/values/", {"config_key": BD_EXCHANGE_RATES_CONFIG_KEY}).json()["data"]["results"]] == [own.pk]
    corrupt(foreign, tenant_id=c.tenant.pk)  # Mismatched scope still must not be read.
    assert _RateResolver(c.tenant).metadata()["rate_config_version"] is None
    corrupt(foreign, tenant_id=None, scope_key="system")
    assert _RateResolver(c.tenant).metadata()["rate_config_version"] is None


@pytest.mark.parametrize("value", [{"rates": [rate_row(rate=0.25)]}, {"rates": [rate_row(rate="0")]},
                                         {"rates": [rate_row(), rate_row()]}, {"rates": [rate_row(extra=True)]}])
def test_corrupt_live_schedule_fails_closed_even_with_legacy_rates(fx_context, value):
    c = fx_context
    version = configure(c)
    corrupt(version, value=value)
    with pytest.raises(APIValidationError, match="Active BD exchange-rate configuration is invalid"):
        build_bd_performance(tenant=c.tenant, **AUGUST)
    response = client_for(c.user).get("/api/internal/influencers/bd-performance/", {
        "start_date": "2026-08-01", "end_date": "2026-08-31",
    })
    assert response.status_code == 400 and response.json()["code"] == "VALIDATION_ERROR"
    assert BD_EXCHANGE_RATES_CONFIG_KEY in response.json()["data"]
    assert "Traceback" not in str(response.json())


def test_report_uses_config_metadata_and_preserves_base_eligibility_cost_and_associations(fx_context):
    c = fx_context
    version = configure(c, value={"rates": [rate_row(rate="0.2")]})
    QuerySet.update(BdSampleAttributionSnapshot.objects.filter(pk=c.sample.pk), sampled_at=instant(8, 1),
                    cost_amount=Decimal("5"), currency="CNY")
    valid = fact(c.tenant, estimated_commission_base=Decimal("123.4567"), actual_paid_commission=Decimal("0"),
                 actual_paid_shop_ads_commission=Decimal("0"))
    attribution(c, valid)
    pending = fact(c.tenant, name="synthetic-pending", settlement_status=TO_SETTLE, estimated_commission_base=Decimal("9999"))
    attribution(c, pending)
    before = (list(ExchangeRate.objects.values()), list(AffiliateOrderSnapshot.objects.values()),
              list(BdOrderAttributionSnapshot.objects.values()), list(BdSampleAttributionSnapshot.objects.values()))
    with CaptureQueriesContext(connection) as queries:
        report = build_bd_performance(tenant=c.tenant, **AUGUST)
    assert all(query["sql"].split()[0] == "SELECT" for query in queries)
    assert report["amount_basis"] == "estimated_commission_base"
    assert report["totals"]["gmv"] == "24.6913" and report["totals"]["gmv_php"] == "123.4567"
    assert report["totals"]["valid_orders"] == 1 and report["totals"]["quantity"] == 3
    assert report["totals"]["investment"] == "5.0000" and report["totals"]["roi"] == "4.9383"
    assert report["rate_source"] == "tenant_config" and report["rate_config_key"] == BD_EXCHANGE_RATES_CONFIG_KEY
    assert report["rate_config_version"] == version.version and report["rate_config_version_id"] == version.pk
    details = [detail for detail in report["rate_details"] if detail["source"] == "tenant_config"]
    assert details[0]["business_date"] == "2026-08-16" and details[0]["rate_effective_date"] == "2026-08-01"
    assert details[0]["config_version"] == version.version and details[0]["config_version_id"] == version.pk
    assert before == (list(ExchangeRate.objects.values()), list(AffiliateOrderSnapshot.objects.values()),
                      list(BdOrderAttributionSnapshot.objects.values()), list(BdSampleAttributionSnapshot.objects.values()))


def test_report_diagnostics_disclose_mixed_and_legacy_sources(fx_context):
    c = fx_context
    version = configure(c)
    ExchangeRate.objects.create(tenant=c.tenant, created_by=c.user, base_currency="MYR", quote_currency="CNY",
                                rate=Decimal("1.65"), effective_from=date(2026, 8, 1), source="synthetic")
    attribution(c, fact(c.tenant))
    attribution(c, fact(c.tenant, name="synthetic-myr", currency="MYR", site="MY"))
    report = build_bd_performance(tenant=c.tenant, **AUGUST)
    assert report["totals"]["gmv"] == "190.0000" and report["rate_source"] == "mixed"
    assert report["rate_config_version"] == version.version and report["rate_config_version_id"] == version.pk
    assert {detail["source"] for detail in report["rate_details"] if detail["source"] != "identity"} == {"tenant_config", "tenant_exchange_rate"}
    reset = configure(c, value={"rates": []})
    report = build_bd_performance(tenant=c.tenant, **AUGUST)
    assert report["totals"]["gmv"] == "177.5000" and report["rate_source"] == "tenant_exchange_rate"
    assert report["rate_config_version"] == reset.version and report["rate_config_version_id"] == reset.pk
    assert {detail["fallback_reason"] for detail in report["rate_details"] if detail["source"] != "identity"} == {"empty_schedule"}


@pytest.mark.parametrize("field,value", [
    ("scope_type", "system"), ("value_type", "string"), ("is_sensitive", True), ("requires_approval", True),
])
@pytest.mark.parametrize("stage", ["create", "approve", "activate", "rollback", "report"])
def test_malformed_definition_cannot_bypass_approval_or_live_read(fx_context, field, value, stage):
    c = fx_context
    grant(c.user, "config.system.manage")
    grant(c.approver, "config.system.manage")
    due = timezone.now() + timedelta(hours=1)
    version = configure(c, effective_at=due if stage == "activate" else None, approve=stage != "approve")
    SystemConfigDefinition.objects.filter(pk=c.definition.pk).update(**{field: value})
    before = (TenantConfigVersion.objects.count(), ConfigChangeLog.objects.count())
    expected = APIValidationError if stage == "report" else ValidationError
    if stage == "activate":
        assert activate_due_config_versions(now=due, config_key=BD_EXCHANGE_RATES_CONFIG_KEY) == {"activated": 0, "superseded": 0, "invalid": 1}
        assert (TenantConfigVersion.objects.count(), ConfigChangeLog.objects.count()) == before
        return
    with pytest.raises(expected):
        if stage == "create":
            configure(c)
        elif stage == "approve":
            approve_config_version(version=version, actor=c.approver)
        elif stage == "rollback":
            rollback_config_version(target_version=version, actor=c.user)
        else:
            _RateResolver(c.tenant)
    assert (TenantConfigVersion.objects.count(), ConfigChangeLog.objects.count()) == before


@pytest.mark.parametrize("approval", [None, "creator"])
def test_live_fx_does_not_require_separate_approval(fx_context, approval):
    c = fx_context
    version = configure(c)
    corrupt(version, approved_by_id=c.user.pk if approval == "creator" else None)
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.25")


def test_direct_save_is_effective_without_approve_permission_and_ignores_activation_time(fx_context):
    c = fx_context
    manager = create_user(c.tenant, "synthetic-direct-fx-manager")
    grant(manager, "config.manage")
    before = timezone.now()
    response = client_for(manager).post("/api/internal/config/values/", {
        "config_key": BD_EXCHANGE_RATES_CONFIG_KEY, "value": {"rates": [rate_row()]},
        "effective_at": (before + timedelta(days=10)).isoformat(),
    }, format="json")
    assert response.status_code == 201
    saved = TenantConfigVersion.objects.get(tenant=c.tenant, config_key=BD_EXCHANGE_RATES_CONFIG_KEY)
    assert saved.status == TenantConfigVersion.Status.EFFECTIVE and saved.approved_by_id is None
    assert before <= saved.effective_at <= timezone.now()
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.25")
    assert ConfigChangeLog.objects.filter(config_key=BD_EXCHANGE_RATES_CONFIG_KEY).count() == 1
    assert not ConfigChangeLog.objects.filter(config_key=BD_EXCHANGE_RATES_CONFIG_KEY, action="approve").exists()


def test_edit_and_delete_preserve_versions_and_never_mutate_business_facts(fx_context):
    c = fx_context
    facts_before = (list(ExchangeRate.objects.values()), list(AffiliateOrderSnapshot.objects.values()),
                    list(BdSampleAttributionSnapshot.objects.values()), list(BdOrderAttributionSnapshot.objects.values()))
    first = configure(c, value={"rates": [rate_row(), rate_row(rate="0.4", currency="MYR")]})
    second = configure(c, value={"rates": [rate_row(rate="0.3")]})
    assert second.status == TenantConfigVersion.Status.EFFECTIVE
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.3")
    reset = configure(c, value={"rates": []})
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.value == {"rates": [rate_row(), rate_row(rate="0.4", currency="MYR")]}
    assert second.value == {"rates": [rate_row(rate="0.3")]}
    assert first.status == second.status == TenantConfigVersion.Status.SUPERSEDED
    assert reset.value == {"rates": []} and reset.status == TenantConfigVersion.Status.EFFECTIVE
    assert TenantConfigVersion.objects.filter(config_key=BD_EXCHANGE_RATES_CONFIG_KEY).count() == 3
    assert _RateResolver(c.tenant).to_cny("PHP", date(2026, 8, 16))[0] == Decimal("0.125")
    assert facts_before == (list(ExchangeRate.objects.values()), list(AffiliateOrderSnapshot.objects.values()),
                            list(BdSampleAttributionSnapshot.objects.values()), list(BdOrderAttributionSnapshot.objects.values()))


def test_direct_save_migration_changes_only_definition_and_does_not_activate_pending(fx_context):
    c = fx_context
    configure(c, approve=False)
    c.definition.requires_approval = True
    c.definition.save()
    versions_before = list(TenantConfigVersion.objects.values())
    logs_before = list(ConfigChangeLog.objects.values())
    other_before = list(SystemConfigDefinition.objects.exclude(config_key=BD_EXCHANGE_RATES_CONFIG_KEY).values())
    module = import_module("apps.influencers.migrations.0037_bd_exchange_rates_direct_save")
    with CaptureQueriesContext(connection) as queries:
        editor = SimpleNamespace(connection=connection)
        module.disable_bd_exchange_rate_approval(apps, editor)
        module.disable_bd_exchange_rate_approval(apps, editor)
    c.definition.refresh_from_db()
    assert not c.definition.requires_approval
    assert versions_before == list(TenantConfigVersion.objects.values())
    assert logs_before == list(ConfigChangeLog.objects.values())
    assert other_before == list(SystemConfigDefinition.objects.exclude(config_key=BD_EXCHANGE_RATES_CONFIG_KEY).values())
    writes = [q["sql"] for q in queries if q["sql"].split()[0] in {"INSERT", "UPDATE", "DELETE"}]
    assert writes and all('"configcenter_systemconfigdefinition"' in sql for sql in writes)


@pytest.mark.parametrize("rate,expected", [
    ("9999999999.9999999999", "9999999999999999999900000.0000"),
    ("0.0000000001", "100000.0000"),
])
def test_allowed_fx_extremes_render_large_safe_source_amount_without_500(fx_context, rate, expected):
    c = fx_context
    configure(c, value={"rates": [rate_row(rate=rate)]})
    # This exact integer is safe in SQLite and within the source Decimal(20,4).
    attribution(c, fact(c.tenant, estimated_commission_base=Decimal("1000000000000000.0000")))
    response = client_for(c.user).get("/api/internal/influencers/bd-performance/", {
        "start_date": "2026-08-01", "end_date": "2026-08-31",
    })
    assert response.status_code == 200
    assert response.json()["data"]["totals"]["gmv"] == expected
    assert response.json()["data"]["totals"]["roi"] is None
    resolver = _RateResolver(c.tenant)
    with CaptureQueriesContext(connection) as queries:
        converted, _ = resolver.convert(Decimal("9999999999999999.9999"), "PHP", "CNY", date(2026, 8, 16))
    assert len(queries) == 0
    with localcontext() as context:
        context.prec = 80
        assert converted == Decimal("9999999999999999.9999") * Decimal(rate)
