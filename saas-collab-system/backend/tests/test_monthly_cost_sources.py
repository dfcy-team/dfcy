from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
import pytest

from apps.products.monthly_cost_sources import _month_bounds
from apps.products.tasks import aggregate_monthly_product_cost_sources
from apps.products.models import MonthlyProductCost
from apps.products.monthly_cost_services import finalize_month
from apps.tenants.models import Tenant
from tests.test_product_costs import make_sku, make_warehouse


class MonthlyCostSourceEntryTests(SimpleTestCase):
    def test_month_boundaries(self):
        self.assertEqual(_month_bounds(date(2026, 12, 15)), (date(2026, 12, 1), date(2027, 1, 1)))

    @override_settings(MONTHLY_PRODUCT_COST_ENABLED=False)
    def test_task_is_disabled_by_default(self):
        with patch("apps.products.monthly_cost_sources.aggregate_month") as aggregate:
            result = aggregate_monthly_product_cost_sources.run(4, "2026-10-01")
        self.assertEqual(result, {"status": "disabled", "enabled": False, "items": []})
        aggregate.assert_not_called()

    @override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
    def test_task_returns_pending_aggregation(self):
        expected = {"items": [], "enabled": True}
        with patch("apps.products.monthly_cost_sources.aggregate_month", return_value=expected) as aggregate, patch("apps.products.monthly_cost_adjustments.sync_late_adjustments", return_value={}):
            result = aggregate_monthly_product_cost_sources.run(4, "2026-10-01")
        self.assertEqual(result["status"], "pending_review")
        aggregate.assert_called_once_with(4, date(2026, 10, 1))


def _source_item(sku, warehouse, outbound="3"):
    return {"sku_id": sku.pk, "warehouse_id": warehouse.pk,
        "receipt_quantity": Decimal("2"), "receipt_amount": Decimal("8"),
        "outbound_quantity": Decimal(outbound), "is_complete": True,
        "missing_reasons": [], "source_keys": ["outbound:1", "receipt:1"]}


def _aggregate(item):
    return {"items": [item], "source_complete": True, "unmapped_outbounds": 0,
        "ambiguous_outbounds": 0, "truncated": False}


@pytest.mark.django_db
@override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
def test_daily_task_writes_and_aggregates_same_sku_outbound(monkeypatch):
    tenant = Tenant.objects.create(name="Sources", code="monthly-sources-one")
    sku, warehouse = make_sku(tenant, "SRC1"), make_warehouse(tenant, "SRC1")
    monkeypatch.setattr("apps.products.monthly_cost_sources.aggregate_month",
        lambda tenant_id, month: _aggregate(_source_item(sku, warehouse, "7")))
    result = aggregate_monthly_product_cost_sources.run(tenant.pk, "2025-05-01")
    row = MonthlyProductCost.objects.get(tenant=tenant, sku=sku, warehouse=warehouse, month=date(2025, 5, 1))
    assert result["written"] == 1
    assert row.outbound_quantity == Decimal("7")
    assert row.receipt_quantity == Decimal("2")
    assert not row.is_complete


@pytest.mark.django_db
@override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
def test_daily_task_carries_forward_finalized_balance(monkeypatch):
    tenant = Tenant.objects.create(name="Sources", code="monthly-sources-two")
    sku, warehouse = make_sku(tenant, "SRC2"), make_warehouse(tenant, "SRC2")
    prior = MonthlyProductCost.objects.create(tenant=tenant, sku=sku, warehouse=warehouse,
        month=date(2025, 4, 1), opening_quantity=Decimal("5"), opening_amount=Decimal("15"),
        receipt_quantity=Decimal("0"), receipt_amount=Decimal("0"), adjustment_amount=Decimal("0"), is_complete=True)
    prior = finalize_month(prior, {"source_complete": True, "inventory_reconciled": True, "opening_verified": True})
    monkeypatch.setattr("apps.products.monthly_cost_sources.aggregate_month",
        lambda tenant_id, month: _aggregate(_source_item(sku, warehouse, "1")))
    aggregate_monthly_product_cost_sources.run(tenant.pk, "2025-05-01")
    current = MonthlyProductCost.objects.get(tenant=tenant, sku=sku, warehouse=warehouse, month=date(2025, 5, 1))
    assert current.opening_quantity == prior.closing_quantity
    assert current.opening_amount == prior.closing_amount


@pytest.mark.django_db
@override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
def test_daily_task_rerun_updates_same_row_without_duplicate_month(monkeypatch):
    tenant = Tenant.objects.create(name="Sources", code="monthly-sources-three")
    sku, warehouse = make_sku(tenant, "SRC3"), make_warehouse(tenant, "SRC3")
    monkeypatch.setattr("apps.products.monthly_cost_sources.aggregate_month",
        lambda tenant_id, month: _aggregate(_source_item(sku, warehouse, "2")))
    aggregate_monthly_product_cost_sources.run(tenant.pk, "2025-05-01")
    aggregate_monthly_product_cost_sources.run(tenant.pk, "2025-05-01")
    assert MonthlyProductCost.objects.filter(tenant=tenant, sku=sku, warehouse=warehouse,
        month=date(2025, 5, 1)).count() == 1


@pytest.mark.django_db
@override_settings(MONTHLY_PRODUCT_COST_ENABLED=True)
def test_daily_task_skips_finalized_month(monkeypatch):
    tenant = Tenant.objects.create(name="Sources", code="monthly-sources-four")
    sku, warehouse = make_sku(tenant, "SRC4"), make_warehouse(tenant, "SRC4")
    finalized = MonthlyProductCost.objects.create(tenant=tenant, sku=sku, warehouse=warehouse,
        month=date(2025, 5, 1), opening_quantity=Decimal("5"), opening_amount=Decimal("15"),
        receipt_quantity=Decimal("0"), receipt_amount=Decimal("0"), adjustment_amount=Decimal("0"), is_complete=True)
    finalize_month(finalized, {"source_complete": True, "inventory_reconciled": True, "opening_verified": True})
    monkeypatch.setattr("apps.products.monthly_cost_sources.aggregate_month",
        lambda tenant_id, month: _aggregate(_source_item(sku, warehouse, "99")))
    result = aggregate_monthly_product_cost_sources.run(tenant.pk, "2025-05-01")
    finalized.refresh_from_db()
    assert result["skipped_finalized"] == 1
    assert finalized.outbound_quantity == 0
