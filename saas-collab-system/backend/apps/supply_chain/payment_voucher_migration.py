"""Bounded, restartable voucher BLOB offload. Caller persists checkpoints.

No transaction spans object storage, and no object is deleted. A failed row
stops the batch without advancing its checkpoint; retry the same interval.
"""
from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connection
from django.db.models import BigIntegerField, Func, QuerySet

from .models import PaymentVoucher
from . import payment_voucher_storage as store


class _ByteLength(Func):
    function = "OCTET_LENGTH"
    output_field = BigIntegerField()

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection,
                           template="LENGTH(CAST(%(expressions)s AS BLOB))", **extra_context)


class _Failure(Exception):
    pass


def _bounded_row(pk):
    # The body-fetching SELECT itself enforces the bound, including races after
    # the metadata SELECT. PositiveIntegerField alone does not bound the BLOB.
    return PaymentVoucher.objects.annotate(_size=_ByteLength("content")).get(
        pk=pk, _size__lte=store.MAX_BYTES)


def _key(row):
    if bool(row.payment_id) == bool(row.settlement_revision_id):
        raise _Failure("parent_metadata")
    return store.object_key(row.tenant_id,
                            "payment" if row.payment_id else "settlement_revision",
                            row.payment_id or row.settlement_revision_id,
                            row.idempotency_key, row.sha256)


def _external(row, alias):
    if (row.content or row.content_storage_alias != alias
            or row.content_object_key != _key(row)):
        raise _Failure("external_metadata")
    return store.read_content(row)


def migrate_batch(after_id, through_id, max_rows, max_bytes, apply=False):
    """Inspect PKs in (after_id, through_id], bounded by rows and raw bytes.

    Dry-run validates inline bytes/hash and existing external references without
    writes. bytes_read counts validated original file bytes; max_bytes bounds
    those original bytes (envelope GET has its own fixed helper limit). A byte
    budget stop leaves the next row pending. source_rows includes a failed or
    pending row; target_rows counts verified external references. Caller owns
    singleton scheduling and durable checkpoint storage, including on failures.
    """
    for value in (after_id, through_id, max_rows, max_bytes):
        if type(value) is not int or value < 0:
            raise ValueError("bounds must be nonnegative integers")
    if (through_id < after_id or not 1 <= max_rows <= 10000
            or max_bytes < 1 or type(apply) is not bool):
        raise ValueError("invalid batch bounds")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("migration requires autocommit outside atomic blocks")
    alias = getattr(settings, "PAYMENT_VOUCHER_STORAGE_ALIAS", "").strip()
    if not alias or len(alias) > 80:
        raise ValueError("voucher storage alias is required")
    # Validate namespace even for an empty batch, before returning success.
    store.object_key(1, "payment", 1, "configuration-check", "0" * 64)
    storage = store.storages[alias]
    result = dict(status="complete", source_rows=0, target_rows=0,
                  schema_diff_count=0, constraint_violations=0, mismatched_chunks=0,
                  sample_artifact=None, recommended_action="persist_checkpoint",
                  checkpoint=after_id, through_id=through_id, bytes_read=0,
                  bytes_uploaded=0, bytes_upload_attempted=0, uncertain_upload_responses=0,
                  migrated_rows=0, planned_rows=0, errors=0,
                  potential_orphan_objects=0, failed_id=None, error_code=None)
    rows = list(PaymentVoucher.objects.filter(pk__gt=after_id, pk__lte=through_id)
                .order_by("pk").annotate(_size=_ByteLength("content"))
                .values("pk", "_size", "byte_size")[:max_rows + 1])
    for item in rows[:max_rows]:
        object_at_risk = False
        referenced = False
        result["source_rows"] += 1
        try:
            if item["_size"] is None or item["_size"] > store.MAX_BYTES:
                raise _Failure("inline_database_limit")
            if not 0 < item["byte_size"] <= store.MAX_BYTES:
                raise _Failure("file_size_metadata")
            if result["bytes_read"] + item["byte_size"] > max_bytes:
                result.update(status="byte_budget", recommended_action="retry_from_checkpoint_with_sufficient_byte_budget")
                break
            row = _bounded_row(item["pk"])
            if not 0 < row.byte_size <= store.MAX_BYTES:
                raise _Failure("file_size_metadata")
            if result["bytes_read"] + row.byte_size > max_bytes:
                result.update(status="byte_budget", recommended_action="retry_from_checkpoint_with_sufficient_byte_budget")
                break
            candidate_key = _key(row)
            if row.content_storage_alias or row.content_object_key:
                raw = _external(row, alias)
                result["bytes_read"] += len(raw)
                result["target_rows"] += 1
            else:
                raw = store.validate_content(bytes(row.content or b""), row.byte_size, row.sha256)
                result["bytes_read"] += len(raw)
                if not apply:
                    result["planned_rows"] += 1
                else:
                    envelope = store.encode_content(raw, row.byte_size, row.sha256)
                    # RAW storage has no exists/delete. GET permits a restart
                    # after a completed PUT without another immutable PUT.
                    try:
                        actual = store._read(storage, candidate_key, row.byte_size, row.sha256)
                        object_at_risk = True
                    except Exception:
                        object_at_risk = True
                        result["bytes_upload_attempted"] += len(envelope)
                        try:
                            saved = storage.save(candidate_key, ContentFile(envelope))
                            result["bytes_uploaded"] += len(envelope)
                        except Exception:
                            # A failed response does not prove PUT failed.
                            saved = candidate_key
                            result["uncertain_upload_responses"] += 1
                        if saved != candidate_key:
                            raise _Failure("storage_renamed_object")
                        actual = store._read(storage, candidate_key, row.byte_size, row.sha256)
                    if actual != raw:
                        raise _Failure("object_bytes_mismatch")
                    cas = PaymentVoucher.objects.filter(
                        pk=row.pk, tenant_id=row.tenant_id, sha256=row.sha256,
                        byte_size=row.byte_size, payment_id=row.payment_id,
                        settlement_revision_id=row.settlement_revision_id,
                        idempotency_key=row.idempotency_key,
                        content_storage_alias=row.content_storage_alias,
                        content_object_key=row.content_object_key, content=raw,
                    )
                    # Record's normal manager forbids every update, even under
                    # domain_write. This narrowly scoped maintenance CAS uses
                    # Django's base implementation; normal writes stay guarded.
                    changed = QuerySet.update(cas, content=b"", content_storage_alias=alias,
                                              content_object_key=candidate_key)
                    if changed:
                        referenced = True
                        result["migrated_rows"] += 1
                    else:
                        current = _bounded_row(row.pk)
                        if (current.tenant_id != row.tenant_id or current.sha256 != row.sha256
                                or current.byte_size != row.byte_size
                                or current.content_object_key != candidate_key):
                            raise _Failure("cas_conflict")
                        if _external(current, alias) != raw:
                            raise _Failure("cas_conflict")
                        referenced = True
                    result["target_rows"] += 1
            result["checkpoint"] = row.pk
        except Exception as exc:
            result.update(status="failed", failed_id=item["pk"], errors=1,
                          constraint_violations=1, mismatched_chunks=1,
                          error_code=str(exc) if isinstance(exc, _Failure) else "storage_or_database_error",
                          recommended_action="repair_failed_row_then_retry_from_checkpoint")
            break
        finally:
            if object_at_risk and not referenced:
                result["potential_orphan_objects"] += 1
    if result["status"] == "complete" and len(rows) > max_rows:
        result.update(status="more", recommended_action="continue_from_checkpoint")
    return result
