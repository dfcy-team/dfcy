from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q

from .models import SupplierPerformanceSnapshot, SupplierShipment, SupplierTask


RATE_QUANTUM = Decimal("0.01")


@dataclass(frozen=True)
class PerformanceMetrics:
    total_tasks: int
    on_time_tasks: int
    overdue_tasks: int
    exception_tasks: int
    total_shipments: int
    accurate_shipments: int
    feedback_on_time_count: int


def _percentage(numerator, denominator):
    if denominator == 0:
        return Decimal("0.00")
    return (Decimal(numerator) * Decimal("100") / Decimal(denominator)).quantize(
        RATE_QUANTUM,
        rounding=ROUND_HALF_UP,
    )


def _calculate_score(metrics):
    on_time = _percentage(metrics.on_time_tasks, metrics.total_tasks)
    overdue = _percentage(metrics.overdue_tasks, metrics.total_tasks)
    exception = _percentage(metrics.exception_tasks, metrics.total_tasks)
    accuracy = _percentage(metrics.accurate_shipments, metrics.total_shipments)
    feedback = _percentage(metrics.feedback_on_time_count, metrics.total_tasks)
    score = Decimal("0")
    if metrics.total_tasks:
        score += (
            on_time * Decimal("0.35")
            + (Decimal("100") - overdue) * Decimal("0.20")
            + (Decimal("100") - exception) * Decimal("0.15")
            + feedback * Decimal("0.10")
        )
    if metrics.total_shipments:
        score += accuracy * Decimal("0.20")
    return score.quantize(RATE_QUANTUM, rounding=ROUND_HALF_UP)


def collect_performance_metrics(*, tenant, supplier_id, period_start, period_end):
    tasks = SupplierTask.objects.filter(
        tenant=tenant,
        supplier_id=supplier_id,
    ).filter(
        Q(expected_ship_date__range=(period_start, period_end))
        | Q(expected_ship_date__isnull=True, created_at__date__range=(period_start, period_end))
    )
    shipments = SupplierShipment.objects.filter(
        tenant=tenant,
        supplier_id=supplier_id,
        created_at__date__range=(period_start, period_end),
    )

    total_tasks = tasks.count()
    total_shipments = shipments.count()
    return PerformanceMetrics(
        total_tasks=total_tasks,
        on_time_tasks=tasks.filter(status=SupplierTask.Status.COMPLETED, is_overdue=False).count(),
        overdue_tasks=tasks.filter(is_overdue=True).count(),
        exception_tasks=tasks.filter(Q(status=SupplierTask.Status.EXCEPTION) | ~Q(exception_note="")).distinct().count(),
        total_shipments=total_shipments,
        accurate_shipments=shipments.filter(
            status__in=(SupplierShipment.Status.SUBMITTED, SupplierShipment.Status.RECEIVED),
            ship_quantity__gt=0,
            carton_count__gt=0,
            weight__isnull=False,
            volume__isnull=False,
        ).count(),
        feedback_on_time_count=tasks.exclude(feedback_note="").filter(is_overdue=False).count(),
    )


def calculate_supplier_performance(*, tenant, supplier_id, period_start: date, period_end: date):
    if period_start > period_end:
        raise ValueError("period_start must not be after period_end")

    metrics = collect_performance_metrics(
        tenant=tenant,
        supplier_id=supplier_id,
        period_start=period_start,
        period_end=period_end,
    )
    values = {
        **metrics.__dict__,
        "on_time_rate": _percentage(metrics.on_time_tasks, metrics.total_tasks),
        "overdue_rate": _percentage(metrics.overdue_tasks, metrics.total_tasks),
        "exception_rate": _percentage(metrics.exception_tasks, metrics.total_tasks),
        "shipment_accuracy_rate": _percentage(metrics.accurate_shipments, metrics.total_shipments),
        "feedback_timeliness_rate": _percentage(metrics.feedback_on_time_count, metrics.total_tasks),
        "total_score": _calculate_score(metrics),
    }
    snapshot, _ = SupplierPerformanceSnapshot.objects.update_or_create(
        tenant=tenant,
        supplier_id=supplier_id,
        period_start=period_start,
        period_end=period_end,
        defaults=values,
    )
    return snapshot
