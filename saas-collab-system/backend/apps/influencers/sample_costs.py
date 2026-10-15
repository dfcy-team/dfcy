from decimal import Decimal

from django.db import transaction
from django.db.models import Case, IntegerField, QuerySet, Value, When
from django.utils import timezone

from apps.audit.services import write_operation_log
from apps.masterdata.models import StatusChoices
from apps.products.models import ProductCostVersion

from .models import BdSampleAttributionSnapshot, SUPPORTED_CURRENCY_CHOICES


CURRENT_COST_SOURCE = "product_cost_version_current"
UNMATCHED_COST_SOURCE = "product_cost_version_unmatched"
COST_FIELDS = (
    "sku_id", "warehouse_id", "cost_version_id", "normalized_sku", "matched_sku_code",
    "matched_legacy_sku_code", "cost_match_status", "cost_source", "unit_cost", "cost_amount", "currency",
)


def confirmed_sample_cost_for(*, tenant, sku, warehouse, occurred_at=None, as_of=None):
    """Use the current confirmed ledger row, never the historical sample date.

    Keep occurred_at as a compatibility argument for older callers. Pending and
    not-yet-effective versions cannot price a sample. As in the ledger's current
    view, prefer an open version, then the highest version number.
    """
    if (
        sku is None or warehouse is None
        or sku.tenant_id != tenant.pk or not sku.is_active
        or warehouse.tenant_id != tenant.pk or warehouse.status != StatusChoices.ACTIVE
    ):
        return None, ""
    open_first = Case(
        When(effective_to__isnull=True, then=Value(0)), default=Value(1), output_field=IntegerField(),
    )
    version = (
        ProductCostVersion.objects.filter(
            tenant=tenant, sku=sku, warehouse=warehouse,
            status=ProductCostVersion.Status.CONFIRMED,
            effective_from__lte=as_of or timezone.now(),
        )
        .order_by(open_first.asc(), "-version_no", "-pk")
        .first()
    )
    return (version, CURRENT_COST_SOURCE) if version and version.confirmed_cost is not None else (None, "")


def sample_item_cost_fields(*, tenant, sku, warehouse, quantity, normalized="", status="pending", as_of=None):
    """Derived fields only: imports/client amounts are never a monetary source."""
    fields = {
        "sku_id": sku.pk if sku else None,
        "warehouse_id": warehouse.pk if warehouse else None,
        "cost_version_id": None,
        "normalized_sku": normalized,
        "matched_sku_code": sku.sku_code if sku else "",
        "matched_legacy_sku_code": sku.legacy_sku_code if sku else "",
        "cost_match_status": "cost_unmatched" if sku else status,
        "cost_source": UNMATCHED_COST_SOURCE,
        "unit_cost": None, "cost_amount": None, "currency": "",
    }
    version, source = confirmed_sample_cost_for(tenant=tenant, sku=sku, warehouse=warehouse, as_of=as_of)
    if version is None or quantity < 1:
        return fields
    unit_cost = version.confirmed_cost
    amount = unit_cost * quantity
    if (
        not unit_cost.is_finite() or unit_cost < 0 or amount >= Decimal("1e14")
        or version.currency not in dict(SUPPORTED_CURRENCY_CHOICES)
    ):
        return fields
    fields.update(
        cost_version_id=version.pk, unit_cost=unit_cost, cost_amount=amount,
        currency=version.currency, cost_match_status=status, cost_source=source,
    )
    return fields


def sample_cost_total(items):
    """An incomplete or mixed-currency sample has an unknown total, not a subtotal."""
    rows = list(items)
    currencies = {row.currency for row in rows}
    if (
        not rows or len(currencies) != 1 or not next(iter(currencies))
        or any(row.cost_amount is None for row in rows)
    ):
        return None, "CNY"
    total = sum((row.cost_amount for row in rows), Decimal("0"))
    return (total, next(iter(currencies))) if total < Decimal("1e14") else (None, "CNY")


@transaction.atomic
def sync_sample_cost_snapshot(*, user, fulfillment):
    """Refresh monetary fields only; ownership and order attribution stay frozen."""
    amount, currency = sample_cost_total(fulfillment.items.filter(tenant=user.tenant))
    for snapshot in BdSampleAttributionSnapshot.objects.select_for_update().filter(
        tenant=user.tenant, fulfillment=fulfillment,
    ):
        if (snapshot.cost_amount, snapshot.currency) == (amount, currency):
            continue
        QuerySet.update(
            BdSampleAttributionSnapshot.objects.filter(pk=snapshot.pk, tenant=user.tenant),
            cost_amount=amount, currency=currency, updated_at=timezone.now(),
        )
        write_operation_log(
            tenant=user.tenant, user=user, module="influencers", action="sample_cost_snapshot_refresh",
            object_type="bd_sample_attribution_snapshot", object_id=snapshot.pk,
            before_data={"cost_amount": str(snapshot.cost_amount) if snapshot.cost_amount is not None else None,
                         "currency": snapshot.currency},
            after_data={"cost_amount": str(amount) if amount is not None else None, "currency": currency},
        )
