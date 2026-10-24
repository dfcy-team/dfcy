from datetime import datetime, time, timezone as dt_timezone
from decimal import Decimal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db.models import Count, Sum
from django.utils import timezone

from apps.commerce.models import SalesOrder
from apps.masterdata.models import StoreMaster
from .snapshot_models import SalesNineSnapshot


def capture_store(store, now=None):
    """Capture observed sales at store-local 09:00, only during its five-minute window."""
    if not getattr(store, "pk", None):
        return None, False
    try:
        canonical_store = StoreMaster.objects.select_related("tenant").get(pk=store.pk)
    except StoreMaster.DoesNotExist:
        return None, False

    zone_name = str(canonical_store.timezone or "").strip()
    if not zone_name:
        return None, False
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        return None, False

    now = now or timezone.now()
    if not timezone.is_aware(now):
        return None, False
    local_now = now.astimezone(zone)
    if not (time(9, 0) <= local_now.timetz().replace(tzinfo=None) < time(9, 5)):
        return None, False

    business_date = local_now.date()
    existing = SalesNineSnapshot.objects.filter(
        tenant_id=canonical_store.tenant_id,
        store_id=canonical_store.pk,
        business_date=business_date,
    ).first()
    if existing:
        return existing, False

    local_start = datetime.combine(business_date, time.min, tzinfo=zone)
    target_local = datetime.combine(business_date, time(9, 0), tzinfo=zone)
    start_utc = local_start.astimezone(dt_timezone.utc)
    target_utc = target_local.astimezone(dt_timezone.utc)
    groups = list(
        SalesOrder.objects.filter(
            tenant_id=canonical_store.tenant_id,
            store_id=canonical_store.pk,
            created_at_utc__gte=start_utc,
            created_at_utc__lt=target_utc,
        )
        .exclude(normalized_status="cancelled")
        .values("currency")
        .annotate(sales_amount=Sum("order_total_amount"), order_count=Count("pk"))
        .order_by("currency")
    )
    frozen_groups = [
        {
            "currency": group["currency"],
            "sales_amount": format(group["sales_amount"] if group["sales_amount"] is not None else Decimal("0"), ".4f"),
            "order_count": int(group["order_count"]),
        }
        for group in groups
    ]
    snapshot, created = SalesNineSnapshot.objects.get_or_create(
        tenant_id=canonical_store.tenant_id,
        store_id=canonical_store.pk,
        business_date=business_date,
        defaults={
            "timezone_name": zone_name,
            "target_at": target_utc,
            "captured_at": now.astimezone(dt_timezone.utc),
            "groups": frozen_groups,
            "integrity_status": SalesNineSnapshot.INTEGRITY_UNVERIFIED,
        },
    )
    return snapshot, created
