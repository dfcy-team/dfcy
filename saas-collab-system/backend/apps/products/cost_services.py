from decimal import Decimal

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
    overlap = existing.filter(Q(effective_to__isnull=True) | Q(effective_to__gt=start))
    if end is not None:
        overlap = overlap.filter(effective_from__lt=end)
    overlapping = list(overlap.order_by("effective_from", "version_no"))
    closable = [item for item in overlapping if item.effective_to is None and item.effective_from < start]
    if len(overlapping) != len(closable) or len(closable) > 1:
        raise ValidationError({"effective_from": "Cost effective interval overlaps an existing version."})
    # Closing the immediately preceding open interval is the only permitted
    # mutation. Amounts and audit evidence remain immutable; the new fact is
    # still appended as a separate version.
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
