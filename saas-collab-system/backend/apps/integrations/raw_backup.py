"""Create and verify offline packages for locally stored RAW payload objects.

This module deliberately does not access Django, a database, a network, or Docker.
"""

import gzip
import hashlib
import json
import os
import re
import secrets
import shutil
import stat
import zlib


MAX_PAYLOAD_BYTES = 32 * 1024 * 1024
MAX_MANIFEST_LINE_BYTES = 1024 * 1024
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY_RE = re.compile(
    r"^raw/(?P<namespace>[A-Za-z0-9][A-Za-z0-9._-]{0,63})/"
    r"tenant-(?P<tenant>[1-9][0-9]*)/(?P<uuid>[0-9a-f]{32})\.json\.gz$"
)
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
_CHUNK = 1024 * 1024


class RawBackupError(ValueError):
    """A safe, actionable backup package validation error."""


def _ordinary_file(path, label):
    try:
        info = os.lstat(path)
    except OSError:
        raise RawBackupError(f"{label} is missing or inaccessible.") from None
    if (not stat.S_ISREG(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT):
        raise RawBackupError(f"{label} must be an ordinary file, not a symlink or special file.")
    return info


def _ordinary_dir(path, label):
    try:
        info = os.lstat(path)
    except OSError:
        raise RawBackupError(f"{label} is missing or inaccessible.") from None
    if (not stat.S_ISDIR(info.st_mode)
            or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT):
        raise RawBackupError(f"{label} must be an ordinary directory.")
    return info


def _sha256_file(path, label):
    before = _ordinary_file(path, label)
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if _path_signature(opened) != _path_signature(before):
            raise RawBackupError(f"{label} changed while opening.")
        remaining = opened.st_size
        while remaining:
            chunk = stream.read(min(_CHUNK, remaining))
            if not chunk:
                raise RawBackupError(f"{label} changed while hashing.")
            digest.update(chunk)
            remaining -= len(chunk)
        if stream.read(1):
            raise RawBackupError(f"{label} grew while hashing.")
        after = os.fstat(stream.fileno())
        if _stat_signature(opened) != _stat_signature(after):
            raise RawBackupError(f"{label} changed while hashing.")
    return digest.hexdigest()


def _stat_signature(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _path_signature(info):
    # Windows may report a different creation/change timestamp for lstat and fstat.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


def _ensure_capacity(path, object_bytes, reserve_bytes):
    try:
        free_bytes = shutil.disk_usage(path).free
    except OSError:
        raise RawBackupError("Cannot determine available space on the package filesystem.") from None
    if free_bytes - object_bytes < reserve_bytes:
        raise RawBackupError("Insufficient free space to preserve the configured reserve.")


def _fsync_dir(path):
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _mkdir_private_tree(root, relative):
    current = root
    for component in relative.split(os.sep):
        parent = current
        current = os.path.join(current, component)
        try:
            os.mkdir(current, 0o700)
            _fsync_dir(parent)
        except FileExistsError:
            pass
        info = _ordinary_dir(current, "Package directory")
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise RawBackupError("Existing package directory is not private.")
        if os.name != "nt":
            os.chmod(current, 0o700)
    return current


def _parse_manifest_line(line, namespace):
    try:
        row = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise RawBackupError("Manifest contains an invalid JSONL row.") from None
    required = {"id", "raw_ref", "tenant_id", "payload_storage_alias",
                "payload_object_key", "payload_hash"}
    if not isinstance(row, dict) or set(row) != required:
        raise RawBackupError("Manifest row must contain exactly the required reference fields.")
    if (isinstance(row["id"], bool) or not isinstance(row["id"], int) or row["id"] <= 0
            or isinstance(row["tenant_id"], bool) or not isinstance(row["tenant_id"], int)
            or row["tenant_id"] <= 0):
        raise RawBackupError("Manifest row has an invalid id or tenant_id.")
    if not isinstance(row["raw_ref"], str) or not row["raw_ref"] or len(row["raw_ref"]) > 80:
        raise RawBackupError("Manifest row has an invalid raw_ref.")
    key = row["payload_object_key"]
    match = _KEY_RE.fullmatch(key) if isinstance(key, str) else None
    if (row["payload_storage_alias"] != "raw_local" or not match
            or match.group("namespace") != namespace
            or match.group("tenant") != str(row["tenant_id"])):
        raise RawBackupError("Manifest row has an invalid RAW storage alias or object key.")
    if not isinstance(row["payload_hash"], str) or not _HASH_RE.fullmatch(row["payload_hash"]):
        raise RawBackupError("Manifest row has an invalid payload_hash.")
    return row


def _iter_manifest(path, namespace, sink=None):
    count = 0
    ids, refs, objects = set(), set(), {}
    digest = hashlib.sha256()
    _ordinary_file(path, "Manifest")
    with open(path, "rb") as src:
        while True:
            line = src.readline(MAX_MANIFEST_LINE_BYTES + 1)
            if not line:
                break
            if len(line) > MAX_MANIFEST_LINE_BYTES:
                raise RawBackupError("Manifest row exceeds the 1 MiB limit.")
            digest.update(line)
            if not line.strip():
                raise RawBackupError("Manifest contains a blank row.")
            row = _parse_manifest_line(line, namespace)
            if row["id"] in ids or row["raw_ref"] in refs:
                raise RawBackupError("Manifest contains a duplicate id or raw_ref.")
            ids.add(row["id"])
            refs.add(row["raw_ref"])
            key = row["payload_object_key"]
            pair = (row["tenant_id"], row["payload_hash"])
            if key in objects and objects[key] != pair:
                raise RawBackupError("A shared object key has inconsistent tenant or payload_hash.")
            objects[key] = pair
            count += 1
            if sink is not None:
                sink.write(line)
    return count, objects, digest.hexdigest()


def _validate_object(source_path, expected_hash):
    info = _ordinary_file(source_path, "RAW object")
    if info.st_size > MAX_PAYLOAD_BYTES:
        raise RawBackupError("Compressed RAW object exceeds the 32 MiB limit.")
    raw_hash = hashlib.sha256()
    raw_bytes = bytearray()
    total = 0
    try:
        with open(source_path, "rb") as compressed, gzip.GzipFile(fileobj=compressed, mode="rb") as payload:
            while True:
                chunk = payload.read(min(_CHUNK, MAX_PAYLOAD_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_PAYLOAD_BYTES:
                    raise RawBackupError("Decompressed RAW payload exceeds the 32 MiB limit.")
                raw_hash.update(chunk)
                raw_bytes.extend(chunk)
    except RawBackupError:
        raise
    except (OSError, EOFError, gzip.BadGzipFile, zlib.error):
        raise RawBackupError("RAW object is not a valid complete gzip payload.") from None
    if raw_hash.hexdigest() != expected_hash:
        raise RawBackupError("RAW object canonical payload hash does not match payload_hash.")
    try:
        value = json.loads(raw_bytes.decode("utf-8"))
        canonical = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError, RecursionError):
        raise RawBackupError("RAW object is not canonical JSON payload data.") from None
    if not isinstance(value, dict) or canonical != raw_bytes:
        raise RawBackupError("RAW object is not a canonical JSON object payload.")
    # The receipt accounts for bytes actually stored in the package.
    return info.st_size


def _ensure_safe_tree(root, expected_files):
    """Reject symlinks, special files, and unreferenced files in package tree."""
    actual = set()
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for name in list(dirs):
            path = os.path.join(current, name)
            info = _ordinary_dir(path, "Package directory")
            rel = os.path.relpath(path, root).replace(os.sep, "/")
            actual.add(rel + "/")
        for name in files:
            path = os.path.join(current, name)
            _ordinary_file(path, "Package file")
            actual.add(os.path.relpath(path, root).replace(os.sep, "/"))
    if actual != expected_files:
        raise RawBackupError("Package contains missing or unexpected paths.")


def _safe_package_object(package_dir, key):
    # Keys are regex-validated before this is called, and contain only fixed safe components.
    path = os.path.join(package_dir, "objects", *key.split("/"))
    root = os.path.join(package_dir, "objects")
    current = root
    for component in key.split("/")[:-1]:
        current = os.path.join(current, component)
        _ordinary_dir(current, "Packaged object directory")
    _ordinary_file(path, "Packaged RAW object")
    return path


def _safe_source_object(source_root, key):
    path = os.path.join(source_root, *key.split("/"))
    current = source_root
    for component in key.split("/")[:-1]:
        current = os.path.join(current, component)
        _ordinary_dir(current, "RAW source directory")
    _ordinary_file(path, "RAW object")
    return path


def create_backup(manifest_path, database_backup_path, source_root, namespace, output_dir,
                  min_free_bytes=10737418240):
    """Build a new private package from a JSONL manifest and a local RAW root."""
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise RawBackupError("Invalid RAW namespace.")
    if (isinstance(min_free_bytes, bool) or not isinstance(min_free_bytes, int)
            or min_free_bytes < 0):
        raise RawBackupError("min_free_bytes must be a non-negative integer.")
    _ordinary_dir(source_root, "RAW source root")
    db_hash = _sha256_file(database_backup_path, "Database backup")
    output_parent = os.path.dirname(os.path.abspath(output_dir))
    _ensure_capacity(output_parent, 0, min_free_bytes)
    if os.path.lexists(output_dir):
        raise RawBackupError("Output directory already exists; refusing to overwrite it.")
    try:
        os.mkdir(output_dir, 0o700)
        if os.name != "nt":
            os.chmod(output_dir, 0o700)
        _fsync_dir(output_parent)
        os.mkdir(os.path.join(output_dir, "objects"), 0o700)
        _fsync_dir(output_dir)
        refs_path = os.path.join(output_dir, "refs.jsonl")
        with open(refs_path, "xb") as refs:
            if os.name != "nt":
                os.chmod(refs_path, 0o600)
            ref_count, objects, manifest_hash = _iter_manifest(manifest_path, namespace, refs)
            refs.flush()
            os.fsync(refs.fileno())
        _fsync_dir(output_dir)
        total_bytes = 0
        for key, (_tenant, payload_hash) in objects.items():
            source = _safe_source_object(source_root, key)
            _validate_object(source, payload_hash)
            target = os.path.join(output_dir, "objects", *key.split("/"))
            rel_dirs = os.path.dirname(key).split("/")
            target_parent = _mkdir_private_tree(os.path.join(output_dir, "objects"), os.path.join(*rel_dirs))
            initial = _ordinary_file(source, "RAW object")
            if initial.st_size > MAX_PAYLOAD_BYTES:
                raise RawBackupError("Compressed RAW object exceeds the 32 MiB limit.")
            _ensure_capacity(target_parent, initial.st_size, min_free_bytes)
            with open(source, "rb") as src, open(os.path.join(target_parent, os.path.basename(target)), "xb") as dst:
                if os.name != "nt":
                    os.chmod(dst.name, 0o600)
                opened = os.fstat(src.fileno())
                if _path_signature(opened) != _path_signature(initial):
                    raise RawBackupError("RAW object changed while opening for copy.")
                remaining = opened.st_size
                while remaining:
                    chunk = src.read(min(_CHUNK, remaining))
                    if not chunk:
                        raise RawBackupError("RAW object changed while being copied.")
                    dst.write(chunk)
                    remaining -= len(chunk)
                if src.read(1) or _stat_signature(opened) != _stat_signature(os.fstat(src.fileno())):
                    raise RawBackupError("RAW object changed while being copied.")
                dst.flush()
                os.fsync(dst.fileno())
            _fsync_dir(target_parent)
            _fsync_dir(os.path.join(output_dir, "objects"))
            # Validate the copied bytes as well, catching source changes during copy.
            total_bytes += _validate_object(target, payload_hash)
        receipt = {
            "format_version": 1,
            "namespace": namespace,
            "database_backup_sha256": db_hash,
            "manifest_sha256": manifest_hash,
            "reference_count": ref_count,
            "object_count": len(objects),
            "total_bytes": total_bytes,
        }
        # Receipt is the completion marker and is written only after every object passes.
        receipt_path = os.path.join(output_dir, "receipt.json")
        temp_receipt = os.path.join(output_dir, ".receipt-" + secrets.token_hex(12))
        published = False
        try:
            with open(temp_receipt, "x", encoding="utf-8", newline="\n") as stream:
                if os.name != "nt":
                    os.chmod(temp_receipt, 0o600)
                json.dump(receipt, stream, sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            # Hard-link publication is atomic and fails if receipt.json already exists.
            os.link(temp_receipt, receipt_path)
            published = True
            # Cleanup is part of successful publication: a leftover temporary
            # receipt would make the exact-tree verifier reject this package.
            os.unlink(temp_receipt)
            _fsync_dir(output_dir)
        except Exception:
            if published:
                try:
                    os.unlink(receipt_path)
                    _fsync_dir(output_dir)
                except OSError:
                    pass
            raise
        finally:
            try:
                os.unlink(temp_receipt)
            except OSError:
                pass
        return {"status": "complete", "reference_count": ref_count,
                "object_count": len(objects), "total_bytes": total_bytes,
                "database_backup_sha256": db_hash, "manifest_sha256": manifest_hash}
    except RawBackupError:
        raise
    except Exception as exc:
        raise RawBackupError(f"Backup package creation failed: {type(exc).__name__}.") from None


def verify_backup(package_dir, database_backup_path):
    """Verify a RAW package against its referenced database backup; never restore data."""
    _ordinary_dir(package_dir, "Package")
    _ordinary_file(database_backup_path, "Database backup")
    receipt_path = os.path.join(package_dir, "receipt.json")
    _ordinary_file(receipt_path, "Completion receipt")
    try:
        if os.path.getsize(receipt_path) > 64 * 1024:
            raise RawBackupError("Completion receipt exceeds the 64 KiB limit.")
        with open(receipt_path, "rb") as stream:
            raw_receipt = stream.read(64 * 1024 + 1)
        if len(raw_receipt) > 64 * 1024:
            raise RawBackupError("Completion receipt exceeds the 64 KiB limit.")
        receipt = json.loads(raw_receipt.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise RawBackupError("Completion receipt is invalid.") from None
    fields = {"format_version", "namespace", "database_backup_sha256", "manifest_sha256",
              "reference_count", "object_count", "total_bytes"}
    if (not isinstance(receipt, dict) or set(receipt) != fields
            or type(receipt.get("format_version")) is not int or receipt.get("format_version") != 1):
        raise RawBackupError("Completion receipt has an unsupported format or fields.")
    namespace = receipt.get("namespace")
    if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
        raise RawBackupError("Completion receipt has an invalid namespace.")
    for name in ("reference_count", "object_count", "total_bytes"):
        value = receipt[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise RawBackupError(f"Completion receipt has an invalid {name}.")
    for name in ("database_backup_sha256", "manifest_sha256"):
        if not isinstance(receipt[name], str) or not _HASH_RE.fullmatch(receipt[name]):
            raise RawBackupError(f"Completion receipt has an invalid {name}.")
    if _sha256_file(database_backup_path, "Database backup") != receipt["database_backup_sha256"]:
        raise RawBackupError("Database backup SHA256 does not match this package.")
    refs_path = os.path.join(package_dir, "refs.jsonl")
    _ordinary_file(refs_path, "Reference manifest")
    with open(os.devnull, "wb") as sink:
        ref_count, objects, manifest_hash = _iter_manifest(refs_path, namespace, sink)
    if manifest_hash != receipt["manifest_sha256"]:
        raise RawBackupError("Reference manifest SHA256 does not match the receipt.")
    if ref_count != receipt["reference_count"] or len(objects) != receipt["object_count"]:
        raise RawBackupError("Reference or object counts do not match the receipt.")
    expected_files = {"receipt.json", "refs.jsonl", "objects/"}
    expected_files.update("objects/" + key for key in objects)
    # Include each directory path so the tree must exactly correspond to the manifest.
    for key in objects:
        parts = ("objects", *key.split("/")[:-1])
        for index in range(1, len(parts) + 1):
            expected_files.add("/".join(parts[:index]) + "/")
    _ensure_safe_tree(package_dir, expected_files)
    total_bytes = 0
    for key, (_tenant, payload_hash) in objects.items():
        total_bytes += _validate_object(_safe_package_object(package_dir, key), payload_hash)
    if total_bytes != receipt["total_bytes"]:
        raise RawBackupError("Payload byte count does not match the receipt.")
    return {"status": "verified", "reference_count": ref_count,
            "object_count": len(objects), "total_bytes": total_bytes,
            "database_backup_sha256": receipt["database_backup_sha256"],
            "manifest_sha256": manifest_hash}
