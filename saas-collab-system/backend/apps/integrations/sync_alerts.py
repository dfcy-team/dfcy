from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.audit.models import NotificationMessage
from apps.audit.services import write_operation_log

from .models import SyncAlertIncident
from .security import sanitize_text


def _message_type(sync_job):
    return f"sync_job_failure:{sync_job.id}"


def upsert_sync_failure_alert(sync_job, *, sync_run=None, error_code="", message=""):
    """Create one open operator alert per sync job and refresh it on repeats."""
    owner = sync_job.integration_config.created_by
    run_id = getattr(sync_run, "run_id", "") or "not-created"
    error_code = str(error_code or getattr(sync_run, "error_code", "") or "SYNC_FAILED")[:80]
    masked_message = sanitize_text(
        message or getattr(sync_run, "masked_error_message", "") or "Readonly synchronization failed."
    )[:500]
    defaults = {
        "title": f"只读同步异常 · 任务 #{sync_job.id}",
        "message": (
            f"资源 {sync_job.resource_type}；运行 {run_id}；错误 {error_code}；"
            f"{masked_message}。请检查授权、读取能力、来源优先级和调度配置。"
        ),
        "message_type": _message_type(sync_job),
        "status": NotificationMessage.Status.UNREAD,
    }
    with transaction.atomic():
        type(sync_job).objects.select_for_update().get(pk=sync_job.pk)
        notification = NotificationMessage.objects.filter(
            tenant=sync_job.tenant,
            user=owner,
            message_type=_message_type(sync_job),
            status__in=(NotificationMessage.Status.UNREAD, NotificationMessage.Status.READ),
        ).first()
        created = notification is None
        if notification:
            NotificationMessage.objects.filter(pk=notification.pk).update(**defaults)
            notification.refresh_from_db()
        else:
            notification = NotificationMessage.objects.create(
                tenant=sync_job.tenant,
                user=owner,
                **defaults,
            )
        incident, incident_created = SyncAlertIncident.objects.select_for_update().get_or_create(
            sync_job=sync_job,
            defaults={"tenant": sync_job.tenant, "notification": notification},
        )
        incident.notification = notification
        incident.status = SyncAlertIncident.Status.OPEN
        incident.acknowledged_by = None
        incident.acknowledged_at = None
        incident.occurrence_count = 1 if incident_created else incident.occurrence_count + 1
        incident.last_sync_run = sync_run
        incident.last_error_code = error_code
        incident.masked_message = masked_message
        incident.resolved_by = None
        incident.resolved_at = None
        incident.resolution_note = ""
        incident.full_clean()
        incident.save()
        return notification, created


def resolve_sync_failure_alert(sync_job, sync_run=None):
    with transaction.atomic():
        archived = NotificationMessage.objects.filter(
            tenant=sync_job.tenant,
            user=sync_job.integration_config.created_by,
            message_type=_message_type(sync_job),
            status__in=(NotificationMessage.Status.UNREAD, NotificationMessage.Status.READ),
        ).update(status=NotificationMessage.Status.ARCHIVED)
        incident = SyncAlertIncident.objects.select_for_update().filter(sync_job=sync_job).first()
        if incident and incident.status != SyncAlertIncident.Status.RESOLVED:
            incident.status = SyncAlertIncident.Status.RESOLVED
            incident.resolved_at = timezone.now()
            incident.resolved_by = None
            incident.last_sync_run = sync_run or incident.last_sync_run
            incident.resolution_note = "Recovered by a successful readonly synchronization."
            incident.save(update_fields=[
                "status", "resolved_at", "resolved_by", "last_sync_run", "resolution_note", "updated_at"
            ])
        return archived


def _require_actor(incident, actor):
    if not actor or actor.tenant_id != incident.tenant_id:
        raise PermissionDenied("Incident action is outside the current tenant.")


def _note(value, *, required=False):
    value = sanitize_text(value).strip()[:2000]
    if required and len(value) < 3:
        raise ValidationError({"note": "A resolution note of at least 3 characters is required."})
    return value


def _audit(incident, actor, action, before):
    write_operation_log(
        tenant=incident.tenant, user=actor, module="integrations", action=action,
        object_type="sync_alert_incident", object_id=incident.id,
        before_data=before,
        after_data={
            "status": incident.status, "assignee_id": incident.assignee_id,
            "resolution_note": incident.resolution_note,
        },
    )


def acknowledge_incident(incident, actor, note=""):
    _require_actor(incident, actor)
    if incident.status == SyncAlertIncident.Status.RESOLVED:
        raise ValidationError("Resolved incidents cannot be acknowledged.")
    before = {"status": incident.status, "assignee_id": incident.assignee_id}
    incident.status = SyncAlertIncident.Status.ACKNOWLEDGED
    incident.acknowledged_by = actor
    incident.acknowledged_at = timezone.now()
    if note:
        incident.resolution_note = _note(note)
    incident.save()
    _audit(incident, actor, "acknowledge_sync_incident", before)
    return incident


def assign_incident(incident, actor, assignee, note=""):
    _require_actor(incident, actor)
    if incident.status == SyncAlertIncident.Status.RESOLVED:
        raise ValidationError("Resolved incidents cannot be assigned.")
    if not assignee or assignee.tenant_id != incident.tenant_id or not assignee.is_active:
        raise ValidationError({"assignee_id": "Assignee must be an active user in the same tenant."})
    before = {"status": incident.status, "assignee_id": incident.assignee_id}
    incident.assignee = assignee
    if note:
        incident.resolution_note = _note(note)
    incident.full_clean()
    incident.save()
    _audit(incident, actor, "assign_sync_incident", before)
    return incident


def add_incident_note(incident, actor, note):
    _require_actor(incident, actor)
    before = {"status": incident.status, "assignee_id": incident.assignee_id, "resolution_note": incident.resolution_note}
    incident.resolution_note = _note(note, required=True)
    incident.save(update_fields=["resolution_note", "updated_at"])
    _audit(incident, actor, "note_sync_incident", before)
    return incident


def resolve_incident(incident, actor, note):
    _require_actor(incident, actor)
    before = {"status": incident.status, "assignee_id": incident.assignee_id}
    incident.status = SyncAlertIncident.Status.RESOLVED
    incident.resolved_by = actor
    incident.resolved_at = timezone.now()
    incident.resolution_note = _note(note, required=True)
    incident.save()
    if incident.notification_id:
        NotificationMessage.objects.filter(pk=incident.notification_id).update(status=NotificationMessage.Status.ARCHIVED)
    _audit(incident, actor, "resolve_sync_incident", before)
    return incident
