import hashlib
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import APIException

from apps.audit.services import write_operation_log

from .models import InventoryAlert, InventoryAlertEvent, InventoryAlertRule, InventoryAlertType


class InventoryAlertVersionConflict(APIException):
    status_code = 409
    default_detail = "Inventory alert was changed by another user. Reload it and retry."
    default_code = "version_conflict"


def _decimal(value, field_name, *, nullable=False):
    if value is None and nullable:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be numeric.") from exc
    if result < 0:
        raise ValidationError(f"{field_name} cannot be negative.")
    return result


def _threshold(rule):
    key_by_type = {
        InventoryAlertType.STOCKOUT_RISK: "coverage_days",
        InventoryAlertType.LOW_COVERAGE: "coverage_days",
        InventoryAlertType.OVERSTOCK_RISK: "coverage_days",
        InventoryAlertType.SLOW_MOVING: "average_daily_sales",
    }
    key = key_by_type[rule.alert_type]
    if key not in rule.threshold_config:
        raise ValidationError(f"threshold_config.{key} is required.")
    return _decimal(rule.threshold_config[key], f"threshold_config.{key}")


def _is_triggered(alert_type, *, coverage_days, average_daily_sales, available_stock, threshold):
    if alert_type == InventoryAlertType.STOCKOUT_RISK and available_stock == 0 and average_daily_sales and average_daily_sales > 0:
        return True
    if alert_type in {InventoryAlertType.STOCKOUT_RISK, InventoryAlertType.LOW_COVERAGE}:
        return coverage_days is not None and coverage_days < threshold
    if alert_type == InventoryAlertType.OVERSTOCK_RISK:
        return coverage_days is not None and coverage_days > threshold
    return average_daily_sales is not None and average_daily_sales <= threshold and available_stock > 0


@transaction.atomic
def evaluate_inventory_alert(
    *, tenant, rule, sku=None, spu=None, warehouse_code="", available_stock,
    in_transit_stock, average_daily_sales, evaluated_at=None, source_summary=None,
):
    evaluated_at = evaluated_at or timezone.now()
    provenance = source_summary or {"mode": "mock", "contains_real_data": False}
    mode = provenance['mode']
    stored_rule = InventoryAlertRule.objects.filter(pk=rule.pk, tenant=tenant).values("rule_code").first()
    if stored_rule is None:
        raise ValidationError("Inventory alert rule does not exist in the requested tenant.")
    effective_rules = list(
        InventoryAlertRule.objects.select_for_update()
        .filter(
            tenant=tenant,
            rule_code=stored_rule["rule_code"],
            effective_at__lte=evaluated_at,
        )
        .order_by("-version", "-id")
    )
    if not effective_rules or effective_rules[0].pk != rule.pk or not effective_rules[0].is_enabled:
        raise ValidationError("Inventory alert rule is not active.")
    rule = effective_rules[0]
    if not sku and not spu:
        raise ValidationError("A SKU or SPU is required.")
    if sku and sku.tenant_id != tenant.id:
        raise ValidationError("SKU is outside the requested tenant.")
    if spu and spu.tenant_id != tenant.id:
        raise ValidationError("SPU is outside the requested tenant.")
    if sku and spu and sku.spu_id != spu.id:
        raise ValidationError("SKU does not belong to the supplied SPU.")

    available_stock = _decimal(available_stock, "available_stock")
    in_transit_stock = _decimal(in_transit_stock, "in_transit_stock")
    average_daily_sales = _decimal(average_daily_sales, "average_daily_sales", nullable=True)
    if average_daily_sales is not None:
        average_daily_sales = average_daily_sales.quantize(Decimal('0.0001'))
    coverage_days = None
    if average_daily_sales and average_daily_sales > 0:
        coverage_days = ((available_stock + in_transit_stock) / average_daily_sales).quantize(Decimal('0.0001'))
    threshold = _threshold(rule)
    if not _is_triggered(
        rule.alert_type,
        coverage_days=coverage_days,
        average_daily_sales=average_daily_sales,
        available_stock=available_stock,
        threshold=threshold,
    ):
        return None, False

    product_key = f"sku:{sku.id}" if sku else f"spu:{spu.id}"
    raw_key = (f"{tenant.id}:{rule.rule_code}:real:{product_key}:{warehouse_code}" if mode == 'real_observation'
               else f"{tenant.id}:{rule.rule_code}:v{rule.version}:{product_key}:{warehouse_code}")
    dedup_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    existing = InventoryAlert.objects.select_for_update().filter(tenant=tenant, dedup_key=dedup_key).first()
    if mode == 'real_observation' and not existing:
        # Reuse a pre-upgrade alert, including its owner and follow-up history.
        existing = InventoryAlert.objects.select_for_update().filter(tenant=tenant, sku=sku, spu=spu or (sku.spu if sku else None),
            warehouse_code=warehouse_code, rule__rule_code=rule.rule_code,
            source_summary__mode='real_observation').order_by('-triggered_at', '-pk').first()
    data_at = parse_datetime(provenance.get('data_at') or '') if mode == 'real_observation' else None
    data_valid_until = data_at + timedelta(hours=24) if data_at else None
    reason = (f'可用库存 {available_stock}，按期有效到货 {in_transit_stock}，日均销量 {average_daily_sales}；'
              + (f'有销量需求但可用库存为零；命中 {rule.rule_code} v{rule.version}。'
                 if rule.alert_type == InventoryAlertType.STOCKOUT_RISK and available_stock == 0 and average_daily_sales else
                 f'{"日均销量" if rule.alert_type == InventoryAlertType.SLOW_MOVING else "覆盖天数"} '
                 f'{average_daily_sales if rule.alert_type == InventoryAlertType.SLOW_MOVING else coverage_days} '
                 f'{"≤" if rule.alert_type == InventoryAlertType.SLOW_MOVING else ">" if rule.alert_type == InventoryAlertType.OVERSTOCK_RISK else "<"} '
                 f'阈值 {threshold}；命中 {rule.rule_code} v{rule.version}。')) if mode == 'real_observation' else (
                 f'Mock evaluation matched {rule.alert_type} rule {rule.rule_code} v{rule.version}.')
    if existing:
        existing.rule = rule
        existing.severity = rule.severity
        existing.alert_type = rule.alert_type
        existing.available_stock = available_stock
        existing.in_transit_stock = in_transit_stock
        existing.average_daily_sales = average_daily_sales
        existing.coverage_days = coverage_days
        existing.threshold_value = threshold
        existing.reason = reason
        existing.source_summary = {**provenance, 'rule_version': rule.version}
        existing.evaluation_state = 'risk' if mode == 'real_observation' else 'unverified'
        existing.data_valid_until = data_valid_until
        existing.version += 1
        event_type = InventoryAlertEvent.EventType.DEDUPLICATED
        if existing.status == InventoryAlert.Status.CLOSED:
            existing.status = InventoryAlert.Status.OPEN
            existing.closed_at = None
            existing.assigned_to = None
            existing.resolution = ''
            existing.action_plan = ''
            existing.due_date = None
            existing.triggered_at = evaluated_at
            event_type = InventoryAlertEvent.EventType.TRIGGERED
        elif existing.status == InventoryAlert.Status.SILENCED and existing.silenced_until and existing.silenced_until <= evaluated_at:
            existing.status = InventoryAlert.Status.OPEN
            existing.silenced_until = None
        existing.save()
        InventoryAlertEvent.objects.create(
            tenant=tenant,
            alert=existing,
            event_type=event_type,
            detail={"mode": mode, "notification_suppressed": existing.status == InventoryAlert.Status.SILENCED},
        )
        return existing, False

    alert = InventoryAlert.objects.create(
        tenant=tenant,
        rule=rule,
        spu=spu or (sku.spu if sku else None),
        sku=sku,
        warehouse_code=str(warehouse_code or "").strip(),
        alert_type=rule.alert_type,
        severity=rule.severity,
        available_stock=available_stock,
        in_transit_stock=in_transit_stock,
        average_daily_sales=average_daily_sales,
        coverage_days=coverage_days,
        threshold_value=threshold,
        dedup_key=dedup_key,
        reason=reason,
        source_summary={**provenance, "rule_version": rule.version},
        evaluation_state='risk' if mode == 'real_observation' else 'unverified',
        data_valid_until=data_valid_until,
        triggered_at=evaluated_at,
    )
    InventoryAlertEvent.objects.create(
        tenant=tenant,
        alert=alert,
        event_type=InventoryAlertEvent.EventType.TRIGGERED,
        detail={"mode": mode, "notification_sent": False},
    )
    return alert, True


@transaction.atomic
def assign_inventory_alert(*, alert, actor, assignee, expected_version=None):
    alert = InventoryAlert.objects.select_for_update().get(pk=alert.pk, tenant=actor.tenant)
    _check_version(alert, expected_version)
    if alert.status == InventoryAlert.Status.CLOSED:
        raise ValidationError("Closed inventory alerts cannot be assigned.")
    if assignee.tenant_id != alert.tenant_id or assignee.user_type != "internal" or not assignee.is_active:
        raise ValidationError("Assignee must be an active internal user in the same tenant.")
    before = alert.status
    before_data = _follow_up_state(alert)
    alert.assigned_to = assignee
    alert.status = InventoryAlert.Status.ASSIGNED
    alert.version += 1
    alert.save(update_fields=["assigned_to", "status", "version", "updated_at"])
    _record_action(alert, actor, InventoryAlertEvent.EventType.ASSIGNED, before, {"assignee_id": assignee.id}, before_data=before_data)
    return alert


@transaction.atomic
def silence_inventory_alert(*, alert, actor, minutes=None, expected_version=None):
    alert = InventoryAlert.objects.select_for_update().select_related("rule").get(pk=alert.pk, tenant=actor.tenant)
    _check_version(alert, expected_version)
    if alert.status == InventoryAlert.Status.CLOSED:
        raise ValidationError("Closed inventory alerts cannot be silenced.")
    silence_minutes = alert.rule.silence_minutes if minutes is None else int(minutes)
    if silence_minutes < 1 or silence_minutes > 43200:
        raise ValidationError("Silence duration must be between 1 and 43200 minutes.")
    before = alert.status
    before_data = _follow_up_state(alert)
    alert.status = InventoryAlert.Status.SILENCED
    alert.silenced_until = timezone.now() + timedelta(minutes=silence_minutes)
    alert.version += 1
    alert.save(update_fields=["status", "silenced_until", "version", "updated_at"])
    _record_action(alert, actor, InventoryAlertEvent.EventType.SILENCED, before, {"minutes": silence_minutes}, before_data=before_data)
    return alert


@transaction.atomic
def close_inventory_alert(*, alert, actor, reason, expected_version=None):
    alert = InventoryAlert.objects.select_for_update().get(pk=alert.pk, tenant=actor.tenant)
    _check_version(alert, expected_version)
    reason = str(reason or "").strip()
    if not reason:
        raise ValidationError("A close reason is required.")
    if alert.status == InventoryAlert.Status.CLOSED:
        raise ValidationError("Inventory alert is already closed.")
    before = alert.status
    before_data = _follow_up_state(alert)
    alert.status = InventoryAlert.Status.CLOSED
    alert.closed_at = timezone.now()
    alert.resolution = reason
    alert.version += 1
    alert.save(update_fields=["status", "closed_at", "resolution", "version", "updated_at"])
    _record_action(alert, actor, InventoryAlertEvent.EventType.CLOSED, before, {"reason": reason, "resolution": reason}, before_data=before_data)
    return alert


@transaction.atomic
def update_inventory_alert_follow_up(*, alert, actor, expected_version, values):
    alert = InventoryAlert.objects.select_for_update().get(pk=alert.pk, tenant=actor.tenant)
    _check_version(alert, expected_version)
    if alert.status == InventoryAlert.Status.CLOSED:
        raise ValidationError("Closed inventory alerts are read-only.")
    before_status = alert.status
    before_data = _follow_up_state(alert)
    assignee = values.get("assigned_to", alert.assigned_to)
    if assignee and (assignee.tenant_id != alert.tenant_id or assignee.user_type != "internal" or not assignee.is_active):
        raise ValidationError("Assignee must be an active internal user in the same tenant.")
    alert.assigned_to = assignee
    for field in ("action_plan", "due_date", "status"):
        if field in values:
            setattr(alert, field, values[field])
    if "assigned_to" in values and assignee is not None and "status" not in values and alert.status == InventoryAlert.Status.OPEN:
        alert.status = InventoryAlert.Status.ASSIGNED
    if "assigned_to" in values and assignee is None and "status" not in values and alert.status == InventoryAlert.Status.ASSIGNED:
        alert.status = InventoryAlert.Status.OPEN
    if alert.status == InventoryAlert.Status.ASSIGNED and assignee is None:
        raise ValidationError("An assigned alert must have an assignee.")
    alert.version += 1
    alert.save(update_fields=["assigned_to", "action_plan", "due_date", "status", "version", "updated_at"])
    _record_action(
        alert, actor, InventoryAlertEvent.EventType.FOLLOW_UP_UPDATED, before_status,
        {"before": before_data, "after": _follow_up_state(alert)}, before_data=before_data,
    )
    return alert


def _check_version(alert, expected_version):
    if expected_version is not None and alert.version != expected_version:
        raise InventoryAlertVersionConflict()


def _follow_up_state(alert):
    return {
        "assigned_to_id": alert.assigned_to_id,
        "action_plan": alert.action_plan,
        "due_date": alert.due_date.isoformat() if alert.due_date else None,
        "resolution": alert.resolution,
        "status": alert.status,
        "version": alert.version,
    }


def _record_action(alert, actor, event_type, before_status, detail, *, before_data=None):
    InventoryAlertEvent.objects.create(
        tenant=alert.tenant,
        alert=alert,
        event_type=event_type,
        actor=actor,
        detail=detail,
    )
    write_operation_log(
        tenant=alert.tenant,
        user=actor,
        module="alerts",
        action=f"inventory_alert.{event_type}",
        object_type="InventoryAlert",
        object_id=alert.id,
        before_data=before_data or {"status": before_status},
        after_data={"status": alert.status, "version": alert.version, **detail},
    )
