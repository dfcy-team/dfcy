from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal
from io import StringIO
import csv

import pytest
from django.db import connection
from django.db.models.query import QuerySet
from django.test.utils import CaptureQueriesContext
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.influencers.attribution import (
    backfill_sample_attributions,
    build_bd_performance,
    create_sample_attribution_snapshot,
    refresh_order_attributions,
)
from apps.influencers.models import (
    AffiliateOrderSnapshot,
    BdOrderAttributionSnapshot,
    BdSampleAttributionSnapshot,
    Influencer,
    OutreachTask,
    SampleFulfillment,
)
from apps.masterdata.models import PlatformMaster, StoreMaster
from apps.tenants.models import Tenant


pytestmark = pytest.mark.django_db
SAMPLED_AT = datetime(2026, 8, 15, 12, tzinfo=dt_timezone.utc)


@pytest.fixture
def facts():
    tenant = Tenant.objects.create(name="Sample performance", code="sample-performance")
    owner = CustomUser.objects.create_user(
        username="sample-owner", tenant=tenant, user_type=CustomUser.UserType.INTERNAL,
    )
    task_owner = CustomUser.objects.create_user(
        username="task-owner", tenant=tenant, user_type=CustomUser.UserType.INTERNAL,
    )
    platform = PlatformMaster.objects.create(
        tenant=tenant, code="tiktok", name="TikTok", platform_type="tiktok",
    )
    store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="TK1PH", name="Sample shop",
        country_code="PH", currency="PHP",
    )
    influencer = Influencer.objects.create(
        tenant=tenant, code="creator", name="Creator", platform="tiktok", handle="creator",
    )
    task = OutreachTask.objects.create(
        tenant=tenant, task_no="SAMPLE-TASK", store=store, owner=owner,
        dispatcher=task_owner, external_product_id="P-1",
    )

    def sample(number, *, linked=True, snapshot=True, sampled_at=SAMPLED_AT):
        fulfillment = SampleFulfillment.objects.create(
            tenant=tenant, fulfillment_no=number, request_key=number, request_hash="a" * 64,
            outreach_task=task if linked else None, influencer=influencer, store=store,
            owner=owner, external_product_id="P-1", sample_sent_at=sampled_at,
            calculated_cost=Decimal("10"),
        )
        if snapshot:
            create_sample_attribution_snapshot(
                tenant=tenant, fulfillment=fulfillment, owner=owner,
                influencer=influencer, store=store,
            )
        return fulfillment

    def order(number, **overrides):
        values = {
            "tenant": tenant, "source": "demo", "source_row_key": number,
            "row_hash": "b" * 64, "data_time": SAMPLED_AT + timedelta(hours=1),
            "shop_abbr": store.code, "site": "PH", "order_id": number,
            "product_id": "P-1", "sku_id": "SKU-1", "payment_amount": Decimal("100"),
            "currency": "CNY", "quantity": 1, "order_status": "completed",
            "creator_username": influencer.handle, "actual_paid_commission": Decimal("0"),
        }
        values.update(overrides)
        return AffiliateOrderSnapshot.objects.create(**values)

    return tenant, owner, task_owner, task, sample, order


def report(tenant, mode="strict"):
    return build_bd_performance(
        tenant=tenant, start_date=SAMPLED_AT.date(), end_date=SAMPLED_AT.date(),
        attribution=mode, currency="CNY",
    )


def test_task_only_owner_does_not_enter_performance_and_task_table_is_not_queried(facts):
    tenant, _, _, _, _, _ = facts
    with CaptureQueriesContext(connection) as queries:
        result = report(tenant)
    assert result["rows"] == []
    assert result["totals"]["sample_count"] == 0
    assert not {"task_count", "outreach_tasks", "linked_count"} & result["totals"].keys()
    assert all(OutreachTask._meta.db_table not in query["sql"] for query in queries)


@pytest.mark.parametrize("mode", ["strict", "fallback"])
@pytest.mark.parametrize("task_state", ["active", "completed", "cancelled", "deleted"])
def test_task_lifecycle_dates_and_owner_do_not_gate_samples_or_orders(facts, mode, task_state):
    tenant, owner, task_owner, task, sample, order = facts
    linked = sample("LINKED")
    sample("STANDALONE", linked=False, sampled_at=SAMPLED_AT - timedelta(minutes=1))
    order("MATCHED")
    # Simulate later task changes without rewriting the frozen sample owner.
    QuerySet.update(
        OutreachTask.objects.filter(pk=task.pk),
        owner=task_owner, created_at=SAMPLED_AT - timedelta(days=90),
        status=task_state if task_state in {"completed", "cancelled"} else "pending",
        is_deleted=task_state == "deleted",
        deleted_at=SAMPLED_AT if task_state == "deleted" else None,
    )
    assert refresh_order_attributions(tenant=tenant, attribution=mode)["created"] == 1
    assert refresh_order_attributions(tenant=tenant, attribution=mode)["noop"] == 1
    attribution = BdOrderAttributionSnapshot.objects.get(tenant=tenant, rule=mode)
    assert attribution.sample_attribution.fulfillment_id == linked.pk
    assert attribution.sample_attribution.owner_id == owner.pk
    with CaptureQueriesContext(connection) as queries:
        result = report(tenant, mode)
    assert [row["owner_id"] for row in result["rows"]] == [owner.pk]
    assert result["totals"]["sample_count"] == 2
    assert result["totals"]["investment"] == "20.0000"
    assert result["totals"]["valid_order_count"] == 1
    assert result["totals"]["gmv"] == "100.0000"
    assert result["totals"]["roi"] == "5.0000"
    assert result["source_status"] == "ready"
    assert all(OutreachTask._meta.db_table not in query["sql"] for query in queries)
    assert not {"task_count", "outreach_tasks", "linked_count"} & result["rows"][0].keys()


@pytest.mark.parametrize("scoped", [True, False])
def test_backfill_includes_active_sample_under_deleted_task_and_replay_is_noop(facts, scoped):
    tenant, _, _, task, sample, order = facts
    active = sample("NEEDS-SNAPSHOT", snapshot=False)
    deleted = sample("DELETED-SAMPLE", linked=False, snapshot=False)
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=deleted.pk), is_deleted=True, deleted_at=SAMPLED_AT,
    )
    QuerySet.update(
        OutreachTask.objects.filter(pk=task.pk), is_deleted=True, deleted_at=SAMPLED_AT,
    )
    scope = {"tenant": tenant} if scoped else {}
    assert backfill_sample_attributions(**scope)["created"] == 1
    assert BdSampleAttributionSnapshot.objects.filter(fulfillment=active).exists()
    assert not BdSampleAttributionSnapshot.objects.filter(fulfillment=deleted).exists()
    replay = backfill_sample_attributions(**scope)
    assert replay["created"] == 0
    assert replay["existing"] == 1
    order("BACKFILLED")
    assert refresh_order_attributions(tenant=tenant)["created"] == 1
    assert report(tenant)["source_status"] == "ready"


def test_deleted_samples_stay_excluded_and_report_and_refresh_are_tenant_isolated(facts):
    tenant, _, _, _, sample, order = facts
    fulfillment = sample("TO-DELETE")
    order("TO-DELETE-ORDER")
    assert refresh_order_attributions(tenant=tenant)["created"] == 1
    other = Tenant.objects.create(name="Other performance", code="other-performance")
    assert refresh_order_attributions(tenant=other)["created"] == 0
    assert report(other)["rows"] == []
    QuerySet.update(
        SampleFulfillment.objects.filter(pk=fulfillment.pk), is_deleted=True, deleted_at=SAMPLED_AT,
    )
    assert report(tenant)["totals"]["sample_count"] == 0
    assert report(tenant)["totals"]["gmv"] == "0.0000"
    assert refresh_order_attributions(tenant=tenant)["deleted"] == 1
    assert not BdOrderAttributionSnapshot.objects.filter(tenant=tenant).exists()


def test_current_orders_can_use_older_samples_without_current_period_investment(facts):
    tenant, owner, _, _, sample, order = facts
    sample("OLDER-SAMPLE", linked=False, sampled_at=SAMPLED_AT - timedelta(days=45))
    order("CURRENT-ORDER")
    assert refresh_order_attributions(tenant=tenant)["created"] == 1
    result = report(tenant)
    assert [row["owner_id"] for row in result["rows"]] == [owner.pk]
    assert result["totals"]["sample_count"] == 0
    assert result["totals"]["investment"] == "0.0000"
    assert result["totals"]["valid_order_count"] == 1
    assert result["totals"]["gmv"] == "100.0000"
    assert result["totals"]["roi"] is None


def test_backend_csv_removes_task_metrics_and_preserves_sample_metrics(facts):
    tenant, owner, _, _, sample, order = facts
    owner.is_superuser = True
    owner.save(update_fields=["is_superuser"])
    sample("CSV-SAMPLE")
    order("CSV-ORDER")
    refresh_order_attributions(tenant=tenant)
    client = APIClient()
    client.force_authenticate(owner)
    response = client.get("/api/internal/influencers/bd-performance/export/", {
        "start_date": "2026-08-15", "end_date": "2026-08-15", "currency": "CNY",
    })
    assert response.status_code == 200
    rows = list(csv.reader(StringIO(response.content.decode("utf-8"))))
    assert "outreach_tasks" not in rows[0]
    assert "linked_count" not in rows[0]
    assert "samples" in rows[0]
    assert rows[1][rows[0].index("samples")] == "1"
    assert rows[-1][rows[0].index("samples")] == "1"
    assert all(len(row) == len(rows[0]) for row in rows)
