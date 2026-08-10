"""Filesystem custody stored outside Git and the application database."""

from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import tempfile
import threading
import uuid
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MASK = "********"
ACTIVE = "active"
REVOKED = "revoked"
EXPIRED = "expired"


class CredentialReference(dict):
    _FIELDS = {
        "credential_id",
        "token_id",
        "mask",
        "version",
        "expires_at",
        "status",
        "operation_id_hash",
    }

    def __init__(self, **metadata):
        if set(metadata) != self._FIELDS:
            raise ValueError("Credential reference metadata is incomplete.")
        super().__init__(metadata)

    def __getattr__(self, name):
        if name in self._FIELDS:
            return self[name]
        raise AttributeError(name)


class FileCustodyError(Exception):
    """Base error with deliberately non-sensitive messages."""


class FileCustodyValidationError(FileCustodyError, ValueError):
    pass


class FileCustodyNotFoundError(FileCustodyError, KeyError):
    pass


class FileCustodyRevokedError(FileCustodyError):
    pass


class FileCustodyExpiredError(FileCustodyError):
    pass


class FileCustodyIdempotencyConflict(FileCustodyError):
    pass


class FileCustodyVersionConflict(FileCustodyError):
    pass


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise FileCustodyValidationError("Credential values must be JSON-compatible.") from exc


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _operation_hash(value: str) -> str:
    return hashlib.sha256(f"credential-custody:{value}".encode()).hexdigest()


def _expiry(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        current = value
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        text = value.strip()
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FileCustodyValidationError("expires_at must be an ISO-8601 timestamp.") from exc
        return text
    raise FileCustodyValidationError("expires_at must be an ISO-8601 timestamp.")


def _is_expired(value: str | None) -> bool:
    if not value:
        return False
    current = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current <= datetime.now(timezone.utc)


def _safe_values(credentials: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(credentials, Mapping) or not credentials:
        raise FileCustodyValidationError("At least one credential value is required.")
    try:
        values = copy.deepcopy(dict(credentials))
    except Exception as exc:
        raise FileCustodyValidationError("Credential values could not be copied safely.") from exc
    if any(not isinstance(key, str) or not key.strip() for key in values):
        raise FileCustodyValidationError("Credential names must be non-empty strings.")
    if any(value in (None, "") for value in values.values()):
        raise FileCustodyValidationError("Credential values must be non-empty.")
    _canonical_json(values)
    return values


_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def _local_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCAL_LOCKS_GUARD:
        return _LOCAL_LOCKS.setdefault(key, threading.RLock())


@contextlib.contextmanager
def _process_lock(path: Path) -> Iterator[None]:
    handle = path.open("a+b")
    windows_locked = False
    unix_locked = False
    try:
        try:
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            unix_locked = True
        except ImportError:
            try:
                import msvcrt  # type: ignore

                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                windows_locked = True
            except ImportError as exc:
                raise FileCustodyError("Cross-process custody locking is unavailable.") from exc
        yield
    except OSError as exc:
        raise FileCustodyError("Credential custody lock is unavailable.") from exc
    finally:
        try:
            if unix_locked:
                import fcntl  # type: ignore

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            if windows_locked:
                import msvcrt  # type: ignore

                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        finally:
            handle.close()


class FileCredentialStore:
    """Atomic, permission-restricted local credential store."""

    def __init__(self, path: str | os.PathLike[str]):
        if not path:
            raise FileCustodyValidationError("CREDENTIAL_CUSTODY_PATH is required.")
        self.path = Path(path).expanduser()
        if not self.path.is_absolute():
            raise FileCustodyValidationError("CREDENTIAL_CUSTODY_PATH must be absolute.")
        self._lock = _local_lock(self.path)
        self._ensure_directory()

    def _ensure_directory(self):
        try:
            self.path.mkdir(parents=True, exist_ok=True)
            if self.path.is_symlink() or not self.path.is_dir():
                raise FileCustodyError("Credential custody path must be a real directory.")
            try:
                os.chmod(self.path, 0o700)
            except OSError:
                if os.name != "nt":
                    raise
        except OSError as exc:
            raise FileCustodyError("Credential custody directory is unavailable.") from exc

    def _record_path(self, credential_id: str) -> Path:
        if not credential_id.startswith("cred_") or Path(credential_id).name != credential_id:
            raise FileCustodyValidationError("Invalid credential reference.")
        return self.path / f"{credential_id}.json"

    def _paths(self):
        return sorted(self.path.glob("cred_*.json"))

    def _read(self, path: Path) -> dict[str, Any]:
        if path.is_symlink():
            raise FileCustodyError("Credential custody record is invalid.")
        try:
            with path.open("r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, TypeError, ValueError) as exc:
            raise FileCustodyError("Credential custody record is unavailable.") from exc
        if not isinstance(record, dict) or not str(record.get("credential_id", "")).startswith("cred_"):
            raise FileCustodyError("Credential custody record is invalid.")
        return record

    def _write(self, credential_id: str, record: Mapping[str, Any]):
        destination = self._record_path(credential_id)
        file_descriptor = None
        temporary_path = None
        try:
            file_descriptor, temporary_path = tempfile.mkstemp(prefix=".credential-", suffix=".tmp", dir=self.path)
            try:
                os.fchmod(file_descriptor, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(file_descriptor, "wb") as handle:
                file_descriptor = None
                handle.write(_canonical_json(dict(record)))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            try:
                os.chmod(destination, 0o600)
            except OSError:
                if os.name != "nt":
                    raise
        except OSError as exc:
            raise FileCustodyError("Credential custody record could not be written.") from exc
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def _find(self, identifier: str) -> tuple[Path, dict[str, Any]]:
        if not isinstance(identifier, str) or not identifier:
            raise FileCustodyValidationError("Credential reference is required.")
        if identifier.startswith("cred_"):
            path = self._record_path(identifier)
            if path.exists():
                return path, self._read(path)
        for path in self._paths():
            record = self._read(path)
            if record.get("token_id") == identifier:
                return path, record
        raise FileCustodyNotFoundError("Credential reference was not found.")

    def _find_idempotency(self, key_hash: str):
        for path in self._paths():
            record = self._read(path)
            if record.get("store_idempotency_key_hash") == key_hash:
                return record
        return None

    @staticmethod
    def _reference(record: Mapping[str, Any]) -> CredentialReference:
        status = str(record.get("status") or ACTIVE)
        if status == ACTIVE and _is_expired(record.get("expires_at")):
            status = EXPIRED
        return CredentialReference(
            credential_id=str(record["credential_id"]),
            token_id=str(record["token_id"]),
            mask=MASK,
            version=int(record.get("version") or 1),
            expires_at=record.get("expires_at"),
            status=status,
            operation_id_hash=str(record.get("operation_id_hash") or ""),
        )

    def store(
        self,
        credentials: Mapping[str, Any],
        *,
        version: int = 1,
        expires_at: Any = None,
        idempotency_key: str | None = None,
        operation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = _safe_values(credentials)
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise FileCustodyValidationError("Credential version must be positive.")
        key_hash = _operation_hash(idempotency_key) if idempotency_key else ""
        payload_hash = _digest(values)
        with self._lock, _process_lock(self.path / ".lock"):
            if key_hash:
                existing = self._find_idempotency(key_hash)
                if existing:
                    if existing.get("payload_hash") != payload_hash:
                        raise FileCustodyIdempotencyConflict("Idempotency key was already used.")
                    return self._reference(existing)
            credential_id = f"cred_{uuid.uuid4().hex}"
            record = {
                "credential_id": credential_id,
                "token_id": f"tok_{uuid.uuid4().hex}",
                "version": version,
                "expires_at": _expiry(expires_at),
                "status": ACTIVE,
                "operation_id_hash": _operation_hash(operation_id or uuid.uuid4().hex),
                "store_idempotency_key_hash": key_hash,
                "payload_hash": payload_hash,
                "metadata": copy.deepcopy(dict(metadata or {})),
                "credentials": values,
            }
            self._write(credential_id, record)
            return self._reference(record)

    def rotate(
        self,
        identifier: str,
        credentials: Mapping[str, Any],
        *,
        expected_version: int,
        expires_at: Any = None,
        idempotency_key: str | None = None,
        operation_id: str | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        values = _safe_values(credentials)
        key_hash = _operation_hash(idempotency_key) if idempotency_key else ""
        payload_hash = _digest(values)
        with self._lock, _process_lock(self.path / ".lock"):
            _, record = self._find(identifier)
            if record.get("status") == REVOKED:
                raise FileCustodyRevokedError("Credential reference has been revoked.")
            if key_hash and record.get("rotate_idempotency_key_hash") == key_hash:
                if record.get("rotate_payload_hash") != payload_hash:
                    raise FileCustodyIdempotencyConflict("Idempotency key was already used.")
                return self._reference(record)
            if int(record.get("version") or 1) != expected_version:
                raise FileCustodyVersionConflict("Credential version has changed.")
            record.update(
                {
                    "token_id": f"tok_{uuid.uuid4().hex}",
                    "version": expected_version + 1,
                    "expires_at": _expiry(expires_at) if expires_at is not None else record.get("expires_at"),
                    "status": ACTIVE,
                    "operation_id_hash": _operation_hash(operation_id or uuid.uuid4().hex),
                    "rotate_idempotency_key_hash": key_hash,
                    "rotate_payload_hash": payload_hash,
                    "metadata": copy.deepcopy(dict(metadata or record.get("metadata") or {})),
                    "credentials": values,
                }
            )
            self._write(str(record["credential_id"]), record)
            return self._reference(record)

    def revoke(self, identifier: str, *, operation_id: str | None = None) -> dict[str, Any]:
        with self._lock, _process_lock(self.path / ".lock"):
            _, record = self._find(identifier)
            if record.get("status") != REVOKED:
                record.update(
                    {
                        "status": REVOKED,
                        "operation_id_hash": _operation_hash(operation_id or uuid.uuid4().hex),
                        "credentials": {},
                    }
                )
                self._write(str(record["credential_id"]), record)
            return self._reference(record)

    def get_reference(self, identifier: str) -> dict[str, Any]:
        with self._lock:
            _, record = self._find(identifier)
            return self._reference(record)

    def _resolve_credentials(self, identifier: str, *, allow_expired: bool = False) -> dict[str, Any]:
        with self._lock:
            _, record = self._find(identifier)
            reference = self._reference(record)
            if reference["status"] == REVOKED:
                raise FileCustodyRevokedError("Credential reference has been revoked.")
            if reference["status"] == EXPIRED and not allow_expired:
                raise FileCustodyExpiredError("Credential reference has expired.")
            return copy.deepcopy(dict(record.get("credentials") or {}))
