from datetime import timedelta
from decimal import Decimal
from io import StringIO
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.models import QuerySet
from django.utils import timezone

from apps.audit.models import OperationLog
from apps.influencers.attribution import create_sample_attribution_snapshot
from apps.influencers.management.commands import reprice_sample_confirmed_costs as module
from apps.influencers.models import BdSampleAttributionSnapshot, SampleItem
from apps.influencers.sample_costs import confirmed_sample_cost_for
from apps.influencers.services import _recalculate_sample_costs, _replace_sample_items_from_source, update_sample_fulfillment
from apps.influencers.tests.test_product_cost_snapshots import _records
from apps.products.models import ProductCostVersion


pytestmark = pytest.mark.django_db


def setup(code="current-ledger", amount="12.5000", currency="CNY"):
    records = _records(code, timezone.now() - timedelta(days=400))
    tenant, user, sku, parent, _, warehouse = records
    version = ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=warehouse, version_no=1, status="confirmed",
        source="manual", currency=currency, confirmed_cost=Decimal(amount),
        effective_from=timezone.now() - timedelta(days=5), created_by=user,
    )
    return (*records, version)


def payload(sku, warehouse, **extra):
    return {"sku": sku, "warehouse": warehouse, "requested_sku": sku.sku_code,
            "quantity": 2, "site_code": "PH", **extra}


def command(user, **options):
    cmd = module.Command()
    call_command(cmd, tenant_id=user.tenant_id, actor_id=user.pk, stdout=StringIO(), **options)
    return cmd.result


def admin(user):
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])


def test_old_sample_ignores_sample_date_and_future_pending_versions():
    tenant, user, sku, parent, sampled_at, wh, version = setup()
    for number, status, start in (
        (2, "pending", timezone.now() - timedelta(days=1)),
        (3, "confirmed", timezone.now() + timedelta(days=5)),
    ):
        ProductCostVersion.objects.create(
            tenant=tenant, sku=sku, warehouse=wh, version_no=number, status=status,
            source="manual", currency="CNY", confirmed_cost=Decimal("999"), effective_from=start, created_by=user,
        )
    selected, _ = confirmed_sample_cost_for(tenant=tenant, sku=sku, warehouse=wh, occurred_at=sampled_at)
    assert selected.pk == version.pk
    _recalculate_sample_costs(user=user, fulfillment=parent, item_payloads=[payload(sku, wh, unit_cost="999")])
    assert parent.items.get().cost_amount == Decimal("25.0000")
    assert parent.calculated_cost == Decimal("25.0000")


@pytest.mark.parametrize("amount", ["0.0000", "12.5000"])
def test_source_import_ignores_source_amounts_preserves_identity_and_replays_without_writes(amount):
    tenant, user, sku, parent, _, wh, version = setup("source-ledger-" + amount, amount)
    parent.store.code = "TKKJ4PH"
    parent.store.save(update_fields=["code"])
    data = [{"requested_sku": sku.sku_code, "site_code": parent.store.code, "quantity": 3,
             "unit_cost": "999", "cost_amount": "2997"}]
    _replace_sample_items_from_source(user=user, fulfillment=parent, item_payloads=data)
    item = parent.items.get()
    snapshot = create_sample_attribution_snapshot(
        tenant=tenant, fulfillment=parent, owner=user, influencer=parent.influencer, store=parent.store,
    )
    expected = Decimal(amount) * 3
    assert item.unit_cost == version.confirmed_cost and item.cost_amount == expected
    assert item.sku_id == sku.pk and item.warehouse_id == wh.pk and item.cost_version_id == version.pk
    assert parent.calculated_cost == snapshot.cost_amount == expected and snapshot.currency == "CNY"
    before = (item.pk, item.updated_at, item.cost_snapshot_at, parent.updated_at)
    log_count = OperationLog.objects.count()
    _replace_sample_items_from_source(user=user, fulfillment=parent, item_payloads=data)
    parent.refresh_from_db()
    item.refresh_from_db()
    assert before == (item.pk, item.updated_at, item.cost_snapshot_at, parent.updated_at)
    assert OperationLog.objects.count() == log_count


def test_cost_change_updates_imported_items_and_only_snapshot_money():
    tenant, user, sku, parent, _, wh, _ = setup("source-change")
    data = [{"requested_sku": sku.sku_code, "site_code": "PH", "quantity": 2}]
    _replace_sample_items_from_source(user=user, fulfillment=parent, item_payloads=data)
    snapshot = create_sample_attribution_snapshot(
        tenant=tenant, fulfillment=parent, owner=user, influencer=parent.influencer, store=parent.store,
    )
    frozen = (snapshot.owner_id, snapshot.influencer_id, snapshot.store_id, snapshot.sampled_at,
              snapshot.creator_username, snapshot.product_id, snapshot.sample_status)
    version = ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=wh, version_no=2, status="confirmed", source="manual",
        currency="PHP", confirmed_cost=Decimal("7.5"), effective_from=timezone.now() - timedelta(days=1), created_by=user,
    )
    item_id = parent.items.get().pk
    _replace_sample_items_from_source(user=user, fulfillment=parent, item_payloads=data)
    snapshot.refresh_from_db()
    assert parent.items.get().pk == item_id and parent.items.get().cost_version_id == version.pk
    assert parent.calculated_cost == snapshot.cost_amount == Decimal("15") and snapshot.currency == "PHP"
    assert frozen == (snapshot.owner_id, snapshot.influencer_id, snapshot.store_id, snapshot.sampled_at,
                      snapshot.creator_username, snapshot.product_id, snapshot.sample_status)


@pytest.mark.parametrize("kind", ["missing", "mixed"])
def test_incomplete_or_mixed_currency_sample_never_exposes_partial_total(kind):
    tenant, user, sku, parent, _, wh, _ = setup("incomplete-" + kind)
    data = [payload(sku, wh)]
    if kind == "missing":
        data.append({"requested_sku": "absent", "warehouse": wh, "site_code": "PH", "quantity": 1})
    else:
        from apps.products.models import ProductSKU
        other = ProductSKU.objects.create(tenant=tenant, spu=sku.spu, sku_code="SECOND")
        ProductCostVersion.objects.create(
            tenant=tenant, sku=other, warehouse=wh, version_no=1, status="confirmed", source="manual",
            currency="PHP", confirmed_cost=Decimal("2"), effective_from=timezone.now() - timedelta(days=1), created_by=user,
        )
        data.append(payload(other, wh))
    _recalculate_sample_costs(user=user, fulfillment=parent, item_payloads=data)
    assert parent.calculated_cost is None
    snap = create_sample_attribution_snapshot(
        tenant=tenant, fulfillment=parent, owner=user, influencer=parent.influencer, store=parent.store,
    )
    assert snap.cost_amount is None


def legacy_sample():
    tenant, user, sku, parent, _, wh, version = setup("reprice-legacy")
    admin(user)
    item = SampleItem.objects.create(
        tenant=tenant, fulfillment=parent, requested_sku=sku.sku_code, site_code="PH", quantity=2,
        cost_source="legacy_shop_analytics_bd", unit_cost=Decimal("1"), cost_amount=Decimal("2"), currency="PHP",
    )
    QuerySet.update(type(parent).objects.filter(pk=parent.pk), calculated_cost=Decimal("9"))
    parent.refresh_from_db()
    snap = create_sample_attribution_snapshot(
        tenant=tenant, fulfillment=parent, owner=user, influencer=parent.influencer, store=parent.store,
    )
    QuerySet.update(BdSampleAttributionSnapshot.objects.filter(pk=snap.pk), cost_amount=Decimal("3"))
    snap.refresh_from_db()
    return tenant, user, sku, parent, item, version, snap


def test_reprice_preview_apply_and_fresh_plan_are_idempotent_and_cost_only(tmp_path):
    tenant, user, _, parent, item, version, snap = legacy_sample()
    protected = (parent.owner_id, parent.influencer_id, parent.store_id, parent.sample_sent_at,
                 parent.sample_order_no, parent.outreach_task_id, parent.status, snap.owner_id, snap.sampled_at)
    path = tmp_path / "plan.json"
    plan = command(user, report_path=str(path))
    assert plan["rows"][0]["changed"] is True
    item.refresh_from_db(); parent.refresh_from_db(); snap.refresh_from_db()
    assert item.cost_amount == Decimal("2") and parent.calculated_cost == Decimal("9") and snap.cost_amount == Decimal("3")
    assert not OperationLog.objects.filter(action="reprice_sample_confirmed_cost").exists()
    command(user, apply=True, expected_plan=str(path))
    item.refresh_from_db(); parent.refresh_from_db(); snap.refresh_from_db()
    assert item.cost_version_id == version.pk
    assert parent.calculated_cost == snap.cost_amount == item.cost_amount == Decimal("25")
    assert snap.currency == "CNY"
    assert protected == (parent.owner_id, parent.influencer_id, parent.store_id, parent.sample_sent_at,
                         parent.sample_order_no, parent.outreach_task_id, parent.status, snap.owner_id, snap.sampled_at)
    assert command(user)["rows"][0]["changed"] is False
    assert OperationLog.objects.filter(tenant=tenant, action="reprice_sample_confirmed_cost").count() == 1
    with pytest.raises(CommandError, match="changed since preview"):
        command(user, apply=True, expected_plan=str(path))


@pytest.mark.parametrize("change", ["quantity", "cost", "snapshot", "delete"])
def test_stale_reprice_plan_is_rejected_without_cost_writes(tmp_path, change):
    _, user, _, parent, item, version, snap = legacy_sample()
    path = tmp_path / "plan.json"
    command(user, report_path=str(path))
    if change == "quantity":
        QuerySet.update(SampleItem.objects.filter(pk=item.pk), quantity=3)
    elif change == "cost":
        QuerySet.update(ProductCostVersion.objects.filter(pk=version.pk), confirmed_cost=Decimal("99"))
    elif change == "snapshot":
        QuerySet.update(type(snap).objects.filter(pk=snap.pk), currency="THB")
    else:
        QuerySet.update(type(parent).objects.filter(pk=parent.pk), is_deleted=True)
    with pytest.raises(CommandError, match="changed since preview"):
        command(user, apply=True, expected_plan=str(path))
    item.refresh_from_db()
    assert item.cost_amount == Decimal("2")
    assert not OperationLog.objects.filter(action="reprice_sample_confirmed_cost").exists()


def test_unmatched_legacy_amount_is_unknown_not_preserved_as_current_cost(tmp_path):
    _, user, _, parent, item, _, snap = legacy_sample()
    QuerySet.update(SampleItem.objects.filter(pk=item.pk), requested_sku="not-found")
    path = tmp_path / "unknown.json"
    assert command(user, report_path=str(path))["rows"][0]["unmatched_items"] == 1
    command(user, apply=True, expected_plan=str(path))
    item.refresh_from_db(); parent.refresh_from_db(); snap.refresh_from_db()
    assert item.cost_amount is parent.calculated_cost is snap.cost_amount is None


def test_reprice_requires_plan_and_admin_and_rolls_back_on_audit_failure(tmp_path, monkeypatch):
    _, user, _, parent, item, _, _ = legacy_sample()
    with pytest.raises(CommandError, match="requires --expected-plan"):
        command(user, apply=True)
    user.is_superuser = False
    user.save(update_fields=["is_superuser"])
    with pytest.raises(CommandError, match="superuser"):
        command(user)
    admin(user)
    path = tmp_path / "rollback.json"
    command(user, report_path=str(path))
    def fail(**kwargs):
        raise RuntimeError("synthetic audit failure")
    monkeypatch.setattr(module, "write_operation_log", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        command(user, apply=True, expected_plan=str(path))
    item.refresh_from_db(); parent.refresh_from_db()
    assert item.cost_amount == Decimal("2") and parent.calculated_cost == Decimal("9")


def test_foreign_tenant_cannot_price_or_reprice_sample_and_cursor_is_bounded(tmp_path):
    tenant, user, sku, parent, _, wh, _ = setup("local-price")
    other, other_user, _, _, _, other_wh, _ = setup("foreign-price")
    assert confirmed_sample_cost_for(tenant=other, sku=sku, warehouse=wh) == (None, "")
    assert confirmed_sample_cost_for(tenant=tenant, sku=sku, warehouse=other_wh) == (None, "")
    admin(user)
    with pytest.raises(CommandError, match="superuser"):
        call_command("reprice_sample_confirmed_costs", tenant_id=tenant.pk, actor_id=other_user.pk)
    plan = command(user, batch_size=1)
    assert len(plan["rows"]) == 1 and plan["rows"][0]["fulfillment_id"] == parent.pk
    assert command(user, after_fulfillment_id=parent.pk)["rows"] == []


def test_non_item_edit_refreshes_legacy_cost_without_replacing_items():
    _, user, _, parent, item, version, snap = legacy_sample()
    updated = update_sample_fulfillment(
        user=user, fulfillment=parent, expected_version=parent.version, validated_data={"notes": "Edited"},
    )
    item.refresh_from_db(); snap.refresh_from_db()
    assert updated.notes == "Edited" and updated.calculated_cost == Decimal("25")
    assert item.cost_version_id == version.pk and item.cost_amount == snap.cost_amount == Decimal("25")
    assert updated.items.get().pk == item.pk


def test_reprice_whole_page_rolls_back_if_second_sample_audit_fails(tmp_path, monkeypatch):
    tenant, user, sku, parent, item, _, _ = legacy_sample()
    second = type(parent).objects.create(
        tenant=tenant, fulfillment_no="SECOND", request_key="SECOND", request_hash="s" * 64,
        influencer=parent.influencer, owner=user, store=parent.store, sample_sent_at=parent.sample_sent_at,
    )
    second_item = SampleItem.objects.create(
        tenant=tenant, fulfillment=second, requested_sku=sku.sku_code, site_code="PH", quantity=1,
    )
    path = tmp_path / "page.json"
    command(user, report_path=str(path))
    real_audit = module.write_operation_log
    def fail_on_second(**kwargs):
        if kwargs["object_type"] == "sample_fulfillment" and kwargs["object_id"] == second.pk:
            raise RuntimeError("second sample failure")
        return real_audit(**kwargs)
    monkeypatch.setattr(module, "write_operation_log", fail_on_second)
    with pytest.raises(RuntimeError, match="second sample failure"):
        command(user, apply=True, expected_plan=str(path))
    item.refresh_from_db(); second_item.refresh_from_db()
    assert item.cost_amount == Decimal("2") and second_item.cost_amount is None
    assert not OperationLog.objects.filter(action="reprice_sample_confirmed_cost").exists()


def test_import_aggregates_same_sku_quantity_before_ledger_pricing():
    _, user, sku, parent, _, _, _ = setup("source-duplicate")
    _replace_sample_items_from_source(
        user=user, fulfillment=parent,
        item_payloads=[{"requested_sku": sku.sku_code, "site_code": "PH", "quantity": q,
                        "unit_cost": str(q * 999), "cost_amount": str(q * 999)} for q in (1, 2)],
    )
    item = parent.items.get()
    assert item.quantity == 3 and item.cost_amount == Decimal("37.5000")


def test_latest_confirmed_null_cost_does_not_fall_back_to_older_price():
    tenant, user, sku, parent, _, wh, _ = setup("latest-null")
    ProductCostVersion.objects.create(
        tenant=tenant, sku=sku, warehouse=wh, version_no=2, status="confirmed", source="manual",
        currency="CNY", confirmed_cost=None, effective_from=timezone.now() - timedelta(days=1), created_by=user,
    )
    _recalculate_sample_costs(user=user, fulfillment=parent, item_payloads=[payload(sku, wh)])
    assert parent.calculated_cost is None and parent.items.get().cost_amount is None


def test_invalid_historical_sku_is_reported_unknown_without_blocking_batch(tmp_path):
    _, user, sku, parent, item, _, snap = legacy_sample()
    QuerySet.update(SampleItem.objects.filter(pk=item.pk), sku=sku)
    sku.is_active = False
    sku.save(update_fields=["is_active"])
    path = tmp_path / "inactive.json"
    assert command(user, report_path=str(path))["rows"][0]["unmatched_items"] == 1
    command(user, apply=True, expected_plan=str(path))
    item.refresh_from_db(); parent.refresh_from_db(); snap.refresh_from_db()
    assert item.cost_amount is parent.calculated_cost is snap.cost_amount is None


def test_existing_report_is_not_overwritten_and_no_data_is_applied(tmp_path):
    _, user, _, parent, item, _, _ = legacy_sample()
    path = tmp_path / "plan.json"
    plan = command(user, report_path=str(path))
    with pytest.raises(FileExistsError):
        command(user, apply=True, expected_plan=str(path), report_path=str(path))
    assert json.loads(path.read_text()) == plan
    item.refresh_from_db(); parent.refresh_from_db()
    assert item.cost_amount == Decimal("2") and parent.calculated_cost == Decimal("9")


@pytest.mark.parametrize("same_code", [False, True])
def test_source_import_legacy_sku_mapping_replays_without_rebinding_or_writes(same_code):
    _, user, sku, parent, _, _, _ = setup("legacy-replay-" + str(same_code))
    sku.legacy_sku_code = sku.sku_code if same_code else "OLD-SKU"
    sku.save(update_fields=["legacy_sku_code"])
    data = [{"requested_sku": sku.legacy_sku_code, "site_code": "PH", "quantity": 1}]
    _replace_sample_items_from_source(user=user, fulfillment=parent, item_payloads=data)
    item = parent.items.get()
    before = (item.pk, item.normalized_sku, item.cost_match_status, item.cost_snapshot_at, item.updated_at, parent.updated_at)
    _replace_sample_items_from_source(user=user, fulfillment=parent, item_payloads=data)
    item.refresh_from_db(); parent.refresh_from_db()
    assert before == (item.pk, item.normalized_sku, item.cost_match_status, item.cost_snapshot_at, item.updated_at, parent.updated_at)
