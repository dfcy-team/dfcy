from datetime import date
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.products.models import MonthlyProductCost, MonthlyProductCostEvent
from apps.products.monthly_cost_services import finalize_month, recalculate_month
from apps.tenants.models import Tenant
from tests.test_product_costs import make_sku, make_warehouse


@pytest.fixture
def monthly_record():
    tenant = Tenant.objects.create(name="Monthly cost", code="monthly-cost-test")
    sku = make_sku(tenant, "MONTHLY")
    warehouse = make_warehouse(tenant, "MONTHLY")
    return MonthlyProductCost.objects.create(
        tenant=tenant, sku=sku, warehouse=warehouse, month=date(2025, 4, 1),
        opening_quantity=Decimal("10"), opening_amount=Decimal("20"),
        receipt_quantity=Decimal("10"), receipt_amount=Decimal("60"), adjustment_amount=Decimal("0"),
        outbound_quantity=Decimal("5"), is_complete=True,
    )


@pytest.mark.django_db
def test_month_weighted_cost_prices_all_outbounds(monthly_record):
    row = recalculate_month(monthly_record)
    assert row.unit_cost == Decimal("4.000000")
    assert row.closing_quantity == Decimal("15.0000")
    assert row.closing_amount == Decimal("60.0000")


@pytest.mark.django_db
def test_unknown_amount_stays_missing_not_zero(monthly_record):
    monthly_record.receipt_amount = None
    monthly_record.is_complete = False
    monthly_record.save()
    row = recalculate_month(monthly_record)
    assert row.unit_cost is None and not row.is_complete


@pytest.mark.django_db
def test_valid_zero_cost_is_complete(monthly_record):
    monthly_record.opening_amount = Decimal("0")
    monthly_record.receipt_amount = Decimal("0")
    monthly_record.save()
    row = recalculate_month(monthly_record)
    assert row.unit_cost == Decimal("0.000000") and row.is_complete


@pytest.mark.django_db
def test_negative_stock_is_marked_incomplete(monthly_record):
    monthly_record.outbound_quantity = Decimal("21")
    monthly_record.save()
    row = recalculate_month(monthly_record)
    assert row.unit_cost is None and not row.is_complete


@pytest.mark.django_db
def test_negative_cost_amount_cannot_be_saved(monthly_record):
    monthly_record.receipt_amount = Decimal("-1")
    with pytest.raises(ValidationError, match="negative"):
        monthly_record.save()


@pytest.mark.django_db
def test_unchanged_recalculation_does_not_create_version(monthly_record):
    recalculate_month(monthly_record)
    recalculate_month(monthly_record)
    assert monthly_record.versions.count() == 1


@pytest.mark.django_db
def test_finalized_cost_is_immutable(monthly_record):
    monthly_record.month = date(2025, 4, 1)
    row = recalculate_month(monthly_record)
    finalize_month(row, {"source_complete": True, "inventory_reconciled": True, "opening_verified": True})
    row.refresh_from_db()
    row.receipt_amount = Decimal("99")
    with pytest.raises(ValidationError, match="immutable"):
        row.save()
    with pytest.raises(ValidationError, match="recalculated"):
        recalculate_month(row)


@pytest.mark.django_db
def test_future_month_cannot_be_finalized(monthly_record):
    monthly_record.month = date.today().replace(day=1)
    monthly_record.save()
    row = recalculate_month(monthly_record)
    with pytest.raises(ValidationError, match="completed month"):
        finalize_month(row, {"source_complete": True, "inventory_reconciled": True, "opening_verified": True})


@pytest.mark.django_db
def test_finalization_requires_watermark(monthly_record):
    row = recalculate_month(monthly_record)
    with pytest.raises(ValidationError, match="watermark"):
        finalize_month(row, {})


@pytest.mark.django_db
def test_idempotency_event_unique_key(monthly_record):
    MonthlyProductCostEvent.objects.create(tenant=monthly_record.tenant, monthly_cost=monthly_record,
                                           source_type="receipt", source_key="R-1")
    with pytest.raises(Exception):
        MonthlyProductCostEvent.objects.create(tenant=monthly_record.tenant, monthly_cost=monthly_record,
                                               source_type="receipt", source_key="R-1")


@pytest.mark.django_db
def test_large_quantity_preserves_amount(monthly_record):
    monthly_record.opening_quantity=Decimal("100000")
    monthly_record.opening_amount=Decimal("12345.6500")
    monthly_record.receipt_quantity=Decimal("0")
    monthly_record.receipt_amount=Decimal("0")
    monthly_record.outbound_quantity=Decimal("0")
    monthly_record.save()
    assert recalculate_month(monthly_record).closing_amount==Decimal("12345.6500")


@pytest.mark.django_db
def test_finalize_recalculates_changed_inputs(monthly_record):
    row=recalculate_month(monthly_record)
    row.receipt_amount=Decimal("100");row.save()
    row=finalize_month(row,{"source_complete": True, "inventory_reconciled": True, "opening_verified": True})
    assert row.unit_cost==Decimal("6")
    assert row.versions.order_by("-version_no").first().snapshot["status"]=="finalized"


@pytest.mark.django_db
def test_missing_recalculation_keeps_unknown_and_is_idempotent(monthly_record):
    monthly_record.is_complete=False;monthly_record.opening_amount=None;monthly_record.save()
    row=recalculate_month(monthly_record)
    count=row.versions.count()
    row=recalculate_month(row)
    assert row.closing_amount is None
    assert row.versions.count()==count


@pytest.mark.django_db
def test_negative_adjustment_reduces_cost_without_negative_total(monthly_record):
    monthly_record.adjustment_amount=Decimal("-20");monthly_record.save()
    row=recalculate_month(monthly_record)
    assert row.unit_cost==Decimal("3")
