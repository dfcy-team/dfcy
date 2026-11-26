"""Deterministic CSV import for monthly historical unit costs."""
import csv
import calendar
from datetime import datetime, time
from decimal import Decimal, InvalidOperation
from io import StringIO
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction

from apps.masterdata.models import WarehouseMaster, StatusChoices
from .cost_services import append_cost_version
from .models import ProductCostVersion, ProductSKU

FIELDS = {"tenant_id", "warehouse_id", "sku_code", "month", "unit_cost"}
BUSINESS_TZ = ZoneInfo(getattr(settings, "SUPPLY_CHAIN_TIME_ZONE", "Asia/Shanghai"))


def preview_monthly_cost_csv(*, content, tenant, actor, apply=False):
    """Preview normalized rows; writes only when apply=True and caller explicitly opts in."""
    text = content.decode("utf-8-sig") if isinstance(content, bytes) else content
    reader = csv.DictReader(StringIO(text))
    if not reader.fieldnames or set(reader.fieldnames) != FIELDS:
        raise ValidationError(f"CSV columns must be exactly: {', '.join(sorted(FIELDS))}")
    rows, seen, errors = [], set(), []
    for line, raw in enumerate(reader, 2):
        try:
            if int(raw["tenant_id"]) != tenant.pk:
                raise ValueError("tenant mismatch")
            warehouse = WarehouseMaster.objects.get(pk=int(raw["warehouse_id"]), tenant=tenant, status=StatusChoices.ACTIVE)
            sku = ProductSKU.objects.get(tenant=tenant, sku_code=raw["sku_code"].strip())
            month = datetime.strptime(raw["month"].strip(), "%Y-%m").date().replace(day=1)
            amount = Decimal(raw["unit_cost"].strip())
            if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -4 or amount > Decimal("999999999999.9999"):
                raise ValueError("unit_cost outside nonnegative 4-decimal range")
            key = (warehouse.pk, sku.pk, month)
            if key in seen:
                raise ValueError("duplicate warehouse/SKU/month")
            seen.add(key)
            start = datetime.combine(month, time.min, BUSINESS_TZ)
            next_month = month.month % 12 + 1
            end_date = month.replace(year=month.year + (month.month == 12), month=next_month)
            end = datetime.combine(end_date, time.min, BUSINESS_TZ)
            identical = ProductCostVersion.objects.filter(tenant=tenant, sku=sku, warehouse=warehouse,
                source=ProductCostVersion.Source.IMPORT, status=ProductCostVersion.Status.CONFIRMED,
                effective_from=start, effective_to=end, confirmed_cost=amount, currency="CNY").exists()
            overlap = ProductCostVersion.objects.filter(tenant=tenant, sku=sku, warehouse=warehouse,
                status=ProductCostVersion.Status.CONFIRMED, effective_from__lt=end).filter(
                models_end_filter(start))
            if overlap.exists() and not identical:
                raise ValueError("overlaps existing confirmed cost version")
            rows.append({"line": line, "sku": sku, "warehouse": warehouse, "month": month,
                         "start": start, "end": end, "amount": amount, "identical": identical})
        except (ValueError, InvalidOperation, WarehouseMaster.DoesNotExist, ProductSKU.DoesNotExist) as exc:
            errors.append({"line": line, "error": str(exc)})
    if errors:
        return {"valid": False, "preview": [{"line": r["line"], "sku_code": r["sku"].sku_code, "month": r["month"].isoformat(), "unit_cost": str(r["amount"])} for r in rows], "errors": errors, "applied": 0}
    applied = 0
    if apply:
        with transaction.atomic():
            for row in rows:
                if row["identical"]:
                    continue
                append_cost_version(tenant=tenant, sku=row["sku"], warehouse=row["warehouse"], actor=actor,
                    status=ProductCostVersion.Status.CONFIRMED, source=ProductCostVersion.Source.IMPORT,
                    currency="CNY", purchase_cost=row["amount"], freight_cost=0, duty_cost=0,
                    packaging_cost=0, other_cost=0, system_cost=None, confirmed_cost=row["amount"],
                    effective_from=row["start"], effective_to=row["end"], reason="Monthly history import")
                applied += 1
    return {"valid": True, "preview": [{"line": r["line"], "sku_code": r["sku"].sku_code, "warehouse_id": r["warehouse"].pk, "month": r["month"].isoformat(), "unit_cost": str(r["amount"])} for r in rows], "errors": [], "applied": applied}


def models_end_filter(start):
    from django.db.models import Q
    return Q(effective_to__isnull=True) | Q(effective_to__gt=start)
