from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import ProductCostVersion, ProductSKU


def effective_cost_for(*, tenant, sku, occurred_at):
    return (
        ProductCostVersion.objects.filter(
            tenant=tenant,
            sku=sku,
            status=ProductCostVersion.Status.CONFIRMED,
            effective_from__lte=occurred_at,
        )
        .filter(Q(effective_to__isnull=True) | Q(effective_to__gt=occurred_at))
        .order_by("-effective_from", "-version_no")
        .first()
    )


@transaction.atomic
def append_cost_version(*, tenant, sku, actor, **values):
    locked_sku = ProductSKU.objects.select_for_update().get(pk=sku.pk, tenant=tenant)
    existing = ProductCostVersion.objects.select_for_update().filter(tenant=tenant, sku=locked_sku)
    start = values["effective_from"]
    end = values.get("effective_to")
    if values.get("status") == ProductCostVersion.Status.CONFIRMED:
        overlap = existing.filter(status=ProductCostVersion.Status.CONFIRMED).filter(
            Q(effective_to__isnull=True) | Q(effective_to__gt=start)
        )
        if end is not None:
            overlap = overlap.filter(effective_from__lt=end)
        overlapping = list(overlap.order_by("effective_from", "version_no"))
        closable = [item for item in overlapping if item.effective_to is None and item.effective_from < start]
        if len(overlapping) != len(closable) or len(closable) > 1:
            raise ValidationError({"effective_from": "Cost effective interval overlaps an existing confirmed version."})
        if closable:
            ProductCostVersion.objects.filter(pk=closable[0].pk, effective_to__isnull=True).update(effective_to=start)
    version_no = (existing.order_by("-version_no").values_list("version_no", flat=True).first() or 0) + 1
    return ProductCostVersion.objects.create(
        tenant=tenant, sku=locked_sku, created_by=actor, version_no=version_no, **values
    )


def preview_system_backfill(*, tenant, sku_ids=None):
    queryset = ProductSKU.objects.filter(tenant=tenant, is_active=True).order_by("sku_code")
    if sku_ids:
        queryset = queryset.filter(id__in=sku_ids)
    rows = []
    for sku in queryset:
        purchase = sku.purchase_price or Decimal("0")
        rows.append({
            "sku_id": sku.id,
            "sku_code": sku.sku_code,
            "purchase_cost": purchase,
            "system_cost": purchase,
            "status": ProductCostVersion.Status.PENDING,
            "will_write": False,
        })
    return rows


@transaction.atomic
def execute_system_backfill(*, tenant, actor, effective_from, sku_ids=None, reason="System cost backfill"):
    rows = preview_system_backfill(tenant=tenant, sku_ids=sku_ids)
    created = []
    unchanged = []
    for row in rows:
        sku = ProductSKU.objects.get(tenant=tenant, pk=row["sku_id"])
        existing = ProductCostVersion.objects.filter(
            tenant=tenant,
            sku=sku,
            status=ProductCostVersion.Status.PENDING,
            source=ProductCostVersion.Source.SYSTEM,
            effective_from=effective_from,
            system_cost=row["system_cost"],
        ).first()
        if existing:
            unchanged.append(existing.pk)
            continue
        version = append_cost_version(
            tenant=tenant,
            sku=sku,
            actor=actor,
            status=ProductCostVersion.Status.PENDING,
            source=ProductCostVersion.Source.SYSTEM,
            currency="CNY",
            purchase_cost=row["purchase_cost"],
            freight_cost=Decimal("0"),
            duty_cost=Decimal("0"),
            packaging_cost=Decimal("0"),
            other_cost=Decimal("0"),
            system_cost=row["system_cost"],
            confirmed_cost=None,
            effective_from=effective_from,
            effective_to=None,
            reason=reason,
        )
        created.append(version.pk)
    return {"created": len(created), "created_ids": created, "unchanged": len(unchanged), "unchanged_ids": unchanged}


@transaction.atomic
def confirm_pending_cost_version(*, tenant, version_id, actor, confirmed_cost=None, reason=""):
    version = ProductCostVersion.objects.select_for_update().select_related("sku").get(
        tenant=tenant, pk=version_id
    )
    if version.status != ProductCostVersion.Status.PENDING:
        raise ValidationError({"status": "Only a pending cost version can be confirmed."})
    ProductSKU.objects.select_for_update().get(tenant=tenant, pk=version.sku_id)
    overlap = ProductCostVersion.objects.select_for_update().filter(
        tenant=tenant,
        sku=version.sku,
        status=ProductCostVersion.Status.CONFIRMED,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gt=version.effective_from))
    if version.effective_to is not None:
        overlap = overlap.filter(effective_from__lt=version.effective_to)
    overlapping = list(overlap.order_by("effective_from", "version_no"))
    closable = [item for item in overlapping if item.effective_to is None and item.effective_from < version.effective_from]
    if len(overlapping) != len(closable) or len(closable) > 1:
        raise ValidationError({"effective_from": "Cost effective interval overlaps an existing confirmed version."})
    if closable:
        ProductCostVersion.objects.filter(pk=closable[0].pk, effective_to__isnull=True).update(
            effective_to=version.effective_from
        )
    amount = confirmed_cost if confirmed_cost is not None else version.system_cost
    if amount is None:
        raise ValidationError({"confirmed_cost": "A confirmed cost is required."})
    try:
        amount = Decimal(str(amount))
    except InvalidOperation as exc:
        raise ValidationError({"confirmed_cost": "Use a decimal number."}) from exc
    if amount < 0:
        raise ValidationError({"confirmed_cost": "Cost must be non-negative."})
    ProductCostVersion.objects.filter(pk=version.pk, status=ProductCostVersion.Status.PENDING).update(
        status=ProductCostVersion.Status.CONFIRMED,
        confirmed_cost=amount,
        reason=reason or version.reason,
    )
    version.refresh_from_db()
    return version
