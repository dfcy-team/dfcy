import hashlib
from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.audit.services import write_operation_log
from apps.common.security import mask_sensitive_text, sanitize_sensitive_data
from apps.permissions.services import check_user_permission

from .models import BusinessAlert, BusinessAlertActionLog, BusinessAlertRule


OPERATORS = {
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
    "eq": lambda value, threshold: value == threshold,
}


def _decimal(value, field_name):
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValidationError(f"{field_name} must be numeric.") from exc


def _condition(rule, metric_value):
    operator = rule.condition_config.get("operator")
    if operator not in OPERATORS:
        raise ValidationError("condition_config.operator must be one of gt/gte/lt/lte/eq.")
    if "threshold" not in rule.condition_config:
        raise ValidationError("condition_config.threshold is required.")
    threshold = _decimal(rule.condition_config["threshold"], "condition_config.threshold")
    return OPERATORS[operator](metric_value, threshold), threshold


def _create_action_log(*, alert, action, actor=None, note=""):
    log = BusinessAlertActionLog(
        tenant=alert.tenant,
        alert=alert,
        action=action,
        actor=actor,
        note=mask_sensitive_text(note),
    )
    log._action_service_write = True
    log.save()
    return log


@transaction.atomic
def evaluate_business_alert(
    *, tenant, rule, business_type, business_id, metric_value, title, detail,
    evaluated_at=None,
):
    evaluated_at = evaluated_at or timezone.now()
    stored_rule = BusinessAlertRule.objects.filter(pk=rule.pk, tenant=tenant).values("rule_code").first()
    if stored_rule is None:
        raise ValidationError("Business alert rule does not exist in the requested tenant.")
    rules = list(
        BusinessAlertRule.objects.select_for_update()
        .filter(
            tenant=tenant,
            rule_code=stored_rule["rule_code"],
            is_enabled=True,
            effective_at__lte=evaluated_at,
        )
        .order_by("-version", "-id")
    )
    if not rules or rules[0].pk != rule.pk:
        raise ValidationError("Business alert rule is not active.")
    rule = rules[0]
    business_type = str(business_type or "").strip()
    business_id = str(business_id or "").strip()
    if not business_type or not business_id:
        raise ValidationError("business_type and business_id are required.")
    metric_value = _decimal(metric_value, "metric_value")
    triggered, threshold = _condition(rule, metric_value)
    if not triggered:
        return None, False
    raw_key = f"{tenant.id}:{rule.rule_code}:v{rule.version}:{business_type}:{business_id}"
    dedup_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    sanitized_title = mask_sensitive_text(title)[:200]
    sanitized_detail = sanitize_sensitive_data(detail or {})
    alert = BusinessAlert.objects.select_for_update().filter(tenant=tenant, dedup_key=dedup_key).first()
    if alert:
        alert.metric_value = metric_value
        alert.threshold_value = threshold
        alert.title = sanitized_title
        alert.detail = sanitized_detail
        action = BusinessAlertActionLog.Action.DEDUPLICATED
        if alert.status == BusinessAlert.Status.CLOSED:
            alert.status = BusinessAlert.Status.OPEN
            alert.assigned_to = None
            alert.closed_at = None
            alert.triggered_at = evaluated_at
            action = BusinessAlertActionLog.Action.TRIGGERED
        elif alert.status == BusinessAlert.Status.SILENCED and alert.silenced_until and alert.silenced_until <= evaluated_at:
            alert.status = BusinessAlert.Status.OPEN
            alert.silenced_until = None
        alert._action_service_write = True
        alert.save()
        _create_action_log(
            alert=alert,
            action=action,
            note="Mock evaluation; notification suppressed." if alert.status == BusinessAlert.Status.SILENCED else "Mock evaluation; no external notification.",
        )
        return alert, False

    alert = BusinessAlert(
        tenant=tenant,
        rule=rule,
        business_type=business_type,
        business_id=business_id,
        severity=rule.severity,
        title=sanitized_title,
        detail=sanitized_detail,
        metric_value=metric_value,
        threshold_value=threshold,
        dedup_key=dedup_key,
        triggered_at=evaluated_at,
    )
    alert._action_service_write = True
    alert.save()
    _create_action_log(
        alert=alert,
        action=BusinessAlertActionLog.Action.TRIGGERED,
        note="Mock evaluation; no platform, RPA, product, or finance action.",
    )
    return alert, True


def _assert_manager(actor):
    if (
        not actor
        or not actor.is_active
        or actor.user_type != "internal"
        or not check_user_permission(actor, "alerts.manage")
    ):
        raise PermissionDenied("Business alert management permission is required.")


@transaction.atomic
def assign_business_alert(*, alert, actor, assignee, note=""):
    _assert_manager(actor)
    alert = BusinessAlert.objects.select_for_update().get(pk=alert.pk, tenant=actor.tenant)
    if alert.status == BusinessAlert.Status.CLOSED:
        raise ValidationError("Closed business alerts cannot be assigned.")
    if assignee.tenant_id != alert.tenant_id or assignee.user_type != "internal" or not assignee.is_active:
        raise ValidationError("Assignee must be an active internal user in the same tenant.")
    before = alert.status
    alert.status = BusinessAlert.Status.ASSIGNED
    alert.assigned_to = assignee
    alert._action_service_write = True
    alert.save(update_fields=["status", "assigned_to", "updated_at"])
    _record_action(alert, actor, BusinessAlertActionLog.Action.ASSIGNED, before, note or f"Assigned to user {assignee.id}.")
    return alert


@transaction.atomic
def silence_business_alert(*, alert, actor, minutes=None, note=""):
    _assert_manager(actor)
    alert = BusinessAlert.objects.select_for_update().select_related("rule").get(pk=alert.pk, tenant=actor.tenant)
    if alert.status == BusinessAlert.Status.CLOSED:
        raise ValidationError("Closed business alerts cannot be silenced.")
    minutes = alert.rule.silence_minutes if minutes is None else int(minutes)
    if minutes < 1 or minutes > 43200:
        raise ValidationError("Silence duration must be between 1 and 43200 minutes.")
    before = alert.status
    alert.status = BusinessAlert.Status.SILENCED
    alert.silenced_until = timezone.now() + timedelta(minutes=minutes)
    alert._action_service_write = True
    alert.save(update_fields=["status", "silenced_until", "updated_at"])
    _record_action(alert, actor, BusinessAlertActionLog.Action.SILENCED, before, note or f"Silenced for {minutes} minutes.")
    return alert


@transaction.atomic
def close_business_alert(*, alert, actor, note):
    _assert_manager(actor)
    note = str(note or "").strip()
    if not note:
        raise ValidationError("A close note is required.")
    alert = BusinessAlert.objects.select_for_update().get(pk=alert.pk, tenant=actor.tenant)
    if alert.status == BusinessAlert.Status.CLOSED:
        raise ValidationError("Business alert is already closed.")
    before = alert.status
    alert.status = BusinessAlert.Status.CLOSED
    alert.closed_at = timezone.now()
    alert._action_service_write = True
    alert.save(update_fields=["status", "closed_at", "updated_at"])
    _record_action(alert, actor, BusinessAlertActionLog.Action.CLOSED, before, note)
    return alert


def _record_action(alert, actor, action, before_status, note):
    safe_note = mask_sensitive_text(note)
    _create_action_log(alert=alert, action=action, actor=actor, note=safe_note)
    write_operation_log(
        tenant=alert.tenant,
        user=actor,
        module="alerts",
        action=f"business_alert.{action}",
        object_type="BusinessAlert",
        object_id=alert.id,
        before_data={"status": before_status},
        after_data={
            "status": alert.status,
            "note": safe_note,
            "external_platform_called": False,
            "rpa_triggered": False,
            "product_status_changed": False,
            "finance_action_executed": False,
        },
    )
