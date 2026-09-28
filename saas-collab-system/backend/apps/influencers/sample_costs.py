from datetime import datetime, timedelta

from django.utils import timezone

from apps.products.cost_services import effective_cost_for
from apps.products.models import ProductCostVersion


def confirmed_sample_cost_for(*, tenant, sku, warehouse, occurred_at):
    """Resolve a sample cost without substituting purchase prices or zeroes."""
    version = effective_cost_for(
        tenant=tenant, sku=sku, warehouse=warehouse, occurred_at=occurred_at,
    )
    if version is not None and version.confirmed_cost is not None:
        return version, "product_cost_version"

    local_date = timezone.localtime(occurred_at).date()
    month_start = local_date.replace(day=1)
    previous_month_end = month_start - timedelta(days=1)
    previous_month_start = previous_month_end.replace(day=1)
    lower = timezone.make_aware(datetime.combine(previous_month_start, datetime.min.time()))
    upper = timezone.make_aware(datetime.combine(month_start, datetime.min.time()))
    version = (
        ProductCostVersion.objects.filter(
            tenant=tenant,
            sku=sku,
            warehouse=warehouse,
            status=ProductCostVersion.Status.CONFIRMED,
            confirmed_cost__isnull=False,
            effective_from__gte=lower,
            effective_from__lt=upper,
        )
        .order_by("-effective_from", "-version_no", "-pk")
        .first()
    )
    return (version, "product_cost_version_previous_month") if version else (None, "")
