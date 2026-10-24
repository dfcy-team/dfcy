import hashlib
import gzip
import io
import json
import re
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from rest_framework.exceptions import ValidationError

from .models import SyncRawEnvelope

MAX_RAW_PAYLOAD_BYTES = 32 * 1024 * 1024
_STORAGE_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _canonical_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_digest(payload):
    return hashlib.sha256(_canonical_payload(payload).encode()).hexdigest()


def load_raw_payload(envelope):
    """Read an inline or explicitly external RAW payload, failing closed on bad metadata."""
    alias, key = envelope.payload_storage_alias, envelope.payload_object_key
    if alias is None and key is None:
        return envelope.payload
    namespace = getattr(settings, "RAW_PAYLOAD_STORAGE_NAMESPACE", "").strip()
    expected_prefix = f"raw/{namespace}/tenant-{envelope.tenant_id}/" if _STORAGE_NAMESPACE_RE.fullmatch(namespace) else ""
    if (not alias or len(alias) > 80 or not key or len(key) > 500 or envelope.payload != {}
            or not expected_prefix or not key.startswith(expected_prefix)
            or not re.fullmatch(re.escape(expected_prefix) + r"[0-9a-f]{32}\.json\.gz", key)):
        raise ValidationError("RAW payload storage metadata is incomplete or inconsistent.")
    try:
        storage = storages[alias]
        with storage.open(key, "rb") as source:
            compressed = source.read(MAX_RAW_PAYLOAD_BYTES + 1)
        if len(compressed) > MAX_RAW_PAYLOAD_BYTES:
            raise ValueError("compressed RAW payload exceeds size limit")
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as source:
            raw = source.read(MAX_RAW_PAYLOAD_BYTES + 1)
        if len(raw) > MAX_RAW_PAYLOAD_BYTES:
            raise ValueError("decompressed RAW payload exceeds size limit")
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict) or payload_digest(payload) != envelope.payload_hash:
            raise ValueError("RAW payload digest mismatch")
        return payload
    except Exception as exc:
        raise ValidationError("External RAW payload is unavailable or failed integrity validation.") from exc


def _create_raw_envelope(*, payload, **fields):
    alias = getattr(settings, "RAW_PAYLOAD_STORAGE_ALIAS", "")
    fields.pop("payload_hash", None)
    if not alias:
        return SyncRawEnvelope.objects.create(payload=payload, payload_hash=payload_digest(payload), **fields)
    namespace = getattr(settings, "RAW_PAYLOAD_STORAGE_NAMESPACE", "").strip()
    if not _STORAGE_NAMESPACE_RE.fullmatch(namespace):
        raise ValidationError("External RAW storage requires a safe RAW_PAYLOAD_STORAGE_NAMESPACE.")
    if len(alias) > 80:
        raise ValidationError("RAW_PAYLOAD_STORAGE_ALIAS exceeds its database field limit.")
    try:
        storage = storages[alias]
        raw = _canonical_payload(payload).encode("utf-8")
        if len(raw) > MAX_RAW_PAYLOAD_BYTES:
            raise ValueError("RAW payload exceeds size limit")
        digest = hashlib.sha256(raw).hexdigest()
        compressed = gzip.compress(raw, mtime=0)
        tenant_id = fields.get("tenant_id") or fields["tenant"].pk
        key = f"raw/{namespace}/tenant-{tenant_id}/{uuid.uuid4().hex}.json.gz"
        if len(key) > 500:
            raise ValueError("RAW object key exceeds its database field limit")
        saved_key = storage.save(key, ContentFile(compressed))
        # Fail closed if a backend renames the UUID key: the reader validates
        # its exact namespace/tenant/UUID shape before opening an object.
        if saved_key != key:
            raise ValueError("RAW storage unexpectedly renamed the object")
        with storage.open(saved_key, "rb") as source:
            actual = source.read(MAX_RAW_PAYLOAD_BYTES + 1)
        if actual != compressed:
            raise ValueError("RAW object read-back mismatch")
        if len(saved_key) > 500:
            raise ValueError("RAW object key exceeds its database field limit")
    except ValidationError:
        raise
    except Exception as exc:
        raise ValidationError("External RAW payload storage failed; envelope was not created.") from exc
    # Keep database errors intact for the caller's existing transaction retry logic.
    return SyncRawEnvelope.objects.create(
        payload={}, payload_storage_alias=alias, payload_object_key=saved_key,
        payload_hash=digest, **fields,
    )


def archive_raw_page(sync_job, sync_run, adapter, cursor, page):
    responses = page.get("raw_responses")
    if not isinstance(responses, list) or not responses:
        responses = [{"endpoint": f"adapter://{adapter.adapter_name}", "payload": page}]
    envelope_payload = {
        "responses": responses,
        "records": page.get("records", []),
        "next_cursor": page.get("next_cursor", ""),
    }
    endpoints = sorted(
        {str(item.get("endpoint") or "") for item in responses if isinstance(item, dict)}
    )
    authorization = getattr(adapter, "authorization", None)
    sequence = sync_run.raw_envelopes.count() + 1
    return _create_raw_envelope(
        tenant=sync_job.tenant,
        sync_run=sync_run,
        store_id=(sync_job.ads_mapping.store_id if sync_job.ads_mapping_id else getattr(authorization, "store_id", None)),
        platform=sync_job.integration_config.platform,
        endpoint=",".join(endpoints)[:255],
        cursor=str(cursor or ""),
        sequence=sequence,
        payload=envelope_payload,
    )


def archive_webhook_payload(webhook_event, payload):
    envelope_payload = {
        "event_id": webhook_event.event_id,
        "event_type": webhook_event.event_type,
        "payload": payload,
    }
    return _create_raw_envelope(
        tenant=webhook_event.tenant,
        webhook_event=webhook_event,
        platform=webhook_event.platform,
        endpoint=f"webhook://{webhook_event.event_type}"[:255],
        sequence=1,
        payload=envelope_payload,
    )


def replay_raw_envelope(envelope, adapter):
    if envelope.sync_run_id and envelope.sync_run.sync_job.ads_mapping_id:
        raise ValidationError("Ads spend requires complete-window fenced execution; RAW replay is disabled.")
    if envelope.sync_run_id and envelope.sync_run.sync_job.resource_type == "affiliate_order":
        raise ValidationError("Affiliate envelopes require complete-day ingestion; individual RAW replay is disabled.")
    payload = load_raw_payload(envelope)
    if payload_digest(payload) != envelope.payload_hash:
        raise ValidationError("RAW response envelope integrity check failed.")
    if envelope.sync_run_id is None:
        raise ValidationError("Webhook RAW envelopes require a webhook-specific replay handler.")
    adapter.validate_configuration(envelope.sync_run.sync_job)
    adapter.bind_run(envelope.sync_run)
    summary = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    for raw_record in payload.get("records", []):
        normalized = adapter.normalize_record(raw_record)
        if not adapter.validate_record(normalized):
            summary["failed"] += 1
            continue
        result = adapter.persist_record(envelope.sync_run.sync_job, normalized)
        action = result.get("action", "skipped")
        summary[action if action in summary else "skipped"] += 1
    return summary
