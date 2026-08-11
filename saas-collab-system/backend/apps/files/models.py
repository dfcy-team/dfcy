from contextlib import contextmanager
from contextvars import ContextVar
from string import hexdigits

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.tenants.models import Tenant


_attachment_domain_write_depth = ContextVar("attachment_domain_write_depth", default=0)


@contextmanager
def _attachment_domain_write_context():
    token = _attachment_domain_write_depth.set(_attachment_domain_write_depth.get() + 1)
    try:
        yield
    finally:
        _attachment_domain_write_depth.reset(token)


def _attachment_domain_write_allowed():
    return _attachment_domain_write_depth.get() > 0


class ProtectedAttachmentQuerySet(models.QuerySet):
    """Keep attachment metadata and security history behind domain services."""

    def update(self, **kwargs):
        raise ValidationError("Controlled attachments require the audited domain service.")

    def bulk_update(self, objs, fields, batch_size=None):
        raise ValidationError("Controlled attachments require the audited domain service.")

    def bulk_create(
        self,
        objs,
        batch_size=None,
        ignore_conflicts=False,
        update_conflicts=False,
        update_fields=None,
        unique_fields=None,
    ):
        raise ValidationError("Controlled attachments require the audited domain service.")

    def delete(self):
        raise ValidationError("Controlled attachment history is retained.")


class AppendOnlyAttachmentQuerySet(ProtectedAttachmentQuerySet):
    pass


class AttachmentDomainModel(models.Model):
    objects = ProtectedAttachmentQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _attachment_domain_write_allowed():
            raise ValidationError("Controlled attachment records require the audited domain service.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Controlled attachment history is retained.")


class AttachmentFile(models.Model):
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="attachment_files")
    file_name = models.CharField(max_length=255)
    file_path = models.CharField(max_length=500)
    file_type = models.CharField(max_length=100, blank=True)
    file_size = models.PositiveBigIntegerField(default=0)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_files",
    )
    business_type = models.CharField(max_length=80, blank=True)
    business_id = models.CharField(max_length=100, blank=True)
    is_private = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["tenant", "business_type", "business_id"], name="idx_attachment_business"),
        ]

    def __str__(self):
        return self.file_name


class ControlledAttachment(AttachmentDomainModel):
    """A private, scan-gated image asset used as handover evidence.

    ``AttachmentFile`` remains a backwards-compatible generic file record for
    existing product/RPA features.  It is deliberately not reused as evidence
    because it has no content hash, scan state, immutable business version or
    audited write boundary.
    """

    class State(models.TextChoices):
        UPLOADING = "uploading", "Uploading"
        UPLOADED = "uploaded", "Uploaded"
        SCANNING = "scanning", "Scanning"
        ACCEPTED = "accepted", "Accepted"
        REJECTED = "rejected", "Rejected"
        QUARANTINED = "quarantined", "Quarantined"
        SUPERSEDED = "superseded", "Superseded"
        DELETED = "deleted", "Deleted"

    class ScanStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SCANNING = "scanning", "Scanning"
        PASSED = "passed", "Passed"
        FAILED = "failed", "Failed"
        QUARANTINED = "quarantined", "Quarantined"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="controlled_attachments")
    attachment_no = models.CharField(max_length=96)
    owner_type = models.CharField(max_length=32)
    owner_id = models.PositiveBigIntegerField()
    business_type = models.CharField(max_length=80, default="consolidation_handover")
    business_id = models.CharField(max_length=128)
    business_version = models.PositiveIntegerField()
    file_name = models.CharField(max_length=255, blank=True)
    extension = models.CharField(max_length=12, blank=True)
    media_type = models.CharField(max_length=80, blank=True)
    byte_size = models.PositiveBigIntegerField(default=0)
    # ``NULL`` represents the pre-upload state.  A plain multi-column unique
    # constraint (rather than a partial index) then remains enforceable on
    # MySQL 8 as well as SQLite/PostgreSQL; multiple unfinished rows may all
    # carry NULL, while finalized content is unique per binding.
    sha256 = models.CharField(max_length=64, null=True, blank=True, default=None)
    # The value is generated by the service and is never accepted from a
    # client.  ``null`` permits a quarantined pre-upload row only for explicit
    # migration/repair tooling; normal service-created rows always have it.
    storage_key = models.CharField(max_length=255, unique=True, null=True, blank=True)
    state = models.CharField(max_length=20, choices=State.choices, default=State.UPLOADING)
    scan_status = models.CharField(max_length=20, choices=ScanStatus.choices, default=ScanStatus.PENDING)
    scan_engine = models.CharField(max_length=80, blank=True)
    scan_engine_version = models.CharField(max_length=40, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    rejection_code = models.CharField(max_length=80, blank=True)
    created_by_type = models.CharField(max_length=32)
    created_by_id = models.PositiveBigIntegerField()
    channel = models.CharField(max_length=32, default="internal")
    accepted_at = models.DateTimeField(null=True, blank=True)
    superseded_by = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="superseded_attachments",
    )
    retention_policy_version = models.CharField(max_length=40, default="attach-v1")
    upload_idempotency_key = models.CharField(max_length=128)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["tenant_id", "-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "attachment_no"],
                name="uniq_controlled_attachment_no",
            ),
            models.UniqueConstraint(
                fields=["tenant", "upload_idempotency_key"],
                name="uniq_controlled_attachment_upload_key",
            ),
            models.UniqueConstraint(
                fields=["tenant", "sha256", "business_type", "business_id", "business_version"],
                name="uniq_controlled_attachment_content_binding",
            ),
            models.CheckConstraint(
                condition=models.Q(owner_id__gt=0) & models.Q(business_version__gt=0),
                name="controlled_attachment_identity_positive",
            ),
            models.CheckConstraint(
                condition=models.Q(byte_size__gte=0),
                name="controlled_attachment_size_nonnegative",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "business_type", "business_id", "business_version", "state"],
                name="idx_ctrl_attach_binding",
            ),
            models.Index(
                fields=["tenant", "owner_type", "owner_id", "state"],
                name="idx_ctrl_attach_owner",
            ),
        ]

    @property
    def file_name_display(self):
        return self.file_name

    @property
    def file_extension(self):
        return self.extension

    @property
    def release_version(self):
        return self.business_version

    def clean(self):
        if not self.attachment_no or not self.attachment_no.strip():
            raise ValidationError({"attachment_no": "Attachment number is required."})
        if not self.owner_type or not self.owner_type.strip() or self.owner_id <= 0:
            raise ValidationError("Attachment owner binding is required.")
        if self.business_type != "consolidation_handover":
            raise ValidationError("Only consolidation handover evidence is enabled in this wave.")
        if not str(self.business_id or "").strip() or self.business_version <= 0:
            raise ValidationError("Attachment business binding is incomplete.")
        if not self.created_by_type or self.created_by_id <= 0:
            raise ValidationError("Attachment creator identity is required.")
        if self.sha256 and (
            len(self.sha256) != 64
            or any(character not in hexdigits for character in self.sha256)
        ):
            raise ValidationError("Attachment SHA-256 must be a 64-character hexadecimal value.")
        if self.storage_key and (
            "\x00" in self.storage_key
            or "://" in self.storage_key
            or self.storage_key.lower().startswith(("http:", "https:", "file:"))
        ):
            raise ValidationError("Attachment storage key cannot be an arbitrary URL.")
        if self.media_type and self.media_type not in {"image/jpeg", "image/png"}:
            raise ValidationError("Only JPEG and PNG evidence are permitted.")
        if self.extension and self.extension.lower().lstrip(".") not in {"jpg", "jpeg", "png"}:
            raise ValidationError("Only JPEG and PNG extensions are permitted.")
        if self.state in {
            self.State.SCANNING,
            self.State.ACCEPTED,
            self.State.REJECTED,
            self.State.QUARANTINED,
            self.State.SUPERSEDED,
        } and not self.sha256:
            raise ValidationError("Scanned attachment metadata must include a server SHA-256.")
        if self.state == self.State.ACCEPTED:
            if self.scan_status != self.ScanStatus.PASSED:
                raise ValidationError("Only a passed scan can be accepted.")
            if not self.media_type or self.byte_size <= 0 or not self.storage_key:
                raise ValidationError("Accepted evidence requires complete file metadata and storage binding.")
            if self.accepted_at is None:
                raise ValidationError("Accepted evidence requires accepted_at.")
        if self.state == self.State.SUPERSEDED and self.superseded_by_id is None:
            raise ValidationError("Superseded evidence requires a replacement reference.")
        if self.superseded_by_id and self.superseded_by_id == self.pk:
            raise ValidationError("An attachment cannot supersede itself.")

    def save(self, *args, **kwargs):
        if self.pk and not self._state.adding:
            # Read the authoritative state before validating the caller's
            # in-memory object.  Otherwise a caller could fetch an accepted
            # row, assign ``state='uploaded'`` and save mutable metadata in a
            # domain context, silently bypassing the historical guard.
            original = type(self).objects.filter(pk=self.pk).values(
                "state", "tenant_id", "owner_type", "owner_id", "business_type", "business_id",
                "business_version", "storage_key", "sha256", "media_type", "byte_size",
                "extension", "file_name", "upload_idempotency_key", "superseded_by_id",
            ).first()
            if original:
                terminal_states = {self.State.ACCEPTED, self.State.SUPERSEDED, self.State.DELETED}
                original_state = original["state"]
                state_transition_allowed = bool(
                    original_state == self.State.ACCEPTED
                    and self.state == self.State.SUPERSEDED
                    and getattr(self, "_allow_attachment_state_transition", False)
                )
                if original_state in terminal_states:
                    if self.state != original_state and not state_transition_allowed:
                        raise ValidationError("Accepted/superseded/deleted attachment state cannot be rolled back.")
                    immutable = {
                        "tenant", "owner_type", "owner_id", "business_type", "business_id",
                        "business_version", "storage_key", "sha256", "media_type", "byte_size",
                        "extension", "file_name", "upload_idempotency_key",
                    }
                    changed = {
                        field for field in immutable
                        if getattr(self, f"{field}_id", getattr(self, field, None))
                        != original.get(f"{field}_id", original.get(field))
                    }
                    if changed and not getattr(self, "_allow_attachment_immutable_write", False):
                        raise ValidationError("Accepted attachment metadata is immutable; supersede with a new asset.")
                    if (
                        original_state == self.State.ACCEPTED
                        and self.superseded_by_id != original.get("superseded_by_id")
                        and not state_transition_allowed
                    ):
                        raise ValidationError("An accepted attachment can only be superseded by the audited service.")
                    if original_state in {self.State.SUPERSEDED, self.State.DELETED}:
                        if self.superseded_by_id != original.get("superseded_by_id"):
                            raise ValidationError("Superseded/deleted attachment history is immutable.")
        return super().save(*args, **kwargs)


class AttachmentUploadSession(AttachmentDomainModel):
    class State(models.TextChoices):
        ACTIVE = "active", "Active"
        FINISHED = "finished", "Finished"
        CANCELLED = "cancelled", "Cancelled"
        EXPIRED = "expired", "Expired"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="attachment_upload_sessions")
    attachment = models.ForeignKey(
        ControlledAttachment,
        on_delete=models.PROTECT,
        related_name="upload_sessions",
    )
    upload_token_hash = models.CharField(max_length=64)
    storage_key = models.CharField(max_length=255)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    state = models.CharField(max_length=16, choices=State.choices, default=State.ACTIVE)
    expires_at = models.DateTimeField()
    created_by_type = models.CharField(max_length=32)
    created_by_id = models.PositiveBigIntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uniq_attachment_upload_session_key",
            ),
            models.UniqueConstraint(
                fields=["storage_key"],
                name="uniq_attachment_upload_session_storage_key",
            ),
        ]

    def clean(self):
        if self.attachment_id and self.attachment.tenant_id != self.tenant_id:
            raise ValidationError("Upload session and attachment must share a tenant.")
        if self.storage_key != self.attachment.storage_key:
            raise ValidationError("Upload session storage binding does not match the controlled attachment.")
        if self.created_by_id <= 0 or not self.created_by_type:
            raise ValidationError("Upload session creator identity is required.")
        if len(self.upload_token_hash) != 64 or any(character not in hexdigits for character in self.upload_token_hash):
            raise ValidationError("Upload token hash must be SHA-256 hexadecimal.")
        if len(self.request_hash) != 64 or any(character not in hexdigits for character in self.request_hash):
            raise ValidationError("Upload request hash must be SHA-256 hexadecimal.")


class ControlledAttachmentEvent(AttachmentDomainModel):
    """Append-only security/domain ledger for every attachment action."""

    class Action(models.TextChoices):
        UPLOAD_SESSION = "upload_session", "Upload session"
        FINISH = "finish", "Finish upload"
        SCAN_START = "scan_start", "Start scan"
        SCAN_RESULT = "scan_result", "Scan result"
        ACCEPT = "accept", "Accept"
        REJECT = "reject", "Reject"
        QUARANTINE = "quarantine", "Quarantine"
        SUPERSEDE = "supersede", "Supersede"
        DELETE = "delete", "Delete"

    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name="controlled_attachment_events")
    attachment = models.ForeignKey(
        ControlledAttachment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="events",
    )
    related_attachment = models.ForeignKey(
        ControlledAttachment,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="related_events",
    )
    action = models.CharField(max_length=32, choices=Action.choices)
    actor_type = models.CharField(max_length=32)
    actor_id = models.PositiveBigIntegerField()
    channel = models.CharField(max_length=32, default="internal")
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    reason = models.TextField(blank=True)
    idempotency_key = models.CharField(max_length=128)
    request_hash = models.CharField(max_length=64)
    occurred_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    objects = AppendOnlyAttachmentQuerySet.as_manager()

    class Meta:
        ordering = ["tenant_id", "created_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "idempotency_key"],
                name="uniq_controlled_attachment_event_key",
            ),
            models.CheckConstraint(
                condition=models.Q(request_hash__regex=r"^[0-9a-fA-F]{64}$"),
                name="controlled_attachment_event_hash_hex",
            ),
        ]
        indexes = [
            models.Index(
                fields=["tenant", "attachment", "action", "created_at"],
                name="idx_ctrl_attach_event",
            ),
        ]

    def clean(self):
        if self.attachment_id and self.attachment.tenant_id != self.tenant_id:
            raise ValidationError("Attachment event and tenant must match.")
        if self.related_attachment_id and self.related_attachment.tenant_id != self.tenant_id:
            raise ValidationError("Related attachment event and tenant must match.")
        if not self.actor_type or self.actor_id <= 0:
            raise ValidationError("Attachment event actor identity is required.")
        if not self.idempotency_key or len(self.idempotency_key) > 128:
            raise ValidationError("Attachment event idempotency key is invalid.")
        if len(self.request_hash or "") != 64 or any(character not in hexdigits for character in self.request_hash):
            raise ValidationError("Attachment event request hash must be SHA-256 hexadecimal.")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Attachment events are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Attachment events are append-only.")


# Domain vocabulary aliases used by later API adapters and tests.  Keeping a
# single append-only ledger prevents action-specific idempotency records from
# drifting apart.
ControlledAttachmentAction = ControlledAttachmentEvent
AttachmentEvent = ControlledAttachmentEvent
