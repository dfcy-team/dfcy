"""Bounded, private payment files in the existing immutable RAW object store."""
import base64
import gzip
import hashlib
import json
import re
from io import BytesIO

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages

MAX_BYTES = 10 * 1024 * 1024
MAX_ENVELOPE_BYTES = 32 * 1024 * 1024
SCHEMA = "payment-voucher-v1"


class VoucherStorageError(Exception):
    """Fixed-message error safe to expose through an authenticated API."""


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _identity(tenant_id, parent_kind, parent_id, idempotency_key, sha256):
    if (type(tenant_id) is not int or tenant_id <= 0 or type(parent_id) is not int
            or parent_id <= 0 or parent_kind not in {"payment", "settlement_revision"}
            or not isinstance(idempotency_key, str) or not 0 < len(idempotency_key) <= 128
            or not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256)):
        raise VoucherStorageError("凭证存储标识无效。")
    return [SCHEMA, tenant_id, parent_kind, parent_id, idempotency_key, sha256]


def object_key(tenant_id, parent_kind, parent_id, idempotency_key, sha256):
    identity = _identity(tenant_id, parent_kind, parent_id, idempotency_key, sha256)
    namespace = getattr(settings, "RAW_PAYLOAD_STORAGE_NAMESPACE", "").strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", namespace):
        raise VoucherStorageError("凭证存储配置无效。")
    stable_id = hashlib.sha256(_canonical(identity)).hexdigest()[:32]
    return f"raw/{namespace}/tenant-{tenant_id}/{stable_id}.json.gz"


def validate_content(body, byte_size, sha256):
    if (type(byte_size) is not int or not 0 < byte_size <= MAX_BYTES
            or len(body) != byte_size or hashlib.sha256(body).hexdigest() != sha256):
        raise VoucherStorageError("凭证内容完整性校验失败。")
    return body


def encode_content(body, byte_size, sha256):
    validate_content(body, byte_size, sha256)
    return gzip.compress(_canonical({"schema": SCHEMA, "content_base64": base64.b64encode(body).decode("ascii"),
                                    "sha256": sha256, "byte_size": byte_size}), mtime=0)


def decode_content(compressed, byte_size, sha256):
    try:
        if len(compressed) > MAX_ENVELOPE_BYTES:
            raise ValueError()
        with gzip.GzipFile(fileobj=BytesIO(compressed)) as source:
            raw = source.read(MAX_ENVELOPE_BYTES + 1)
        if len(raw) > MAX_ENVELOPE_BYTES:
            raise ValueError()
        envelope = json.loads(raw.decode("utf-8"))
        if (not isinstance(envelope, dict)
                or set(envelope) != {"schema", "content_base64", "sha256", "byte_size"}
                or envelope["schema"] != SCHEMA or type(envelope["byte_size"]) is not int
                or envelope["byte_size"] != byte_size or envelope["sha256"] != sha256
                or _canonical(envelope) != raw):
            raise ValueError()
        body = base64.b64decode(envelope["content_base64"], validate=True)
        if base64.b64encode(body).decode("ascii") != envelope["content_base64"]:
            raise ValueError()
        return validate_content(body, byte_size, sha256)
    except VoucherStorageError:
        raise
    except Exception as exc:
        raise VoucherStorageError("凭证内容完整性校验失败。") from exc


def _read(storage, key, byte_size, sha256):
    with storage.open(key, "rb") as source:
        compressed = source.read(MAX_ENVELOPE_BYTES + 1)
    return decode_content(compressed, byte_size, sha256)


def store_content(*, body, tenant_id, parent_kind, parent_id, idempotency_key, sha256):
    """Return DB fields only after a successful authenticated read-back."""
    validate_content(body, len(body), sha256)
    alias = getattr(settings, "PAYMENT_VOUCHER_STORAGE_ALIAS", "").strip()
    if not alias:
        return {"content": body, "content_storage_alias": None, "content_object_key": None}
    if len(alias) > 80:
        raise VoucherStorageError("凭证存储配置无效。")
    key = object_key(tenant_id, parent_kind, parent_id, idempotency_key, sha256)
    try:
        storage = storages[alias]
        try:
            saved = storage.save(key, ContentFile(encode_content(body, len(body), sha256)))
        except Exception:
            # PUT may succeed while its response is lost, or an immutable retry may conflict.
            saved = key
        if saved != key or _read(storage, key, len(body), sha256) != body:
            raise ValueError("read-back failed")
    except Exception as exc:
        raise VoucherStorageError("凭证存储暂不可用，请重试。") from exc
    return {"content": b"", "content_storage_alias": alias, "content_object_key": key}


def read_content(voucher):
    alias, key = voucher.content_storage_alias, voucher.content_object_key
    if not alias and not key:
        return validate_content(bytes(voucher.content or b""), voucher.byte_size, voucher.sha256)
    if not alias or not key or voucher.content:
        raise VoucherStorageError("凭证存储引用无效。")
    parent_kind = "payment" if voucher.payment_id else "settlement_revision"
    parent_id = voucher.payment_id or voucher.settlement_revision_id
    expected = object_key(voucher.tenant_id, parent_kind, parent_id, voucher.idempotency_key, voucher.sha256)
    if key != expected:
        raise VoucherStorageError("凭证存储引用无效。")
    try:
        return _read(storages[alias], key, voucher.byte_size, voucher.sha256)
    except VoucherStorageError:
        raise
    except Exception as exc:
        raise VoucherStorageError("凭证存储暂不可用，请重试。") from exc
