"""Bounded, restartable offload of immutable TikTok video evidence.

The caller owns scheduling, a singleton lock and durable checkpoint storage. A
checkpoint advances only after a row is verified (or inspected in dry-run).
No exception text or payload is returned, and objects are never deleted.
"""
import gzip
import hashlib
import io
import re

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.db import connection
from django.db.models import BigIntegerField, Func, TextField
from django.db.models.functions import Cast

from .models import TikTokVideoSyncEvidence
from .tiktok_shop_dataset import canonical_bytes

LIMIT = 32 * 1024 * 1024


class _ByteLength(Func):
    function = "OCTET_LENGTH"
    output_field = BigIntegerField()

    def as_sqlite(self, compiler, connection, **extra_context):
        return self.as_sql(compiler, connection, template="LENGTH(CAST(%(expressions)s AS BLOB))", **extra_context)


class _Failure(Exception):
    pass


def _bounded_row(pk):
    # Apply the bound in the SELECT that fetches JSON too, closing the race
    # between the metadata query and a concurrent writer.
    return TikTokVideoSyncEvidence.objects.annotate(
        _size=_ByteLength(Cast("payload", TextField()))
    ).get(pk=pk, _size__lte=LIMIT)


def _canonical(payload, expected_hash):
    if not isinstance(payload, dict):
        raise _Failure("payload_type")
    raw = canonical_bytes(payload)
    if len(raw) > LIMIT:
        raise _Failure("payload_limit")
    if hashlib.sha256(raw).hexdigest() != expected_hash:
        raise _Failure("payload_hash")
    return raw


def _read(storage, key):
    with storage.open(key, "rb") as source:
        compressed = source.read(LIMIT + 1)
    if len(compressed) > LIMIT:
        raise _Failure("compressed_limit")
    with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as source:
        raw = source.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise _Failure("payload_limit")
    return compressed, raw


def _external(row, alias, namespace):
    prefix = f"raw/{namespace}/tenant-{row.tenant_id}/"
    if (row.payload != {} or row.payload_storage_alias != alias or
            not re.fullmatch(re.escape(prefix) + r"[0-9a-f]{32}\.json\.gz", row.payload_object_key or "")):
        raise _Failure("external_metadata")
    raw = _canonical(row.read_payload(), row.payload_hash)
    return len(raw)


def migrate_batch(after_id, through_id, max_rows, max_bytes, apply=False):
    """Inspect PKs (after_id, through_id], at most max_rows/max_bytes raw bytes.

    Returns aggregate counters; checkpoint is safe to persist even on failure.
    Dry-run performs no storage writes or database updates. target_rows counts
    verified external rows; planned_rows counts valid inline rows in dry-run.
    A byte budget smaller than the next row returns byte_budget without skipping
    it. Consumers must retry with a sufficient budget. No network call holds a
    transaction opened by this function; callers must also use autocommit.
    """
    for value in (after_id, through_id, max_rows, max_bytes):
        if type(value) is not int or value < 0:
            raise ValueError("bounds must be nonnegative integers")
    if through_id < after_id or not 1 <= max_rows <= 10000 or max_bytes < 1 or type(apply) is not bool:
        raise ValueError("invalid batch bounds")
    if connection.in_atomic_block or not connection.get_autocommit():
        raise ValueError("migration requires autocommit outside atomic blocks")
    result = dict(status="complete", source_rows=0, target_rows=0,
                  schema_diff_count=0, constraint_violations=0, mismatched_chunks=0,
                  sample_artifact=None, recommended_action="persist_checkpoint",
                  checkpoint=after_id, through_id=through_id, bytes_read=0,
                  bytes_uploaded=0, bytes_upload_attempted=0, uncertain_upload_responses=0,
                  migrated_rows=0, planned_rows=0, errors=0,
                  potential_orphan_objects=0, failed_id=None, error_code=None)
    alias = getattr(settings, "RAW_PAYLOAD_STORAGE_ALIAS", "").strip()
    namespace = getattr(settings, "RAW_PAYLOAD_STORAGE_NAMESPACE", "").strip()
    if not alias or len(alias) > 80 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", namespace):
        raise ValueError("raw payload storage configuration is invalid")
    storage = storages[alias]
    # Metadata first: reject oversized DB values before Django deserializes JSON.
    rows = list(TikTokVideoSyncEvidence.objects.filter(pk__gt=after_id, pk__lte=through_id)
                .order_by("pk").annotate(_size=_ByteLength(Cast("payload", TextField())))
                .values("pk", "_size")[:max_rows + 1])
    for item in rows[:max_rows]:
        candidate_key = None
        may_have_written = False
        referenced = False
        result["source_rows"] += 1
        try:
            if item["_size"] is None or item["_size"] > LIMIT:
                raise _Failure("inline_database_limit")
            row = _bounded_row(item["pk"])
            if row.payload_storage_alias is not None or row.payload_object_key is not None:
                size = _external(row, alias, namespace)
                if result["bytes_read"] + size > max_bytes:
                    result.update(status="byte_budget", recommended_action="retry_from_checkpoint_with_sufficient_byte_budget")
                    break
                result["bytes_read"] += size
                result["target_rows"] += 1
            else:
                raw = _canonical(row.payload, row.payload_hash)
                if result["bytes_read"] + len(raw) > max_bytes:
                    result.update(status="byte_budget", recommended_action="retry_from_checkpoint_with_sufficient_byte_budget")
                    break
                result["bytes_read"] += len(raw)
                if not apply:
                    result["planned_rows"] += 1
                else:
                    compressed = gzip.compress(raw, mtime=0)
                    if len(compressed) > LIMIT:
                        raise _Failure("compressed_limit")
                    # Include the model type and PK to prevent cross-type reuse.
                    identity = f"TikTokVideoSyncEvidence:{row.tenant_id}:{row.pk}:{row.payload_hash}"
                    stable_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]
                    candidate_key = f"raw/{namespace}/tenant-{row.tenant_id}/{stable_id}.json.gz"
                    # Production RAW storage deliberately has no exists(). A
                    # verified GET reuses a prior upload without another PUT.
                    try:
                        actual_compressed, actual_raw = _read(storage, candidate_key)
                    except Exception:
                        may_have_written = True
                        result["bytes_upload_attempted"] += len(compressed)
                        try:
                            saved = storage.save(candidate_key, ContentFile(compressed))
                            result["bytes_uploaded"] += len(compressed)
                        except Exception:
                            # Immutable PUT can conflict, or succeed before its
                            # response is lost. Resolve both by a bounded GET.
                            saved = candidate_key
                            result["uncertain_upload_responses"] += 1
                        if saved != candidate_key:
                            raise _Failure("storage_renamed_object")
                        actual_compressed, actual_raw = _read(storage, candidate_key)
                    if actual_compressed != compressed or actual_raw != raw:
                        raise _Failure("object_bytes_mismatch")
                    changed = TikTokVideoSyncEvidence.objects.filter(
                        pk=row.pk, tenant_id=row.tenant_id, payload_hash=row.payload_hash,
                        payload_storage_alias__isnull=True, payload_object_key__isnull=True,
                        payload=row.payload,
                    ).update(payload={}, payload_storage_alias=alias, payload_object_key=candidate_key)
                    if changed:
                        referenced = True
                        result["migrated_rows"] += 1
                    else:
                        current = _bounded_row(row.pk)
                        if current.tenant_id != row.tenant_id or current.payload_hash != row.payload_hash:
                            raise _Failure("cas_conflict")
                        _external(current, alias, namespace)
                        referenced = current.payload_object_key == candidate_key
                    result["target_rows"] += 1
            result["checkpoint"] = row.pk
        except Exception as exc:
            result.update(status="failed", failed_id=item["pk"], errors=1,
                          constraint_violations=1, mismatched_chunks=1,
                          error_code=str(exc) if isinstance(exc, _Failure) else "storage_or_database_error",
                          recommended_action="repair_failed_row_then_retry_from_checkpoint")
            break
        finally:
            if may_have_written and not referenced:
                result["potential_orphan_objects"] += 1
    if result["status"] == "complete" and len(rows) > max_rows:
        result.update(status="more", recommended_action="continue_from_checkpoint")
    return result
