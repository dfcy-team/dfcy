import hashlib
import json

from rest_framework.exceptions import ValidationError

from .models import SyncRawEnvelope


def _canonical_payload(payload):
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def payload_digest(payload):
    return hashlib.sha256(_canonical_payload(payload).encode()).hexdigest()


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
    return SyncRawEnvelope.objects.create(
        tenant=sync_job.tenant,
        sync_run=sync_run,
        store_id=getattr(authorization, "store_id", None),
        platform=sync_job.integration_config.platform,
        endpoint=",".join(endpoints)[:255],
        cursor=str(cursor or ""),
        sequence=sequence,
        payload=envelope_payload,
        payload_hash=payload_digest(envelope_payload),
    )


def archive_webhook_payload(webhook_event, payload):
    envelope_payload = {
        "event_id": webhook_event.event_id,
        "event_type": webhook_event.event_type,
        "payload": payload,
    }
    return SyncRawEnvelope.objects.create(
        tenant=webhook_event.tenant,
        webhook_event=webhook_event,
        platform=webhook_event.platform,
        endpoint=f"webhook://{webhook_event.event_type}"[:255],
        sequence=1,
        payload=envelope_payload,
        payload_hash=payload_digest(envelope_payload),
    )


def replay_raw_envelope(envelope, adapter):
    if payload_digest(envelope.payload) != envelope.payload_hash:
        raise ValidationError("RAW response envelope integrity check failed.")
    if envelope.sync_run_id is None:
        raise ValidationError("Webhook RAW envelopes require a webhook-specific replay handler.")
    adapter.validate_configuration(envelope.sync_run.sync_job)
    adapter.bind_run(envelope.sync_run)
    summary = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    for raw_record in envelope.payload.get("records", []):
        normalized = adapter.normalize_record(raw_record)
        if not adapter.validate_record(normalized):
            summary["failed"] += 1
            continue
        result = adapter.persist_record(envelope.sync_run.sync_job, normalized)
        action = result.get("action", "skipped")
        summary[action if action in summary else "skipped"] += 1
    return summary
