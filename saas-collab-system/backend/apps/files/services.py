"""Controlled private attachment domain services.

This module intentionally exposes no HTTP/upload endpoint.  The storage and
scanner interfaces are dependency-injected and the default implementations
are in-memory only, so local tests cannot accidentally connect to production
object storage or a scanning vendor.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import secrets
import threading
import unicodedata
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Protocol

from django.core.exceptions import ValidationError as DjangoValidationError
from django.conf import settings
from django.db import IntegrityError, OperationalError, transaction
from django.utils import timezone
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import CustomUser
from apps.common.exceptions import (
    BusinessRuleViolation,
    IdempotencyConflict,
    ScopedResourceNotFound,
    StateConflict,
)

from .models import (
    AttachmentUploadSession,
    ControlledAttachment,
    ControlledAttachmentEvent,
    _attachment_domain_write_context,
)


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
MIN_ATTACHMENT_BYTES = 1
MAX_HANDOVER_ATTACHMENTS = 9
MAX_IMAGE_PIXELS = 40_000_000
ALLOWED_MEDIA_TYPES = frozenset({"image/jpeg", "image/png"})


class AttachmentStorageAdapter(Protocol):
    def put(self, storage_key: str, content: bytes) -> dict[str, Any]: ...

    def read(self, storage_key: str) -> bytes: ...

    def head(self, storage_key: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class AttachmentScanResult:
    passed: bool
    quarantined: bool = False
    engine: str = "local-fake"
    version: str = "1"
    rejection_code: str = ""


class AttachmentScannerAdapter(Protocol):
    def scan(self, *, content: bytes, media_type: str, sha256: str) -> AttachmentScanResult: ...


# Short vocabulary aliases keep future adapters/tests decoupled from the
# concrete implementation names while retaining protocol-only boundaries.
StorageAdapter = AttachmentStorageAdapter
ScannerAdapter = AttachmentScannerAdapter


class InMemoryAttachmentStorage:
    """Thread-safe fake storage used by local services and gate tests."""

    def __init__(self):
        self._objects: dict[str, bytes] = {}
        self._lock = threading.RLock()

    def put(self, storage_key: str, content: bytes) -> dict[str, Any]:
        _validate_storage_key(storage_key)
        data = bytes(content)
        with self._lock:
            self._objects[storage_key] = data
        return {"byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    upload = put

    def read(self, storage_key: str) -> bytes:
        with self._lock:
            if storage_key not in self._objects:
                raise KeyError(storage_key)
            return self._objects[storage_key]

    get = read

    def head(self, storage_key: str) -> dict[str, Any]:
        data = self.read(storage_key)
        return {"byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest()}

    def delete(self, storage_key: str) -> None:
        with self._lock:
            self._objects.pop(storage_key, None)


class InMemoryAttachmentScanner:
    def __init__(self, *, result: AttachmentScanResult | None = None):
        self.result = result

    def scan(self, *, content: bytes, media_type: str, sha256: str) -> AttachmentScanResult:
        if self.result is not None:
            return self.result
        return AttachmentScanResult(passed=True, engine="local-fake", version="1")


class UnavailableAttachmentScanner:
    """Fail-closed default used when a caller did not inject a scanner."""

    def scan(self, *, content: bytes, media_type: str, sha256: str) -> AttachmentScanResult:
        raise RuntimeError("No attachment scanner adapter has been configured.")


# Explicit aliases make adapter injection discoverable without implying a
# production implementation.
FakeAttachmentStorage = InMemoryAttachmentStorage
MemoryAttachmentStorage = InMemoryAttachmentStorage
FakeAttachmentScanner = InMemoryAttachmentScanner
MemoryAttachmentScanner = InMemoryAttachmentScanner
_DEFAULT_STORAGE = InMemoryAttachmentStorage()
_DEFAULT_SCANNER = UnavailableAttachmentScanner()


def _database_error_code(exc):
    for candidate in (getattr(exc, "__cause__", None), exc):
        args = getattr(candidate, "args", ())
        if args and isinstance(args[0], int):
            return args[0]
    return None


def _attachment_domain_action(func):
    def wrapped(*args, **kwargs):
        try:
            with _attachment_domain_write_context():
                return func(*args, **kwargs)
        except OperationalError as exc:
            if _database_error_code(exc) in {1205, 1213}:
                raise StateConflict(
                    "Attachment transaction hit a retryable database conflict; retry with the same idempotency key."
                ) from exc
            raise

    wrapped.__name__ = getattr(func, "__name__", "attachment_domain_action")
    wrapped.__doc__ = getattr(func, "__doc__", None)
    return wrapped


def _canonical_hash(payload):
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _validate_idempotency_key(value):
    if not isinstance(value, str) or not value or len(value) > 128:
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key is required."})
    if any(ord(character) < 0x21 or ord(character) > 0x7E for character in value):
        raise ValidationError({"idempotency_key": "Idempotency-Key must contain printable ASCII only."})


def _validate_actor(actor):
    if not actor or not getattr(actor, "is_authenticated", False) or not actor.is_active:
        raise PermissionDenied("An active authenticated actor is required.")
    if not actor.tenant_id:
        raise PermissionDenied("A tenant-bound actor is required.")
    return actor


def _actor_identity(actor):
    _validate_actor(actor)
    return str(actor.user_type), int(actor.id)


def _is_unique_validation_error(exc):
    if not isinstance(exc, DjangoValidationError):
        return False
    errors = list(getattr(exc, "error_list", ()) or ())
    for field_errors in (getattr(exc, "error_dict", {}) or {}).values():
        errors.extend(field_errors)
    for error in errors:
        if getattr(error, "code", None) in {"unique", "unique_together"}:
            return True
        if "already exists" in str(getattr(error, "message", error) or "").lower():
            return True
    return False


def _validate_storage_key(storage_key):
    if not isinstance(storage_key, str) or not storage_key or len(storage_key) > 255:
        raise ValidationError({"storage_key": "A generated storage key is required."})
    if "\x00" in storage_key or "://" in storage_key or storage_key.lower().startswith(("http:", "https:", "file:")):
        raise ValidationError({"storage_key": "Arbitrary URLs are not accepted as storage keys."})


def normalize_attachment_filename(file_name: str | None) -> tuple[str, str]:
    """Return a safe display name and a lowercase extension."""

    value = unicodedata.normalize("NFKC", str(file_name or "attachment"))
    value = value.replace("\\", "/").rsplit("/", 1)[-1]
    value = "".join(character for character in value if ord(character) >= 32 and character not in {"\x7f", "\x00"})
    value = value.strip(" .")[:255] or "attachment"
    extension = value.rsplit(".", 1)[-1].lower() if "." in value else ""
    if extension not in {"jpg", "jpeg", "png"}:
        extension = ""
    return value, extension


def validate_image_content(content: bytes, *, claimed_media_type: str | None = None) -> dict[str, Any]:
    """Validate magic, decoder support, media type, byte and pixel limits."""

    data = bytes(content)
    byte_size = len(data)
    if byte_size < MIN_ATTACHMENT_BYTES:
        raise BusinessRuleViolation("Attachment content cannot be empty.")
    if byte_size > MAX_ATTACHMENT_BYTES:
        raise BusinessRuleViolation("Attachment exceeds the 10 MiB local evidence limit.")
    if data.startswith(b"\xff\xd8\xff"):
        media_type, extension = "image/jpeg", "jpg"
    elif data.startswith(b"\x89PNG\r\n\x1a\n"):
        media_type, extension = "image/png", "png"
    else:
        raise BusinessRuleViolation("Only JPEG and PNG magic bytes are accepted.")
    if claimed_media_type and claimed_media_type.lower() != media_type:
        raise BusinessRuleViolation("Declared MIME does not match server-detected image content.")
    try:
        with Image.open(io.BytesIO(data)) as image:
            width, height = image.size
            if width <= 0 or height <= 0 or width * height > MAX_IMAGE_PIXELS:
                raise BusinessRuleViolation("Image pixel dimensions exceed the safety limit.")
            image.verify()
        # ``verify`` invalidates the decoder; reopen to ensure the actual
        # image can be decoded rather than merely having a plausible header.
        with Image.open(io.BytesIO(data)) as image:
            image.load()
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise BusinessRuleViolation("Image content cannot be decoded safely.") from exc
    return {
        "media_type": media_type,
        "extension": extension,
        "byte_size": byte_size,
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": width,
        "height": height,
    }


def _release_version_for_allocation(allocation):
    from apps.consolidation.models import ConsolidationEvent

    if allocation.consolidation.status not in {
        allocation.consolidation.Status.RELEASED,
        allocation.consolidation.Status.RECEIVING,
        allocation.consolidation.Status.READY_FOR_SHIPMENT,
    }:
        raise StateConflict("Evidence upload requires a released consolidation arrangement.")
    event = ConsolidationEvent.objects.filter(
        tenant=allocation.tenant,
        consolidation_id=allocation.consolidation_id,
        action=ConsolidationEvent.Action.RELEASE,
    ).order_by("-source_version", "-created_at", "-id").first()
    if event is None or not event.source_version:
        raise StateConflict("The consolidation has no verifiable release version for evidence binding.")
    return int(event.source_version)


def _locked_allocation(actor, allocation_id, *, require_upload_state=True):
    from apps.consolidation.models import ConsolidationBoxAllocation

    query = ConsolidationBoxAllocation.objects.select_for_update().select_related("consolidation", "box").filter(
        pk=allocation_id,
        tenant=actor.tenant,
    )
    allocation = query.first()
    if allocation is None:
        raise ScopedResourceNotFound("Consolidation allocation is not available in this tenant.")
    if require_upload_state and allocation.state not in {
        ConsolidationBoxAllocation.State.ALLOCATED,
        ConsolidationBoxAllocation.State.HANDOVER_SUBMITTED,
    }:
        raise StateConflict("This allocation is not accepting new handover evidence.")
    if getattr(actor, "user_type", None) == CustomUser.UserType.EXTERNAL:
        profile = getattr(actor, "external_profile", None)
        if profile is None or profile.supplier_id != allocation.supplier_id_snapshot:
            # Do not reveal whether another supplier's attachment exists.
            raise ScopedResourceNotFound("Consolidation allocation is not available to this supplier.")
        from apps.consolidation.services import _require_handover_capability
        _require_handover_capability(actor, allocation.supplier_id_snapshot)
    release_version = _release_version_for_allocation(allocation)
    return allocation, release_version


def _derived_upload_token(session):
    """Derive a short-lived upload token without persisting plaintext."""
    expiry = int(session.expires_at.timestamp())
    message = f"attach-upload:v1:{session.tenant_id}:{session.id}:{session.storage_key}:{expiry}".encode("utf-8")
    secret = str(getattr(settings, "SECRET_KEY", "") or "local-development-secret").encode("utf-8")
    signature = hmac.new(secret, message, hashlib.sha256).hexdigest()
    return f"v1.{session.id}.{expiry}.{signature}"


def _attach_upload_token(attachment):
    session = getattr(attachment, "upload_session", None)
    if session is None:
        session = AttachmentUploadSession.objects.filter(attachment=attachment).order_by("-created_at", "-id").first()
    if session is not None:
        session.upload_token = _derived_upload_token(session)
        # Keep the same transient relation shape for first responses and
        # idempotent replays; this is not a persisted plaintext token.
        attachment.upload_session = session
    return session


def _attachment_snapshot(attachment):
    return {
        "id": int(attachment.id),
        "attachment_no": attachment.attachment_no,
        "owner_type": attachment.owner_type,
        "owner_id": int(attachment.owner_id),
        "business_type": attachment.business_type,
        "business_id": str(attachment.business_id),
        "business_version": int(attachment.business_version),
        "file_name": attachment.file_name,
        "extension": attachment.extension,
        "media_type": attachment.media_type,
        "byte_size": int(attachment.byte_size or 0),
        "sha256": attachment.sha256,
        "state": attachment.state,
        "scan_status": attachment.scan_status,
        "scan_engine": attachment.scan_engine,
        "scan_engine_version": attachment.scan_engine_version,
        "rejection_code": attachment.rejection_code,
        "accepted_at": attachment.accepted_at.isoformat() if attachment.accepted_at else None,
        "superseded_by_id": attachment.superseded_by_id,
    }


def _event_replay(*, tenant, key, action, request_hash, actor, attachment_id=None):
    event = ControlledAttachmentEvent.objects.select_for_update().filter(
        tenant=tenant,
        idempotency_key=key,
    ).first()
    if event is None:
        return None
    if event.action != action or event.actor_id != actor.id or event.actor_type != str(actor.user_type):
        raise IdempotencyConflict("The attachment idempotency key belongs to another action or actor.")
    if event.request_hash != request_hash:
        raise IdempotencyConflict("The attachment idempotency key was reused with another payload.")
    if attachment_id is not None and event.attachment_id not in {None, attachment_id}:
        raise IdempotencyConflict("The attachment idempotency key belongs to another resource.")
    return event


def _event(*, tenant, action, actor, key, request_hash, before=None, after=None, reason="", attachment=None,
           related_attachment=None, channel="internal"):
    actor_type, actor_id = _actor_identity(actor)
    event = ControlledAttachmentEvent(
        tenant=tenant,
        attachment=attachment,
        related_attachment=related_attachment,
        action=action,
        actor_type=actor_type,
        actor_id=actor_id,
        channel=channel,
        before=before or {},
        after=after or {},
        reason=str(reason or ""),
        idempotency_key=key,
        request_hash=request_hash,
        occurred_at=timezone.now(),
    )
    try:
        with transaction.atomic():
            event.save()
    except (IntegrityError, DjangoValidationError) as exc:
        if isinstance(exc, DjangoValidationError) and not _is_unique_validation_error(exc):
            raise
        existing = ControlledAttachmentEvent.objects.select_for_update().filter(
            tenant=tenant,
            idempotency_key=key,
        ).first()
        if existing is None:
            raise
        if (
            existing.action != action
            or existing.actor_id != actor_id
            or existing.actor_type != actor_type
            or existing.request_hash != request_hash
        ):
            raise IdempotencyConflict("The attachment idempotency key was reused with another payload.")
        return existing, True
    return event, False


def _generated_storage_key(tenant_id):
    return f"private/tenant-{int(tenant_id)}/consolidation/{uuid.uuid4().hex}"


def _generated_attachment_no(tenant_id, key):
    return f"ATT-{hashlib.sha256(f'{tenant_id}:{key}'.encode('utf-8')).hexdigest()[:28].upper()}"


def _attachment_for_event(event):
    if event.attachment_id is None:
        raise StateConflict("Attachment event has no controlled attachment reference.")
    return ControlledAttachment.objects.get(pk=event.attachment_id)


@_attachment_domain_action
def create_attachment_upload_session(*, actor, allocation_id, idempotency_key, channel="internal",
                                     expires_in_seconds=900, storage=None):
    """Create one owner/binding-derived upload session and empty asset row."""

    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    if isinstance(expires_in_seconds, bool) or int(expires_in_seconds) <= 0 or int(expires_in_seconds) > 3600:
        raise ValidationError({"expires_in_seconds": "Upload session expiry must be between 1 and 3600 seconds."})
    storage = storage or _DEFAULT_STORAGE
    with transaction.atomic():
        allocation, release_version = _locked_allocation(actor, allocation_id)
        payload = {
            "allocation_id": int(allocation.id),
            "tenant_id": int(actor.tenant_id),
            "owner_type": "supplier",
            "owner_id": int(allocation.supplier_id_snapshot),
            "business_version": release_version,
            "channel": str(channel or "internal"),
            "expires_in_seconds": int(expires_in_seconds),
        }
        request_hash = _canonical_hash(payload)
        replay = _event_replay(
            tenant=actor.tenant,
            key=idempotency_key,
            action=ControlledAttachmentEvent.Action.UPLOAD_SESSION,
            request_hash=request_hash,
            actor=actor,
        )
        if replay:
            attachment = _attachment_for_event(replay)
            session = _attach_upload_token(attachment)
            if session is not None and session.expires_at <= timezone.now():
                raise StateConflict("The original upload session has expired; create a new idempotency key.")
            return attachment, replay, True
        existing_upload = ControlledAttachment.objects.select_for_update().filter(
            tenant=actor.tenant,
            upload_idempotency_key=idempotency_key,
        ).first()
        if existing_upload is not None:
            raise IdempotencyConflict("The upload idempotency key was reused with another payload.")
        active_count = ControlledAttachment.objects.filter(
            tenant=actor.tenant,
            business_type="consolidation_handover",
            business_id=str(allocation.id),
            business_version=release_version,
        ).exclude(state__in=[ControlledAttachment.State.SUPERSEDED, ControlledAttachment.State.DELETED]).count()
        if active_count >= MAX_HANDOVER_ATTACHMENTS:
            raise BusinessRuleViolation("A handover can contain at most nine active evidence images.")
        actor_type, actor_id = _actor_identity(actor)
        attachment = ControlledAttachment(
            tenant=actor.tenant,
            attachment_no=_generated_attachment_no(actor.tenant_id, idempotency_key),
            owner_type="supplier",
            owner_id=int(allocation.supplier_id_snapshot),
            business_type="consolidation_handover",
            business_id=str(allocation.id),
            business_version=release_version,
            storage_key=_generated_storage_key(actor.tenant_id),
            state=ControlledAttachment.State.UPLOADING,
            scan_status=ControlledAttachment.ScanStatus.PENDING,
            created_by_type=actor_type,
            created_by_id=actor_id,
            channel=str(channel or "internal"),
            upload_idempotency_key=idempotency_key,
        )
        try:
            with transaction.atomic():
                attachment.save()
        except (IntegrityError, DjangoValidationError) as exc:
            if isinstance(exc, DjangoValidationError) and not _is_unique_validation_error(exc):
                raise
            replay = _event_replay(
                tenant=actor.tenant,
                key=idempotency_key,
                action=ControlledAttachmentEvent.Action.UPLOAD_SESSION,
                request_hash=request_hash,
                actor=actor,
            )
            if replay:
                attachment = _attachment_for_event(replay)
                session = _attach_upload_token(attachment)
                if session is not None and session.expires_at <= timezone.now():
                    raise StateConflict("The original upload session has expired; create a new idempotency key.")
                return attachment, replay, True
            raise IdempotencyConflict("The upload idempotency key is already in use.") from exc
        session = AttachmentUploadSession(
            tenant=actor.tenant,
            attachment=attachment,
            # Save once to obtain a stable session ID.  The placeholder is
            # replaced by the HMAC-derived token hash in the same transaction.
            upload_token_hash="0" * 64,
            storage_key=attachment.storage_key,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            expires_at=timezone.now() + timedelta(seconds=int(expires_in_seconds)),
            created_by_type=actor_type,
            created_by_id=actor_id,
        )
        session.save()
        token = _derived_upload_token(session)
        session.upload_token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        session.save(update_fields=["upload_token_hash"])
        # The plaintext token is intentionally transient; it is never stored.
        session.upload_token = token
        attachment.upload_session = session
        event, replayed = _event(
            tenant=actor.tenant,
            action=ControlledAttachmentEvent.Action.UPLOAD_SESSION,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            after=_attachment_snapshot(attachment),
            attachment=attachment,
            channel=channel,
        )
        return attachment, event, replayed


def _resolve_attachment(actor, attachment_id=None, upload_session_id=None):
    if attachment_id is None and upload_session_id is None:
        raise ValidationError({"attachment_id": "attachment_id or upload_session_id is required."})
    if upload_session_id is not None:
        session = AttachmentUploadSession.objects.select_for_update().select_related("attachment").filter(
            pk=upload_session_id,
            tenant=actor.tenant,
        ).first()
        if session is None:
            raise ScopedResourceNotFound("Upload session is not available in this tenant.")
        attachment_id = session.attachment_id
    attachment = ControlledAttachment.objects.select_for_update().filter(
        pk=attachment_id,
        tenant=actor.tenant,
    ).first()
    if attachment is None:
        raise ScopedResourceNotFound("Controlled attachment is not available in this tenant.")
    return attachment


@_attachment_domain_action
def finalize_attachment(*, actor, idempotency_key, attachment_id=None, upload_session_id=None,
                        file_name=None, claimed_media_type=None, claimed_sha256=None,
                        content=None, upload_token=None, storage=None):
    """Read actual bytes from the injected storage and freeze finish metadata."""

    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    storage = storage or _DEFAULT_STORAGE
    with transaction.atomic():
        attachment = _resolve_attachment(actor, attachment_id, upload_session_id)
        allocation, release_version = _locked_allocation(actor, int(attachment.business_id))
        if attachment.business_version != release_version:
            raise StateConflict("The attachment release version is stale.")
        session = AttachmentUploadSession.objects.select_for_update().filter(
            tenant=actor.tenant,
            attachment=attachment,
        ).order_by("-created_at", "-id").first()
        if session is None:
            raise ScopedResourceNotFound("Upload session is not available for this attachment.")
        if upload_token is not None:
            token_hash = hashlib.sha256(str(upload_token).encode("utf-8")).hexdigest()
            if token_hash != session.upload_token_hash:
                raise PermissionDenied("The upload token is invalid.")
        if session.expires_at <= timezone.now() and session.state == AttachmentUploadSession.State.ACTIVE:
            session.state = AttachmentUploadSession.State.EXPIRED
            session.save(update_fields=["state"])
            raise StateConflict("The upload session has expired.")
        if content is not None:
            storage.put(attachment.storage_key, bytes(content))
        try:
            actual_content = storage.read(attachment.storage_key)
        except (KeyError, FileNotFoundError) as exc:
            raise BusinessRuleViolation("Uploaded object is not available in the isolated storage adapter.") from exc
        metadata_payload = {
            "attachment_id": int(attachment.id),
            "byte_size": len(actual_content),
            "sha256": hashlib.sha256(actual_content).hexdigest(),
            "file_name": str(file_name or ""),
            "claimed_media_type": str(claimed_media_type or ""),
            "claimed_sha256": str(claimed_sha256 or ""),
        }
        request_hash = _canonical_hash(metadata_payload)
        replay = _event_replay(
            tenant=actor.tenant,
            key=idempotency_key,
            action=ControlledAttachmentEvent.Action.FINISH,
            request_hash=request_hash,
            actor=actor,
            attachment_id=attachment.id,
        )
        if replay:
            return _attachment_for_event(replay), replay, True
        if attachment.state != ControlledAttachment.State.UPLOADING:
            raise StateConflict("Only an uploading attachment can be finalized; reuse its original key to replay.")
        safe_name, _ = normalize_attachment_filename(file_name)
        try:
            detected = validate_image_content(actual_content, claimed_media_type=claimed_media_type)
            if claimed_sha256 and str(claimed_sha256).lower() != detected["sha256"]:
                raise BusinessRuleViolation("Client SHA-256 does not match the server-computed digest.")
        except BusinessRuleViolation as exc:
            attachment.file_name = safe_name
            attachment.byte_size = len(actual_content)
            attachment.sha256 = hashlib.sha256(actual_content).hexdigest()
            attachment.state = ControlledAttachment.State.REJECTED
            attachment.scan_status = ControlledAttachment.ScanStatus.FAILED
            attachment.rejection_code = "content_validation_failed"
            attachment.save(update_fields=["file_name", "byte_size", "sha256", "state", "scan_status", "rejection_code", "updated_at"])
            session.state = AttachmentUploadSession.State.FINISHED
            session.finished_at = timezone.now()
            session.save(update_fields=["state", "finished_at"])
            event, replayed = _event(
                tenant=actor.tenant,
                action=ControlledAttachmentEvent.Action.FINISH,
                actor=actor,
                key=idempotency_key,
                request_hash=request_hash,
                before=_attachment_snapshot(attachment),
                after=_attachment_snapshot(attachment),
                reason=str(exc.detail if hasattr(exc, "detail") else exc),
                attachment=attachment,
                channel=attachment.channel,
            )
            return attachment, event, replayed
        attachment.file_name = safe_name
        attachment.extension = detected["extension"]
        attachment.media_type = detected["media_type"]
        attachment.byte_size = detected["byte_size"]
        attachment.sha256 = detected["sha256"]
        attachment.state = ControlledAttachment.State.UPLOADED
        attachment.scan_status = ControlledAttachment.ScanStatus.PENDING
        attachment.rejection_code = ""
        attachment.save(update_fields=["file_name", "extension", "media_type", "byte_size", "sha256", "state", "scan_status", "rejection_code", "updated_at"])
        session.state = AttachmentUploadSession.State.FINISHED
        session.finished_at = timezone.now()
        session.save(update_fields=["state", "finished_at"])
        event, replayed = _event(
            tenant=actor.tenant,
            action=ControlledAttachmentEvent.Action.FINISH,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            after=_attachment_snapshot(attachment),
            attachment=attachment,
            channel=attachment.channel,
        )
        return attachment, event, replayed


def finish_attachment_upload(**kwargs):
    return finalize_attachment(**kwargs)


@_attachment_domain_action
def start_attachment_scan(*, actor, attachment_id, idempotency_key, reason="", channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({"attachment_id": attachment_id, "reason": reason})
    with transaction.atomic():
        attachment = _resolve_attachment(actor, attachment_id=attachment_id)
        replay = _event_replay(
            tenant=actor.tenant,
            key=idempotency_key,
            action=ControlledAttachmentEvent.Action.SCAN_START,
            request_hash=request_hash,
            actor=actor,
            attachment_id=attachment.id,
        )
        if replay:
            return _attachment_for_event(replay), replay, True
        if attachment.state != ControlledAttachment.State.UPLOADED:
            raise StateConflict("Only a finished upload can enter scanning.")
        before = _attachment_snapshot(attachment)
        attachment.state = ControlledAttachment.State.SCANNING
        attachment.scan_status = ControlledAttachment.ScanStatus.SCANNING
        attachment.save(update_fields=["state", "scan_status", "updated_at"])
        event, replayed = _event(
            tenant=actor.tenant,
            action=ControlledAttachmentEvent.Action.SCAN_START,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            before=before,
            after=_attachment_snapshot(attachment),
            reason=reason,
            attachment=attachment,
            channel=channel,
        )
        return attachment, event, replayed


@_attachment_domain_action
def record_attachment_scan_result(*, actor, attachment_id, idempotency_key, passed=None,
                                  quarantined=None, rejection_code=None, scan_engine=None,
                                  scan_engine_version=None, scanner=None, storage=None, reason="",
                                  channel="internal"):
    """Apply the result returned by an injected scanner, fail closed.

    The outcome fields are retained as deprecated keyword arguments solely to
    produce a deterministic validation error for old callers.  A caller may
    not declare ``passed``/``quarantined``/engine metadata; only the scanner
    adapter result can select the ACCEPT/REJECT/QUARANTINE transition.
    """

    if any(value is not None for value in (passed, quarantined, rejection_code, scan_engine, scan_engine_version)):
        raise ValidationError("Scan outcome and engine metadata must come from the injected scanner adapter.")
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    storage = storage or _DEFAULT_STORAGE
    scanner = scanner or _DEFAULT_SCANNER
    request_hash = _canonical_hash({
        "attachment_id": int(attachment_id),
        "reason": reason,
        "channel": str(channel or "internal"),
    })
    with transaction.atomic():
        attachment = _resolve_attachment(actor, attachment_id=attachment_id)
        # Scan result can vary between scanner attempts, so idempotency is
        # keyed to the caller's action/resource payload, not the result.  A
        # retry therefore replays the original event before calling scanner a
        # second time.
        existing = ControlledAttachmentEvent.objects.select_for_update().filter(
            tenant=actor.tenant,
            idempotency_key=idempotency_key,
        ).first()
        if existing is not None:
            if (
                existing.action not in {
                    ControlledAttachmentEvent.Action.ACCEPT,
                    ControlledAttachmentEvent.Action.REJECT,
                    ControlledAttachmentEvent.Action.QUARANTINE,
                }
                or existing.actor_id != actor.id
                or existing.actor_type != str(actor.user_type)
                or existing.attachment_id != attachment.id
            ):
                raise IdempotencyConflict("The attachment idempotency key belongs to another action or actor.")
            if existing.request_hash != request_hash:
                raise IdempotencyConflict("The attachment idempotency key was reused with another payload.")
            return _attachment_for_event(existing), existing, True
        if attachment.state not in {ControlledAttachment.State.UPLOADED, ControlledAttachment.State.SCANNING}:
            raise StateConflict("Only an uploaded/scanning attachment can receive a scan result.")
        try:
            content = storage.read(attachment.storage_key)
            result = scanner.scan(content=content, media_type=attachment.media_type, sha256=attachment.sha256)
            if not isinstance(result, AttachmentScanResult):
                raise TypeError("Scanner adapter returned an invalid result object.")
        except Exception:
            # Missing storage, scanner timeout/error and malformed adapter
            # output all remain quarantined; none can become accepted.
            result = AttachmentScanResult(
                passed=False,
                quarantined=True,
                engine="fail-closed",
                version="1",
                rejection_code="scanner_unavailable",
            )
        passed_result = bool(result.passed)
        quarantined_result = bool(result.quarantined)
        result_engine = str(result.engine or "")[:80]
        result_version = str(result.version or "")[:40]
        result_rejection = str(result.rejection_code or "")[:80]
        target_action = (
            ControlledAttachmentEvent.Action.QUARANTINE
            if quarantined_result
            else ControlledAttachmentEvent.Action.ACCEPT
            if passed_result
            else ControlledAttachmentEvent.Action.REJECT
        )
        before = _attachment_snapshot(attachment)
        if attachment.state == ControlledAttachment.State.UPLOADED:
            attachment.state = ControlledAttachment.State.SCANNING
        attachment.scan_status = (
            ControlledAttachment.ScanStatus.QUARANTINED
            if quarantined_result
            else ControlledAttachment.ScanStatus.PASSED
            if passed_result
            else ControlledAttachment.ScanStatus.FAILED
        )
        attachment.scan_engine = result_engine
        attachment.scan_engine_version = result_version
        attachment.scanned_at = timezone.now()
        attachment.rejection_code = "" if passed_result and not quarantined_result else result_rejection or "scan_failed"
        if quarantined_result:
            attachment.state = ControlledAttachment.State.QUARANTINED
            attachment.accepted_at = None
        elif passed_result:
            attachment.state = ControlledAttachment.State.ACCEPTED
            attachment.accepted_at = timezone.now()
        else:
            attachment.state = ControlledAttachment.State.REJECTED
            attachment.accepted_at = None
        attachment.save(update_fields=["state", "scan_status", "scan_engine", "scan_engine_version", "scanned_at", "rejection_code", "accepted_at", "updated_at"])
        event, replayed = _event(
            tenant=actor.tenant,
            action=target_action,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            before=before,
            after=_attachment_snapshot(attachment),
            reason=reason,
            attachment=attachment,
            channel=channel,
        )
        return attachment, event, replayed


def scan_attachment(**kwargs):
    return record_attachment_scan_result(**kwargs)


def apply_attachment_scan_result(**kwargs):
    return record_attachment_scan_result(**kwargs)


def accept_attachment(*, actor, attachment_id, idempotency_key, scanner=None, storage=None,
                      reason="", channel="internal"):
    return record_attachment_scan_result(
        actor=actor,
        attachment_id=attachment_id,
        idempotency_key=idempotency_key,
        scanner=scanner,
        storage=storage,
        reason=reason,
        channel=channel,
    )


def reject_attachment(*, actor, attachment_id, idempotency_key, scanner=None, storage=None,
                      reason="", channel="internal"):
    return record_attachment_scan_result(
        actor=actor,
        attachment_id=attachment_id,
        idempotency_key=idempotency_key,
        scanner=scanner,
        storage=storage,
        reason=reason,
        channel=channel,
    )


def quarantine_attachment(*, actor, attachment_id, idempotency_key, scanner=None, storage=None,
                          reason="", channel="internal"):
    return record_attachment_scan_result(
        actor=actor,
        attachment_id=attachment_id,
        idempotency_key=idempotency_key,
        scanner=scanner,
        storage=storage,
        reason=reason,
        channel=channel,
    )


@_attachment_domain_action
def supersede_attachment(*, actor, attachment_id, replacement_attachment_id, idempotency_key,
                         reason="", channel="internal"):
    _validate_actor(actor)
    _validate_idempotency_key(idempotency_key)
    request_hash = _canonical_hash({
        "attachment_id": attachment_id,
        "replacement_attachment_id": replacement_attachment_id,
        "reason": reason,
    })
    with transaction.atomic():
        ids = sorted({int(attachment_id), int(replacement_attachment_id)})
        rows = list(ControlledAttachment.objects.select_for_update().filter(
            tenant=actor.tenant,
            pk__in=ids,
        ).order_by("pk"))
        if len(rows) != 2:
            raise ScopedResourceNotFound("Replacement attachment is not available in this tenant.")
        old = next(row for row in rows if row.id == int(attachment_id))
        replacement = next(row for row in rows if row.id == int(replacement_attachment_id))
        replay = _event_replay(
            tenant=actor.tenant,
            key=idempotency_key,
            action=ControlledAttachmentEvent.Action.SUPERSEDE,
            request_hash=request_hash,
            actor=actor,
            attachment_id=old.id,
        )
        if replay:
            return _attachment_for_event(replay), replay, True
        if old.state != ControlledAttachment.State.ACCEPTED:
            raise StateConflict("Only accepted evidence can be superseded.")
        if replacement.state != ControlledAttachment.State.ACCEPTED:
            raise StateConflict("A replacement must be accepted before superseding history.")
        binding_fields = ("owner_type", "owner_id", "business_type", "business_id", "business_version")
        if any(getattr(old, field) != getattr(replacement, field) for field in binding_fields):
            raise BusinessRuleViolation("Replacement evidence must keep the same tenant owner and release binding.")
        before = _attachment_snapshot(old)
        old.state = ControlledAttachment.State.SUPERSEDED
        old.superseded_by = replacement
        # The model compares against the database's accepted state and only
        # permits this one audited terminal transition explicitly.
        old._allow_attachment_state_transition = True
        try:
            old.save(update_fields=["state", "superseded_by", "updated_at"])
        finally:
            old._allow_attachment_state_transition = False
        after = _attachment_snapshot(old)
        after["replacement"] = _attachment_snapshot(replacement)
        event, replayed = _event(
            tenant=actor.tenant,
            action=ControlledAttachmentEvent.Action.SUPERSEDE,
            actor=actor,
            key=idempotency_key,
            request_hash=request_hash,
            before=before,
            after=after,
            reason=reason,
            attachment=old,
            related_attachment=replacement,
            channel=channel,
        )
        return old, event, replayed


# Domain vocabulary aliases for future API adapters.
create_upload_session = create_attachment_upload_session
start_upload_session = create_attachment_upload_session
finalize_upload = finalize_attachment
finish_upload = finalize_attachment
start_scan = start_attachment_scan
record_scan_result = record_attachment_scan_result
supersede = supersede_attachment
