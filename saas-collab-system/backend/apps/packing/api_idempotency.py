import hashlib
import json

from django.db import IntegrityError, transaction
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.common.error_codes import ErrorCode
from apps.common.exceptions import IdempotencyConflict

from .models import PackingApiIdempotencyRecord, _packing_domain_write_context


def canonical_hash(payload):
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def idempotency_key(request):
    value = request.META.get("HTTP_IDEMPOTENCY_KEY", "")
    if not isinstance(value, str):
        raise ValidationError({"idempotency_key": "A valid Idempotency-Key is required."})
    normalized = value.strip()
    if (
        not 1 <= len(normalized) <= 128
        or any(ord(character) < 32 or ord(character) > 126 for character in normalized)
    ):
        raise ValidationError(
            {"idempotency_key": "Idempotency-Key must contain 1 to 128 printable ASCII characters."}
        )
    return normalized


def success_envelope(data):
    return {
        "success": True,
        "code": ErrorCode.OK,
        "message": "success",
        "data": data,
    }


def _assert_identity(
    record,
    *,
    actor,
    channel,
    action,
    scope_key,
    resource_key,
    request_hash,
):
    if (
        record.actor_id != actor.id
        or record.channel != channel
        or record.action != action
        or record.scope_key != scope_key
        or record.resource_key != resource_key
        or record.request_hash != request_hash
    ):
        raise IdempotencyConflict(
            "The idempotency key was already used by another actor, channel, action, resource, or payload."
        )


def _find_record(actor, key):
    return (
        PackingApiIdempotencyRecord.objects.select_for_update()
        .filter(tenant=actor.tenant, idempotency_key=key)
        .first()
    )


def _json_response(record, replayed):
    response = Response(record.response_body, status=record.http_status)
    response["Idempotency-Replayed"] = "true" if replayed else "false"
    return response


def execute_json_action(
    request,
    *,
    channel,
    action,
    scope_key,
    resource_key,
    payload,
    callback,
):
    key = idempotency_key(request)
    request_hash = canonical_hash(payload)
    identity = {
        "actor": request.user,
        "channel": channel,
        "action": action,
        "scope_key": scope_key,
        "resource_key": resource_key,
        "request_hash": request_hash,
    }
    try:
        with transaction.atomic():
            record = _find_record(request.user, key)
            if record:
                _assert_identity(record, **identity)
                if record.response_kind != PackingApiIdempotencyRecord.ResponseKind.JSON:
                    raise IdempotencyConflict("The idempotency key belongs to a label response.")
                return _json_response(record, True)

            data, http_status = callback(key)
            body = success_envelope(data)
            with _packing_domain_write_context():
                record = PackingApiIdempotencyRecord.objects.create(
                    tenant=request.user.tenant,
                    idempotency_key=key,
                    http_status=http_status,
                    response_kind=PackingApiIdempotencyRecord.ResponseKind.JSON,
                    response_body=body,
                    label_snapshot=None,
                    **identity,
                )
            return _json_response(record, False)
    except (IntegrityError, DjangoValidationError):
        with transaction.atomic():
            record = _find_record(request.user, key)
            if record is None:
                raise
            _assert_identity(record, **identity)
            if record.response_kind != PackingApiIdempotencyRecord.ResponseKind.JSON:
                raise IdempotencyConflict("The idempotency key belongs to a label response.")
            return _json_response(record, True)


def execute_label_action(
    request,
    *,
    channel,
    action,
    scope_key,
    resource_key,
    payload,
    callback,
    renderer,
):
    key = idempotency_key(request)
    request_hash = canonical_hash(payload)
    identity = {
        "actor": request.user,
        "channel": channel,
        "action": action,
        "scope_key": scope_key,
        "resource_key": resource_key,
        "request_hash": request_hash,
    }
    replayed = False
    try:
        with transaction.atomic():
            record = _find_record(request.user, key)
            if record:
                _assert_identity(record, **identity)
                if record.response_kind != PackingApiIdempotencyRecord.ResponseKind.LABEL:
                    raise IdempotencyConflict("The idempotency key belongs to a JSON response.")
                replayed = True
            else:
                snapshot, http_status = callback(key, request_hash)
                with _packing_domain_write_context():
                    record = PackingApiIdempotencyRecord.objects.create(
                        tenant=request.user.tenant,
                        idempotency_key=key,
                        http_status=http_status,
                        response_kind=PackingApiIdempotencyRecord.ResponseKind.LABEL,
                        response_body=None,
                        label_snapshot=snapshot,
                        **identity,
                    )
    except (IntegrityError, DjangoValidationError):
        with transaction.atomic():
            record = _find_record(request.user, key)
            if record is None:
                raise
            _assert_identity(record, **identity)
            if record.response_kind != PackingApiIdempotencyRecord.ResponseKind.LABEL:
                raise IdempotencyConflict("The idempotency key belongs to a JSON response.")
            replayed = True

    response = renderer(record.label_snapshot, status=record.http_status)
    response["Idempotency-Replayed"] = "true" if replayed else "false"
    return response
