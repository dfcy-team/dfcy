"""Private report exports: explicit storage identity, verified reads, no deletion.

An empty alias is the historical REPORT_EXPORT_ROOT. Never reinterpret an old
record using today's write alias, or fall back to local on an object-store error.
"""
import hashlib
import os
from pathlib import Path
import re
from tempfile import SpooledTemporaryFile
import uuid

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from rest_framework.exceptions import ValidationError

CHUNK = 64 * 1024
MAX_BYTES = 32 * 1024 * 1024
META_FIELDS = ["storage_key", "storage_alias", "file_size", "content_type", "file_sha256"]


def _storage(alias):
    if alias not in getattr(settings, "REPORT_EXPORT_ALLOWED_STORAGE_ALIASES", ()):
        raise ValidationError("报表对象存储未获准，请检查配置。")
    try:
        return storages[alias]
    except Exception:
        raise ValidationError("报表对象存储暂不可用。") from None


def _key(record):
    tenant = re.escape(str(record.tenant_id))
    suffix = re.escape(record.file_format)
    pattern = (rf"reports/[A-Za-z0-9][A-Za-z0-9._-]{{0,63}}/tenant-{tenant}/[0-9a-f]{{32}}\.{suffix}"
               if record.storage_alias else rf"{tenant}/[0-9a-f]{{32}}\.{suffix}")
    if record.file_format not in {"csv", "txt"} or not re.fullmatch(pattern, record.storage_key):
        raise ValidationError("报表文件标识无效。")
    return record.storage_key


def _local_path(record):
    root = Path(settings.REPORT_EXPORT_ROOT).resolve()
    target = root / _key(record)
    if target.parent.is_symlink() or target.is_symlink() or root not in target.resolve().parents:
        raise ValidationError("报表文件路径无效。")
    return target


def write_export(record, content):
    alias = getattr(settings, "REPORT_EXPORT_WRITE_STORAGE_ALIAS", "")
    if not isinstance(content, bytes):
        raise ValidationError("报表文件内容无效。")
    if alias and len(content) > MAX_BYTES:
        raise ValidationError("报表对象文件超过32MiB上限，请缩小导出范围。")
    storage = _storage(alias) if alias else None
    namespace = getattr(storage, "namespace", "reports") if storage else None
    filename = f"{uuid.uuid4().hex}.{record.file_format}"
    key = f"reports/{namespace}/tenant-{record.tenant_id}/{filename}" if alias else f"{record.tenant_id}/{filename}"
    # Validate without changing the request's successful file metadata yet.
    from types import SimpleNamespace
    reference = SimpleNamespace(tenant_id=record.tenant_id, file_format=record.file_format,
                                storage_alias=alias, storage_key=key)
    _key(reference)
    try:
        if storage:
            if storage.save(key, ContentFile(content)) != key:
                raise ValueError("Storage renamed immutable key")
        else:
            target = _local_path(reference)
            target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            temporary = target.with_name(f".{filename}.tmp")
            try:
                with temporary.open("xb") as out:
                    out.write(content)
                os.replace(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
    except Exception:
        # No provider details or local fallback. An uncertain upload may leave
        # an orphan: inventory it; never retry or delete it automatically.
        raise ValidationError("报表文件保存失败，请稍后重新申请导出。") from None
    reference.file_size = len(content)
    reference.file_sha256 = hashlib.sha256(content).hexdigest()
    # Verify the stored bytes before publishing a completed file reference.
    with open_verified_export(reference):
        pass
    record.storage_alias, record.storage_key = alias, key
    record.file_size = len(content)
    record.file_sha256 = reference.file_sha256
    record.content_type = "text/csv; charset=utf-8" if record.file_format == "csv" else "text/plain; charset=utf-8"


def open_verified_export(record):
    key = _key(record)
    result = SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b")
    try:
        source = _storage(record.storage_alias).open(key, "rb") if record.storage_alias else _local_path(record).open("rb")
        digest, size = hashlib.sha256(), 0
        with source:
            while chunk := source.read(CHUNK):
                size += len(chunk)
                if size > MAX_BYTES and record.storage_alias:
                    raise ValueError("Oversized export")
                digest.update(chunk)
                result.write(chunk)
        if digest.hexdigest() != record.file_sha256 or (record.file_size is not None and size != record.file_size):
            raise ValueError("Integrity mismatch")
        result.seek(0)
        return result
    except Exception:
        result.close()
        raise ValidationError("报表文件不可用或完整性校验失败，请重新申请导出。") from None
