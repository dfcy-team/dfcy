from celery import shared_task
from decimal import Decimal
from django.conf import settings
from django.db import transaction
from django.utils.dateparse import parse_date


@shared_task(name="apps.products.tasks.aggregate_monthly_product_cost_sources", ignore_result=False)
def aggregate_monthly_product_cost_sources(tenant_id, month):
    """Daily-callable safe entry point; disabled by default, never finalizes."""
    if not getattr(settings, "MONTHLY_PRODUCT_COST_ENABLED", False):
        return {"status": "disabled", "enabled": False, "items": []}
    parsed = parse_date(month) if isinstance(month, str) else month
    if not parsed:
        return {"status": "invalid_month", "items": []}
    from .monthly_cost_sources import aggregate_month
    from .monthly_cost_adjustments import sync_late_adjustments
    adjustment_run = sync_late_adjustments(tenant_id, parsed.replace(day=1))
    result = aggregate_month(tenant_id, parsed)
    from .monthly_cost_models import MonthlyProductCost
    from .monthly_cost_services import recalculate_month

    month_date = parsed.replace(day=1)
    written, skipped_finalized = 0, 0
    errors=[]
    for item in result["items"]:
        try:
            with transaction.atomic():
                previous = MonthlyProductCost.objects.filter(tenant_id=tenant_id,
                    sku_id=item["sku_id"], warehouse_id=item["warehouse_id"],
                    month=month_date.replace(year=month_date.year - (month_date.month == 1),
                        month=12 if month_date.month == 1 else month_date.month - 1),
                    status=MonthlyProductCost.Status.FINALIZED).first()
                record, created = MonthlyProductCost.objects.get_or_create(
                    tenant_id=tenant_id, sku_id=item["sku_id"], warehouse_id=item["warehouse_id"],
                    month=month_date)
                if record.status == MonthlyProductCost.Status.FINALIZED:
                    skipped_finalized += 1
                    continue
                record = MonthlyProductCost.objects.select_for_update().get(pk=record.pk)
                if record.status == MonthlyProductCost.Status.FINALIZED:
                    skipped_finalized += 1
                    continue
                # Carry forward finalized balances only. Existing manual opening inputs win.
                if created and previous:
                    record.opening_quantity = previous.closing_quantity
                    record.opening_amount = previous.closing_amount
                elif not created and record.opening_amount is None and previous:
                    record.opening_quantity = previous.closing_quantity
                    record.opening_amount = previous.closing_amount
                record.receipt_quantity = item["receipt_quantity"]
                record.receipt_amount = item["receipt_amount"]
                record.outbound_quantity = item["outbound_quantity"]
                # No registered adjustment is a known zero; provenance remains a separate
                # review watermark until the adjustment feed is integrated.
                record.adjustment_amount = item.get("adjustment_amount", Decimal("0"))
                record.historical_sold_adjustment = item.get("historical_sold_adjustment", Decimal("0"))
                record.other_in_quantity = item.get("other_in_quantity", Decimal("0"))
                record.other_in_amount = item.get("other_in_amount", Decimal("0"))
                record.other_out_quantity = item.get("other_out_quantity", Decimal("0"))
                reasons = list(item["missing_reasons"])
                if not previous and record.opening_amount is None:
                    reasons.append("缺少上月已核定期末余额，期初待补")
                if record.opening_amount is None:
                    reasons.append("期初金额未知")
                if not result["source_complete"]:
                    reasons.append(result["pending_reason"] or "来源完整性待核")
                if item.get("contains_estimates"):
                    reasons.append("入库成本含暂估版本，待审阅")

                if not item["is_complete"]:
                    reasons.extend(item["missing_reasons"])
                record.is_complete = bool(record.opening_amount is not None and item["is_complete"])
                record.missing_reason = "；".join(dict.fromkeys(reasons))[:255]
                record.status = MonthlyProductCost.Status.PENDING_REVIEW
                record.watermark = {**record.watermark, "month": month_date.isoformat(), "source_keys": item["source_keys"],
                    "source_complete": item.get("source_complete", result["source_complete"]), "unmapped_outbounds": result["unmapped_outbounds"],
                    "ambiguous_outbounds": result["ambiguous_outbounds"], "truncated": result["truncated"],
                    "contains_estimates": item.get("contains_estimates", False),
                    "adjustment_source_pending": False, "payment_state": "estimated" if item.get("contains_estimates") else "confirmed"}
                record.save()
                record = recalculate_month(record)
                from .monthly_cost_reconciliation import reconcile_month
                reconcile_month(record)
                written += 1
        except Exception as exc:
            errors.append({"sku_id":item["sku_id"],"warehouse_id":item["warehouse_id"],"reason":str(exc)[:255]})
    result["status"] = "pending_review"
    result["errors"] = errors
    result["written"] = written
    result["skipped_finalized"] = skipped_finalized
    return result
