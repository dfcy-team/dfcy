from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import QuerySet

from apps.audit.models import OperationLog
from apps.influencers.attribution import create_sample_attribution_snapshot
from apps.influencers.management.commands import backfill_sample_confirmed_costs as module
from apps.influencers.models import SampleItem
from apps.influencers.tests.test_product_cost_snapshots import _records
from apps.products.models import ProductCostVersion


pytestmark = pytest.mark.django_db


def setup(code, source="", quantity=2):
    tenant, user, sku, parent, sampled_at, warehouse = _records(code)
    item = SampleItem.objects.create(
        tenant=tenant, fulfillment=parent, requested_sku=sku.sku_code, site_code="PH",
        quantity=quantity, cost_source=source,
    )
    version = ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=warehouse, version_no=1, status="confirmed",
        source="manual", currency="CNY", confirmed_cost=Decimal("8.1234"),
        effective_from=sampled_at - timedelta(days=1), created_by=user,
    )
    snapshot = create_sample_attribution_snapshot(
        tenant=tenant, fulfillment=parent, owner=user, influencer=parent.influencer, store=parent.store,
    )
    QuerySet.update(type(snapshot).objects.filter(pk=snapshot.pk), currency="PHP")
    snapshot.refresh_from_db()
    return tenant, user, sku, parent, item, version, snapshot


def run(user, *, apply=False, **kwargs):
    output = StringIO()
    call_command("backfill_sample_confirmed_costs", tenant_id=user.tenant_id, actor_id=user.pk,
                 apply=apply, stdout=output, **kwargs)
    return output.getvalue()


@pytest.mark.parametrize("source", ["", "legacy_shop_analytics_bd"])
def test_pending_imports_fill_cost_and_bd_snapshot_idempotently(source):
    tenant, user, sku, parent, item, version, snapshot = setup("pending-" + str(len(source)), source)
    immutable_parent = (parent.owner_id, parent.store_id, parent.influencer_id, parent.sample_sent_at,
                        parent.outreach_task_id, parent.sample_order_no)
    immutable_snapshot = (snapshot.owner_id, snapshot.creator_username, snapshot.sampled_at, snapshot.product_id)
    assert "matched=1 applied=0" in run(user)
    item.refresh_from_db()
    assert item.cost_amount is None
    assert "matched=1 applied=1" in run(user, apply=True)
    item.refresh_from_db(); parent.refresh_from_db(); snapshot.refresh_from_db()
    assert item.cost_version_id == version.pk and item.sku_id == sku.pk
    assert item.warehouse_id == version.warehouse_id and item.cost_amount == Decimal("16.2468")
    assert parent.calculated_cost == snapshot.cost_amount == item.cost_amount
    assert snapshot.currency == "CNY"
    assert immutable_parent == (parent.owner_id, parent.store_id, parent.influencer_id, parent.sample_sent_at,
                                parent.outreach_task_id, parent.sample_order_no)
    assert immutable_snapshot == (snapshot.owner_id, snapshot.creator_username, snapshot.sampled_at, snapshot.product_id)
    assert "scanned=0" in run(user, apply=True)
    assert OperationLog.objects.filter(tenant=tenant, action="backfill_sample_confirmed_cost").count() == 1


@pytest.mark.parametrize("field,value", [("unit_cost", Decimal("0")), ("cost_amount", Decimal("1")),
                                          ("cost_version", "version"), ("cost_source", "manual")])
def test_never_overwrites_existing_or_manual_item_fields(field, value):
    _, user, _, _, item, version, snapshot = setup("protected-item-" + field)
    QuerySet.update(SampleItem.objects.filter(pk=item.pk), **{field: version if value == "version" else value})
    assert "scanned=0" in run(user, apply=True)
    snapshot.refresh_from_db()
    assert snapshot.cost_amount is None


@pytest.mark.parametrize("target", ["parent", "snapshot"])
def test_known_historical_totals_are_held_for_manual_review(target):
    _, user, _, parent, item, _, snapshot = setup("known-total-" + target)
    obj = parent if target == "parent" else snapshot
    field = "calculated_cost" if target == "parent" else "cost_amount"
    QuerySet.update(type(obj).objects.filter(pk=obj.pk), **{field: Decimal("9.99")})
    assert "existing_total=1" in run(user, apply=True)
    item.refresh_from_db(); obj.refresh_from_db()
    assert item.cost_amount is None and getattr(obj, field) == Decimal("9.99")


def test_partial_sample_total_and_bd_cost_remain_unknown_then_fill_on_retry():
    _, user, sku, parent, item, version, snapshot = setup("partial-total")
    other = SampleItem.objects.create(tenant=user.tenant, fulfillment=parent, requested_sku="missing-sku",
                                      site_code="PH", quantity=1)
    assert "applied=1" in run(user, apply=True)
    parent.refresh_from_db(); snapshot.refresh_from_db()
    assert parent.calculated_cost is None and snapshot.cost_amount is None
    assert snapshot.currency == "PHP"
    QuerySet.update(SampleItem.objects.filter(pk=item.pk), requested_sku="old-processed")
    QuerySet.update(SampleItem.objects.filter(pk=other.pk), requested_sku=sku.sku_code)
    assert "applied=1" in run(user, apply=True)
    parent.refresh_from_db(); snapshot.refresh_from_db()
    assert parent.calculated_cost == snapshot.cost_amount == Decimal("24.3702")


@pytest.mark.parametrize("change,reason", [("site", "country_conflict"), ("cost", "no_version"),
                                           ("warehouse", "warehouse_ambiguous"), ("quantity", "invalid_source")])
def test_bad_matching_inputs_do_not_write(change, reason):
    _, user, _, _, item, version, snapshot = setup("unmatched-" + change)
    if change == "site":
        QuerySet.update(SampleItem.objects.filter(pk=item.pk), site_code="TH")
    elif change == "quantity":
        QuerySet.update(SampleItem.objects.filter(pk=item.pk), quantity=0)
    elif change == "cost":
        QuerySet.update(ProductCostVersion.objects.filter(pk=version.pk), status="pending")
    else:
        QuerySet.update(type(version.warehouse).objects.filter(pk=version.warehouse_id), status="inactive")
    assert reason + "=1" in run(user, apply=True)
    item.refresh_from_db(); snapshot.refresh_from_db()
    assert item.cost_amount is None and snapshot.cost_amount is None


def test_cross_tenant_and_deleted_samples_are_never_changed():
    _, user, _, parent, item, _, _ = setup("tenant-primary")
    _, other_user, _, other_parent, other_item, _, _ = setup("tenant-foreign")
    QuerySet.update(type(parent).objects.filter(pk=parent.pk), is_deleted=True)
    assert "scanned=0" in run(user, apply=True)
    item.refresh_from_db(); other_item.refresh_from_db()
    assert item.cost_amount is None and other_item.cost_amount is None
    with pytest.raises(CommandError):
        call_command("backfill_sample_confirmed_costs", tenant_id=user.tenant_id, actor_id=other_user.pk)


def test_exact_historical_shop_code_is_a_valid_site_alias():
    _, user, _, parent, item, _, snapshot = setup("legacy-shop-site")
    QuerySet.update(SampleItem.objects.filter(pk=item.pk), site_code=parent.store.code)
    assert "applied=1" in run(user, apply=True)
    snapshot.refresh_from_db()
    assert snapshot.cost_amount == Decimal("16.2468")


def test_expected_plan_rejects_changed_amount_and_supports_bounded_cursor(tmp_path):
    _, user, _, _, item, version, _ = setup("expected-plan")
    report = tmp_path / "plan.json"
    run(user, report_path=str(report))
    assert json.loads(report.read_text())["rows"][0]["item_id"] == item.pk
    QuerySet.update(ProductCostVersion.objects.filter(pk=version.pk), confirmed_cost=Decimal("9"))
    with pytest.raises(CommandError, match="changed since"):
        run(user, apply=True, expected_plan=str(report))
    item.refresh_from_db()
    assert item.cost_amount is None
    QuerySet.update(ProductCostVersion.objects.filter(pk=version.pk), confirmed_cost=Decimal("8.1234"))
    assert "applied=1" in run(user, apply=True, expected_plan=str(report), batch_size=1)


def test_empty_expected_page_still_advances_cursor(tmp_path):
    _, user, _, _, item, _, _ = setup("empty-page")
    report = tmp_path / "empty.json"
    report.write_text(json.dumps({"tenant_id": user.tenant_id, "rows": []}))
    result = run(user, apply=True, expected_plan=str(report))
    assert "next_after_item_id=" + str(item.pk) in result
    item.refresh_from_db()
    assert item.cost_amount is None


def test_reviewed_multi_item_sample_can_cross_batch_boundary(tmp_path):
    _, user, sku, parent, item, _, snapshot = setup("multi-page")
    sku.legacy_sku_code = "legacy-multi-page"
    sku.save(update_fields=["legacy_sku_code"])
    other = SampleItem.objects.create(tenant=user.tenant, fulfillment=parent, requested_sku=sku.legacy_sku_code,
                                      site_code="PH", quantity=1)
    report = tmp_path / "multi-page.json"
    run(user, report_path=str(report))
    first = run(user, apply=True, expected_plan=str(report), batch_size=1)
    assert "has_more=true" in first and "applied=1" in first
    parent.refresh_from_db(); snapshot.refresh_from_db()
    assert parent.calculated_cost is None and snapshot.cost_amount is None
    assert "applied=1" in run(user, apply=True, expected_plan=str(report), batch_size=1, after_item_id=item.pk)
    parent.refresh_from_db(); snapshot.refresh_from_db(); other.refresh_from_db()
    assert parent.calculated_cost == snapshot.cost_amount == Decimal("24.3702")


def test_mixed_currencies_and_oversized_amounts_remain_unknown():
    _, user, _, parent, item, version, snapshot = setup("currency-conflict")
    SampleItem.objects.create(tenant=user.tenant, fulfillment=parent, requested_sku="known-php",
                              site_code="PH", quantity=1, unit_cost=Decimal("1"), cost_amount=Decimal("1"), currency="PHP")
    assert "currency_conflict=1" in run(user, apply=True)
    item.refresh_from_db(); snapshot.refresh_from_db()
    assert item.cost_amount is None and snapshot.cost_amount is None
    QuerySet.update(SampleItem.objects.filter(pk=item.pk), quantity=1000)
    QuerySet.update(ProductCostVersion.objects.filter(pk=version.pk), confirmed_cost=Decimal("999999999999.0000"))
    assert "applied=0" in run(user, apply=True)


def test_audit_failure_rolls_back_item_parent_and_snapshot(monkeypatch):
    _, user, _, parent, item, _, snapshot = setup("audit-rollback")
    def refuse(**kwargs):
        raise RuntimeError("synthetic-audit-failure")
    monkeypatch.setattr(module, "write_operation_log", refuse)
    with pytest.raises(RuntimeError, match="synthetic-audit"):
        run(user, apply=True)
    item.refresh_from_db(); parent.refresh_from_db(); snapshot.refresh_from_db()
    assert item.cost_amount is parent.calculated_cost is snapshot.cost_amount is None
