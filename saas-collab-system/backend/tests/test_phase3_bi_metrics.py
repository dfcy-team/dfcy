from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.permissions.services import check_user_permission
from apps.reports.models import (
    MetricAggregate,
    MetricAggregateLineage,
    MetricDataPoint,
    MetricDataPointQuerySet,
    MetricDefinition,
)
from apps.reports.services import (
    MAX_LINEAGE_VALUES,
    aggregate_metric,
    create_metric_definition,
    create_metric_definition_version,
    deactivate_metric_definition,
    upsert_metric_data_point,
)
from apps.tenants.models import Tenant


def create_user(tenant, username, user_type=CustomUser.UserType.INTERNAL):
    return CustomUser.objects.create_user(username=username, tenant=tenant, user_type=user_type)


def grant_analytics_permission(user, permission_code, scope_type=DataScope.ScopeType.ALL, scope_config=None):
    role = Role.objects.create(
        tenant=user.tenant,
        name=f"Analytics {permission_code} {user.id}",
        code=f"analytics-{permission_code.replace('.', '-')}-{user.id}",
    )
    permission = Permission.objects.get(code=permission_code)
    role.permissions.add(permission)
    UserRole.objects.create(tenant=user.tenant, user=user, role=role)
    DataScope.objects.create(
        tenant=user.tenant,
        role=role,
        scope_type=scope_type,
        config=scope_config or {},
    )


def authenticated_client(user):
    client = APIClient()
    client.force_authenticate(user=user)
    return client


def create_definition(
    tenant,
    code="BI_SALES_AMOUNT",
    version=1,
    aggregation_method=MetricDefinition.AggregationMethod.SUM,
    permission_code="analytics.view",
    contains_sensitive_data=False,
    allowed_dimensions=None,
    missing_data_policy=MetricDefinition.MissingDataPolicy.MARK_MISSING,
    minimum_quality_rate=Decimal("1.0000"),
    actor=None,
):
    actor = actor or create_user(
        tenant,
        f"definition-creator-{tenant.id}-{CustomUser.objects.count() + 1}",
    )
    if not check_user_permission(actor, "analytics.manage"):
        grant_analytics_permission(actor, "analytics.manage")
    fields = {
        "metric_code": code,
        "name": "Demo sales amount",
        "formula": "sum(valid demo sales facts)",
        "aggregation_method": aggregation_method,
        "source_tables": ["demo_sales_fact"],
        "supported_granularities": [MetricAggregate.Granularity.DAY, MetricAggregate.Granularity.MONTH],
        "allowed_dimensions": (["platform", "shop"] if allowed_dimensions is None else allowed_dimensions),
        "allow_drill_down": True,
        "permission_code": permission_code,
        "contains_sensitive_data": contains_sensitive_data,
        "missing_data_policy": missing_data_policy,
        "minimum_quality_rate": minimum_quality_rate,
    }
    if version != 1:
        fields["version"] = version
    return create_metric_definition(
        tenant=tenant,
        actor=actor,
        reason="Create a demo metric definition for tests.",
        **fields,
    )


def create_point(definition, record_id, value, occurred_at, **kwargs):
    return MetricDataPoint.objects.create(
        tenant=kwargs.pop("tenant", definition.tenant),
        metric_definition=definition,
        source_table="demo_sales_fact",
        source_batch=kwargs.pop("source_batch", "demo-batch-001"),
        source_record_id=record_id,
        calculation_task=kwargs.pop("calculation_task", "demo-task-001"),
        occurred_at=occurred_at,
        dimensions=kwargs.pop("dimensions", {"platform": "mock", "shop": "demo-shop"}),
        numeric_value=value,
        quality_status=kwargs.pop("quality_status", MetricDataPoint.QualityStatus.PASSED),
        **kwargs,
    )


@pytest.mark.django_db
def test_metric_definition_is_versioned_and_cannot_enable_automated_decisions():
    tenant = Tenant.objects.create(name="Tenant", code="bi-definition")
    actor = create_user(tenant, "metric-version-actor")
    grant_analytics_permission(actor, "analytics.manage")
    first = create_definition(tenant)
    second = create_metric_definition_version(
        first,
        actor=actor,
        reason="Add version two description.",
        description="version two",
    )

    assert first.metric_code == second.metric_code
    assert second.version == 2
    assert second.allows_automated_decision is False


@pytest.mark.django_db
def test_metric_version_chain_has_one_active_latest_version():
    tenant = Tenant.objects.create(name="Tenant", code="bi-version-chain")
    actor = create_user(tenant, "version-chain-actor")
    grant_analytics_permission(actor, "analytics.manage")
    first = create_definition(tenant)
    second = create_metric_definition_version(
        first,
        actor=actor,
        reason="Update the formula.",
        formula="version two",
    )

    with pytest.raises(ValidationError):
        create_metric_definition_version(
            first,
            actor=actor,
            reason="Attempt a stale fork.",
            formula="stale fork",
        )
    with pytest.raises(ValidationError):
        create_definition(tenant, version=3)
    with pytest.raises(ValidationError):
        MetricDefinition.objects.bulk_create(
            [
                MetricDefinition(
                    tenant=tenant,
                    metric_code="BI_BULK",
                    name="Bulk metric",
                    formula="bulk",
                    aggregation_method=MetricDefinition.AggregationMethod.SUM,
                    source_tables=["demo_sales_fact"],
                    supported_granularities=[MetricAggregate.Granularity.DAY],
                    allowed_dimensions=[],
                )
            ]
        )

    first.refresh_from_db()
    first.status = MetricDefinition.Status.ACTIVE
    with pytest.raises(ValidationError):
        first.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        MetricDefinition.objects.filter(pk=first.pk).update(status=MetricDefinition.Status.ACTIVE)

    active_versions = MetricDefinition.objects.filter(
        tenant=tenant,
        metric_code=first.metric_code,
        status=MetricDefinition.Status.ACTIVE,
    )
    assert list(active_versions.values_list("id", flat=True)) == [second.id]
    audit = OperationLog.objects.get(
        tenant=tenant,
        module="analytics",
        action="metric_definition.create_version",
    )
    assert audit.user == actor
    assert audit.before_data["definition"]["version"] == 1
    assert audit.after_data["definition"]["version"] == 2
    assert audit.after_data["reason"] == "Update the formula."


@pytest.mark.django_db
def test_stale_definition_object_cannot_aggregate_after_new_version_is_created():
    tenant = Tenant.objects.create(name="Tenant", code="bi-stale-aggregate")
    actor = create_user(tenant, "stale-aggregate-actor")
    grant_analytics_permission(actor, "analytics.manage")
    definition = create_definition(tenant, actor=actor)
    now = timezone.now()
    create_point(definition, "stale-version-point", Decimal("10"), now)

    create_metric_definition_version(
        definition,
        actor=actor,
        reason="Replace the stale aggregation definition.",
        formula="version two formula",
    )

    assert definition.status == MetricDefinition.Status.ACTIVE
    assert MetricDefinition.objects.get(pk=definition.pk).status == MetricDefinition.Status.INACTIVE
    with pytest.raises(ValidationError, match="Only active metric definitions"):
        aggregate_metric(
            tenant=tenant,
            metric_definition=definition,
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(hours=1),
            granularity=MetricAggregate.Granularity.DAY,
        )
    assert MetricAggregate.objects.count() == 0


@pytest.mark.django_db
def test_metric_definition_allows_no_drill_down_dimensions():
    tenant = Tenant.objects.create(name="Tenant", code="bi-no-dimensions")

    definition = create_definition(tenant, allowed_dimensions=[])

    assert definition.allowed_dimensions == []


@pytest.mark.django_db
def test_metric_version_audit_requires_same_tenant_internal_actor_and_reason():
    tenant = Tenant.objects.create(name="Tenant", code="bi-version-audit")
    other_tenant = Tenant.objects.create(name="Other", code="bi-version-audit-other")
    definition = create_definition(tenant)
    other_actor = create_user(other_tenant, "other-version-actor")
    external_actor = create_user(tenant, "external-version-actor", CustomUser.UserType.EXTERNAL)
    unauthorized_actor = create_user(tenant, "unauthorized-version-actor")
    grant_analytics_permission(other_actor, "analytics.manage")

    with pytest.raises(ValidationError):
        create_metric_definition_version(definition, actor=other_actor, reason="Wrong tenant.", formula="v2")
    with pytest.raises(ValidationError):
        create_metric_definition_version(definition, actor=external_actor, reason="Wrong type.", formula="v2")
    with pytest.raises(ValidationError):
        create_metric_definition_version(definition, actor=unauthorized_actor, reason="No permission.", formula="v2")
    with pytest.raises(ValidationError):
        create_metric_definition_version(definition, actor=create_user(tenant, "no-reason"), reason="", formula="v2")

    assert OperationLog.objects.filter(action="metric_definition.create_version").count() == 0


@pytest.mark.django_db
def test_metric_definition_create_and_deactivate_require_audited_services():
    tenant = Tenant.objects.create(name="Tenant", code="bi-definition-lifecycle")
    actor = create_user(tenant, "definition-lifecycle-actor")
    grant_analytics_permission(actor, "analytics.manage")
    definition = create_definition(tenant, actor=actor)

    with pytest.raises(ValidationError):
        MetricDefinition.objects.create(
            tenant=tenant,
            metric_code="BI_DIRECT",
            name="Direct",
            formula="direct",
            aggregation_method=MetricDefinition.AggregationMethod.SUM,
            source_tables=["demo_sales_fact"],
            supported_granularities=[MetricAggregate.Granularity.DAY],
            allowed_dimensions=[],
        )
    definition.status = MetricDefinition.Status.INACTIVE
    with pytest.raises(ValidationError):
        definition.save(update_fields=["status"])
    with pytest.raises(ValidationError):
        MetricDefinition.objects.filter(pk=definition.pk).update(status=MetricDefinition.Status.INACTIVE)

    definition = deactivate_metric_definition(
        definition,
        actor=actor,
        reason="Retire the demo metric.",
    )

    assert definition.status == MetricDefinition.Status.INACTIVE
    create_audit = OperationLog.objects.get(action="metric_definition.create", object_id=str(definition.id))
    deactivate_audit = OperationLog.objects.get(action="metric_definition.deactivate", object_id=str(definition.id))
    assert create_audit.user == actor
    assert deactivate_audit.user == actor
    assert deactivate_audit.after_data["reason"] == "Retire the demo metric."


@pytest.mark.django_db
def test_metric_data_point_rejects_cross_tenant_definition_and_unknown_source():
    tenant = Tenant.objects.create(name="Tenant", code="bi-source-a")
    other_tenant = Tenant.objects.create(name="Other", code="bi-source-b")
    definition = create_definition(tenant)
    occurred_at = timezone.now()

    with pytest.raises(ValidationError):
        create_point(definition, "cross-tenant", 1, occurred_at, tenant=other_tenant)

    unknown_source = MetricDataPoint(
        tenant=tenant,
        metric_definition=definition,
        source_table="unknown_table",
        source_batch="demo-batch",
        source_record_id="unknown-source",
        occurred_at=occurred_at,
        numeric_value=1,
        quality_status=MetricDataPoint.QualityStatus.PASSED,
    )
    with pytest.raises(ValidationError):
        unknown_source.save()

    assert MetricDataPoint.objects.count() == 0
    valid = create_point(definition, "valid-owner", 1, occurred_at)
    with pytest.raises(ValidationError):
        MetricDataPoint.objects.filter(pk=valid.pk).update(tenant=other_tenant)
    valid.refresh_from_db()
    assert valid.tenant_id == tenant.id


@pytest.mark.django_db
def test_aggregation_excludes_cross_tenant_failed_missing_and_expired_points():
    tenant = Tenant.objects.create(name="Tenant", code="bi-aggregate-a")
    other_tenant = Tenant.objects.create(name="Other", code="bi-aggregate-b")
    definition = create_definition(tenant)
    now = timezone.now()
    period_start = now - timedelta(hours=1)
    period_end = now + timedelta(hours=1)
    dimensions = {"platform": "mock", "shop": "demo-shop"}

    create_point(definition, "valid-1", Decimal("10.00"), now)
    create_point(definition, "valid-2", Decimal("20.00"), now)
    create_point(
        definition,
        "failed",
        Decimal("1000.00"),
        now,
        quality_status=MetricDataPoint.QualityStatus.FAILED,
    )
    create_point(
        definition,
        "missing",
        None,
        now,
        quality_status=MetricDataPoint.QualityStatus.MISSING,
    )
    create_point(definition, "expired", Decimal("1000.00"), now, expires_at=now - timedelta(seconds=1))
    with pytest.raises(ValidationError):
        create_point(definition, "cross-tenant", Decimal("1000.00"), now, tenant=other_tenant)

    aggregate = aggregate_metric(
        tenant=tenant,
        metric_definition=definition,
        period_start=period_start,
        period_end=period_end,
        granularity=MetricAggregate.Granularity.DAY,
        dimensions=dimensions,
        refreshed_at=now,
    )

    assert aggregate.numeric_value == Decimal("30.00")
    assert aggregate.valid_point_count == 2
    assert aggregate.excluded_point_count == 3
    assert aggregate.quality_status == MetricAggregate.QualityStatus.DEGRADED
    assert aggregate.is_formal is False
    assert aggregate.definition_version == definition.version
    expected_watermark = (
        MetricDataPoint.objects.filter(tenant=tenant, metric_definition=definition)
        .order_by("-id")
        .values_list("id", flat=True)
        .first()
    )
    assert aggregate.quality_detail == {
        "total_count": 5,
        "passed_value_count": 2,
        "missing_count": 1,
        "failed_count": 1,
        "expired_count": 1,
        "zero_filled_count": 0,
        "excluded_count": 3,
        "quality_rate": "0.4000",
        "minimum_quality_rate": "1.0000",
        "missing_data_policy": "mark_missing",
        "source_watermark_id": expected_watermark,
    }
    expected_ids = list(
        MetricDataPoint.objects.filter(source_record_id__in=["valid-1", "valid-2"])
        .order_by("id")
        .values_list("id", flat=True)
    )
    assert aggregate.source_lineage == {
        "source_tables": ["demo_sales_fact"],
        "source_table_count": 1,
        "source_batches": ["demo-batch-001"],
        "source_batch_count": 1,
        "calculation_tasks": ["demo-task-001"],
        "calculation_task_count": 1,
        "data_point_count": 2,
        "source_watermark_id": expected_watermark,
        "first_data_point_id": expected_ids[0],
        "last_data_point_id": expected_ids[-1],
    }
    assert aggregate.lineage_records.count() == 1


@pytest.mark.django_db
def test_aggregation_uses_one_materialized_source_snapshot():
    tenant = Tenant.objects.create(name="Tenant", code="bi-source-snapshot")
    definition = create_definition(tenant)
    now = timezone.now()
    point = create_point(definition, "snapshot-point", Decimal("10"), now)
    original_iter = MetricDataPointQuerySet.__iter__
    mutation = {"done": False}

    def materialize_then_mutate(queryset):
        rows = list(original_iter(queryset))
        if not mutation["done"]:
            mutation["done"] = True
            MetricDataPoint.objects.filter(pk=point.pk).update(
                quality_status=MetricDataPoint.QualityStatus.FAILED,
                numeric_value=None,
            )
        return iter(rows)

    with patch.object(MetricDataPointQuerySet, "__iter__", materialize_then_mutate):
        aggregate = aggregate_metric(
            tenant=tenant,
            metric_definition=definition,
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(hours=1),
            granularity=MetricAggregate.Granularity.DAY,
        )

    point.refresh_from_db()
    assert point.quality_status == MetricDataPoint.QualityStatus.FAILED
    assert aggregate.numeric_value == Decimal("10")
    assert aggregate.valid_point_count == 1
    assert aggregate.quality_status == MetricAggregate.QualityStatus.PASSED
    assert aggregate.is_formal is True
    assert aggregate.lineage_records.count() == 1


@pytest.mark.django_db
def test_zero_fill_policy_is_applied_and_recorded():
    tenant = Tenant.objects.create(name="Tenant", code="bi-zero-fill")
    definition = create_definition(
        tenant,
        missing_data_policy=MetricDefinition.MissingDataPolicy.ZERO_FILL,
    )
    now = timezone.now()
    create_point(definition, "valid", 10, now)
    create_point(
        definition,
        "missing",
        None,
        now,
        quality_status=MetricDataPoint.QualityStatus.MISSING,
    )

    aggregate = aggregate_metric(
        tenant=tenant,
        metric_definition=definition,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
        granularity=MetricAggregate.Granularity.DAY,
        dimensions={"platform": "mock", "shop": "demo-shop"},
    )

    assert aggregate.numeric_value == Decimal("10")
    assert aggregate.valid_point_count == 2
    assert aggregate.excluded_point_count == 0
    assert aggregate.quality_status == MetricAggregate.QualityStatus.PASSED
    assert aggregate.is_formal is True
    assert aggregate.quality_detail["zero_filled_count"] == 1
    assert aggregate.lineage_records.count() == 1


@pytest.mark.django_db
def test_repeated_source_record_across_batches_is_upserted_not_double_counted():
    tenant = Tenant.objects.create(name="Tenant", code="bi-source-idempotency")
    definition = create_definition(
        tenant,
        code="BI_ORDER_COUNT",
        aggregation_method=MetricDefinition.AggregationMethod.COUNT,
    )
    now = timezone.now()
    common = {
        "tenant": tenant,
        "metric_definition": definition,
        "source_table": "demo_sales_fact",
        "source_record_id": "same-order",
        "occurred_at": now,
        "dimensions": {"platform": "mock", "shop": "demo-shop"},
        "numeric_value": 1,
        "quality_status": MetricDataPoint.QualityStatus.PASSED,
    }

    first, first_created = upsert_metric_data_point(**common, source_batch="batch-1")
    second, second_created = upsert_metric_data_point(**common, source_batch="batch-2")
    aggregate = aggregate_metric(
        tenant=tenant,
        metric_definition=definition,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
        granularity=MetricAggregate.Granularity.DAY,
        dimensions={"platform": "mock", "shop": "demo-shop"},
    )

    assert first_created is True
    assert second_created is False
    assert first.id == second.id
    assert MetricDataPoint.objects.count() == 1
    assert second.source_batch == "batch-2"
    assert aggregate.numeric_value == Decimal("1")


@pytest.mark.django_db
def test_metric_definition_requires_new_version_for_semantic_changes():
    tenant = Tenant.objects.create(name="Tenant", code="bi-version-immutability")
    actor = create_user(tenant, "version-immutability-actor")
    grant_analytics_permission(actor, "analytics.manage")
    definition = create_definition(tenant)

    definition.formula = "changed in place"
    with pytest.raises(ValidationError):
        definition.save()
    with pytest.raises(ValidationError):
        MetricDefinition.objects.filter(pk=definition.pk).update(formula="queryset bypass")

    new_definition = create_metric_definition_version(
        definition,
        actor=actor,
        reason="Create a new formula version.",
        formula="version two formula",
    )
    definition.refresh_from_db()

    assert definition.status == MetricDefinition.Status.INACTIVE
    assert new_definition.version == 2
    assert new_definition.formula == "version two formula"


@pytest.mark.django_db
def test_aggregation_is_idempotent_and_rejects_foreign_definition():
    tenant = Tenant.objects.create(name="Tenant", code="bi-idempotent-a")
    other_tenant = Tenant.objects.create(name="Other", code="bi-idempotent-b")
    definition = create_definition(tenant)
    foreign_definition = create_definition(other_tenant)
    now = timezone.now()
    create_point(definition, "valid", 5, now)
    arguments = {
        "tenant": tenant,
        "metric_definition": definition,
        "period_start": now - timedelta(hours=1),
        "period_end": now + timedelta(hours=1),
        "granularity": MetricAggregate.Granularity.DAY,
        "dimensions": {"platform": "mock", "shop": "demo-shop"},
    }

    first = aggregate_metric(**arguments)
    second = aggregate_metric(**arguments)

    assert first.id == second.id
    assert MetricAggregate.objects.count() == 1
    with pytest.raises(ValidationError):
        aggregate_metric(**{**arguments, "metric_definition": foreign_definition})


@pytest.mark.django_db
def test_quality_failure_is_recorded_but_not_exposed_as_formal_aggregate():
    tenant = Tenant.objects.create(name="Tenant", code="bi-no-valid-data")
    viewer = create_user(tenant, "viewer-no-valid-data")
    grant_analytics_permission(viewer, "analytics.view")
    definition = create_definition(tenant)
    now = timezone.now()
    create_point(
        definition,
        "failed-only",
        100,
        now,
        quality_status=MetricDataPoint.QualityStatus.FAILED,
    )
    aggregate = aggregate_metric(
        tenant=tenant,
        metric_definition=definition,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
        granularity=MetricAggregate.Granularity.DAY,
        dimensions={"platform": "mock", "shop": "demo-shop"},
    )

    response = authenticated_client(viewer).get("/api/internal/analytics/aggregates/")

    assert aggregate.quality_status == MetricAggregate.QualityStatus.NO_VALID_DATA
    assert aggregate.is_formal is False
    assert response.status_code == 200
    assert response.json()["data"]["items"] == []
    with pytest.raises(ValidationError):
        MetricAggregate.objects.filter(pk=aggregate.pk).update(is_formal=True)


@pytest.mark.django_db
def test_analytics_api_enforces_tenant_permission_type_and_standard_response():
    tenant = Tenant.objects.create(name="Tenant", code="bi-api-a")
    other_tenant = Tenant.objects.create(name="Other", code="bi-api-b")
    viewer = create_user(tenant, "analytics-viewer")
    plain_internal = create_user(tenant, "plain-internal")
    external = create_user(tenant, "external", CustomUser.UserType.EXTERNAL)
    rpa = create_user(tenant, "rpa", CustomUser.UserType.RPA)
    grant_analytics_permission(viewer, "analytics.view")
    visible = create_definition(tenant)
    create_definition(other_tenant)

    response = authenticated_client(viewer).get("/api/internal/analytics/metrics/")

    assert response.status_code == 200
    assert response.json() == {
        "success": True,
        "code": "OK",
        "message": "success",
        "data": {
            "items": [MetricDefinitionSerializerForTest(visible)],
            "pagination": {"page": 1, "page_size": 50, "total": 1, "total_pages": 1},
        },
    }
    assert APIClient().get("/api/internal/analytics/metrics/").status_code == 401
    assert authenticated_client(plain_internal).get("/api/internal/analytics/metrics/").status_code == 403
    assert authenticated_client(external).get("/api/internal/analytics/metrics/").status_code == 403
    assert authenticated_client(rpa).get("/api/internal/analytics/metrics/").status_code == 403


def MetricDefinitionSerializerForTest(definition):
    from apps.reports.serializers import MetricDefinitionSerializer

    return MetricDefinitionSerializer(definition).data


@pytest.mark.django_db
def test_view_only_permission_cannot_run_mock_aggregation():
    tenant = Tenant.objects.create(name="Tenant", code="bi-view-only")
    viewer = create_user(tenant, "viewer")
    grant_analytics_permission(viewer, "analytics.view")
    definition = create_definition(tenant)
    now = timezone.now()
    create_point(definition, "demo", 10, now)

    response = authenticated_client(viewer).post(
        "/api/internal/analytics/aggregate-mock/",
        {
            "metric_code": definition.metric_code,
            "granularity": "day",
            "period_start": (now - timedelta(hours=1)).isoformat(),
            "period_end": (now + timedelta(hours=1)).isoformat(),
            "dimensions": {"platform": "mock", "shop": "demo-shop"},
        },
        format="json",
    )

    assert response.status_code == 403
    assert MetricAggregate.objects.count() == 0


@pytest.mark.django_db
def test_finance_metric_requires_independent_finance_permission():
    tenant = Tenant.objects.create(name="Tenant", code="bi-finance-permission")
    analytics_viewer = create_user(tenant, "analytics-only")
    finance_viewer = create_user(tenant, "analytics-finance")
    grant_analytics_permission(analytics_viewer, "analytics.view")
    grant_analytics_permission(finance_viewer, "analytics.view")
    grant_analytics_permission(finance_viewer, "finance.view")
    create_definition(tenant)
    create_definition(
        tenant,
        code="BI_FINANCE_DIFFERENCE",
        permission_code="finance.view",
        contains_sensitive_data=True,
    )

    analytics_response = authenticated_client(analytics_viewer).get("/api/internal/analytics/metrics/")
    finance_response = authenticated_client(finance_viewer).get("/api/internal/analytics/metrics/")

    assert [item["metric_code"] for item in analytics_response.json()["data"]["items"]] == ["BI_SALES_AMOUNT"]
    assert {item["metric_code"] for item in finance_response.json()["data"]["items"]} == {
        "BI_SALES_AMOUNT",
        "BI_FINANCE_DIFFERENCE",
    }


@pytest.mark.django_db
def test_calculator_can_run_mock_aggregation_within_custom_data_scope_only():
    tenant = Tenant.objects.create(name="Tenant", code="bi-custom-scope")
    calculator = create_user(tenant, "calculator")
    grant_analytics_permission(
        calculator,
        "analytics.calculate",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"analytics_dimensions": [{"platform": "mock"}]},
    )
    grant_analytics_permission(
        calculator,
        "analytics.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"analytics_dimensions": [{"platform": "mock"}]},
    )
    definition = create_definition(tenant)
    now = timezone.now()
    create_point(definition, "demo", 10, now)
    client = authenticated_client(calculator)
    payload = {
        "metric_code": definition.metric_code,
        "granularity": "day",
        "period_start": (now - timedelta(hours=1)).isoformat(),
        "period_end": (now + timedelta(hours=1)).isoformat(),
        "dimensions": {"platform": "mock", "shop": "demo-shop"},
    }

    allowed = client.post("/api/internal/analytics/aggregate-mock/", payload, format="json")
    denied = client.post(
        "/api/internal/analytics/aggregate-mock/",
        {**payload, "dimensions": {"platform": "shopee", "shop": "demo-shop"}},
        format="json",
    )

    assert allowed.status_code == 200
    assert allowed.json()["data"]["numeric_value"] == "10.0000"
    assert denied.status_code == 403


@pytest.mark.django_db
def test_aggregate_list_applies_tenant_and_custom_dimension_scope():
    tenant = Tenant.objects.create(name="Tenant", code="bi-list-scope")
    viewer = create_user(tenant, "scoped-viewer")
    grant_analytics_permission(
        viewer,
        "analytics.view",
        scope_type=DataScope.ScopeType.CUSTOM,
        scope_config={"analytics_dimensions": [{"platform": "mock"}]},
    )
    definition = create_definition(tenant)
    now = timezone.now()
    for platform, value in (("mock", 10), ("shopee", 20)):
        create_point(
            definition,
            platform,
            value,
            now,
            dimensions={"platform": platform, "shop": "demo-shop"},
        )
        aggregate_metric(
            tenant=tenant,
            metric_definition=definition,
            period_start=now - timedelta(hours=1),
            period_end=now + timedelta(hours=1),
            granularity=MetricAggregate.Granularity.DAY,
            dimensions={"platform": platform, "shop": "demo-shop"},
        )

    response = authenticated_client(viewer).get("/api/internal/analytics/aggregates/")

    assert response.status_code == 200
    assert len(response.json()["data"]["items"]) == 1
    assert response.json()["data"]["items"][0]["dimensions"]["platform"] == "mock"
    assert "credential" not in str(response.json()).lower()


@pytest.mark.django_db
def test_lineage_and_api_pages_are_bounded():
    tenant = Tenant.objects.create(name="Tenant", code="bi-bounded-output")
    viewer = create_user(tenant, "bounded-viewer")
    grant_analytics_permission(viewer, "analytics.view")
    definition = create_definition(tenant)
    now = timezone.now()
    for index in range(MAX_LINEAGE_VALUES + 1):
        create_point(
            definition,
            f"record-{index}",
            1,
            now,
            source_batch=f"batch-{index:03d}",
            calculation_task=f"task-{index:03d}",
        )
    aggregate = aggregate_metric(
        tenant=tenant,
        metric_definition=definition,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
        granularity=MetricAggregate.Granularity.DAY,
        dimensions={"platform": "mock", "shop": "demo-shop"},
    )

    response = authenticated_client(viewer).get("/api/internal/analytics/aggregates/?page_size=101")

    assert len(aggregate.source_lineage["source_batches"]) == MAX_LINEAGE_VALUES
    assert aggregate.source_lineage["source_batch_count"] == MAX_LINEAGE_VALUES + 1
    assert aggregate.source_lineage["data_point_count"] == MAX_LINEAGE_VALUES + 1
    assert "data_point_ids" not in aggregate.source_lineage
    assert MetricAggregateLineage.objects.filter(aggregate=aggregate).count() == MAX_LINEAGE_VALUES + 1
    assert MetricAggregateLineage.objects.filter(aggregate=aggregate, source_batch="batch-100").exists()
    assert response.status_code == 400


@pytest.mark.django_db
def test_metric_aggregate_bulk_create_cannot_bypass_tenant_validation():
    tenant = Tenant.objects.create(name="Tenant", code="bi-aggregate-bulk")
    other_tenant = Tenant.objects.create(name="Other", code="bi-aggregate-bulk-other")
    definition = create_definition(tenant)
    now = timezone.now()
    invalid = MetricAggregate(
        tenant=other_tenant,
        metric_definition=definition,
        definition_version=definition.version,
        granularity=MetricAggregate.Granularity.DAY,
        period_start=now,
        period_end=now + timedelta(hours=1),
        dimensions={},
        dimensions_hash="0" * 64,
        numeric_value=1,
        valid_point_count=1,
        excluded_point_count=0,
        quality_status=MetricAggregate.QualityStatus.PASSED,
        is_formal=True,
        source_lineage={},
        refreshed_at=now,
    )

    with pytest.raises(ValidationError):
        MetricAggregate.objects.bulk_create([invalid])
    with pytest.raises(ValidationError):
        MetricAggregate.objects.create(
            tenant=tenant,
            metric_definition=definition,
            definition_version=definition.version,
            granularity=MetricAggregate.Granularity.DAY,
            period_start=now,
            period_end=now + timedelta(hours=1),
            dimensions={},
            numeric_value=999,
            valid_point_count=1,
            excluded_point_count=0,
            quality_status=MetricAggregate.QualityStatus.PASSED,
            quality_detail={"quality_rate": "1.0000"},
            is_formal=True,
            source_lineage={"source_batches": ["forged"]},
            refreshed_at=now,
        )

    assert MetricAggregate.objects.count() == 0

    create_point(definition, "service-point", 10, now)
    aggregate = aggregate_metric(
        tenant=tenant,
        metric_definition=definition,
        period_start=now - timedelta(hours=1),
        period_end=now + timedelta(hours=1),
        granularity=MetricAggregate.Granularity.DAY,
    )
    aggregate.numeric_value = 123456
    with pytest.raises(ValidationError):
        aggregate.save(update_fields=["numeric_value"])
    aggregate.refresh_from_db()
    assert aggregate.numeric_value == Decimal("10")


@pytest.mark.django_db
def test_aggregation_window_is_bounded_by_granularity():
    tenant = Tenant.objects.create(name="Tenant", code="bi-window-limit")
    definition = create_definition(tenant)
    now = timezone.now()

    with pytest.raises(ValidationError):
        aggregate_metric(
            tenant=tenant,
            metric_definition=definition,
            period_start=now - timedelta(days=2),
            period_end=now,
            granularity=MetricAggregate.Granularity.DAY,
        )
