"""Local credential custody.

This module is deliberately independent from the integration database.  The
database stores references (``credential_id``/``token_id`` and lifecycle
metadata) while this service stores the value in a separate, operator-owned
directory.  It is intentionally *not* an encryption provider and does not
depend on a cloud secret manager.  Deployments should put the custody
directory on a dedicated volume with a service account that is not allowed to
read the application database.

Only the local custody process should be given read access to the files.  The
public methods below never return a secret, token, or reversible ciphertext;
they return :class:`CredentialReference` objects containing metadata only.
"""

from __future__ import annotations

import contextlib
import copy
import errno
import hashlib
import json
import logging
import os
import tempfile
import threading
import uuid
from collections.abc import Mapping
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator


LOGGER = logging.getLogger(__name__)

_DEFAULT_MASK = "***"
_ACTIVE = "active"
_REVOKED = "revoked"
_EXPIRED = "expired"
_STATUS_VALUES = {_ACTIVE, _REVOKED, _EXPIRED}
_SENSITIVE_NAMES = {
    "secret",
    "secrets",
    "password",
    "passwd",
    "api_key",
    "api_secret",
    "access_token",
    "refresh_token",
    "token",
    "client_secret",
    "private_key",
}


class CredentialCustodyError(Exception):
    """Base error for custody operations.

    Error messages are static or metadata-only by design.  Never include an
    input credential in an exception message.
    """


class CredentialValidationError(CredentialCustodyError, ValueError):
    pass


class CredentialNotFoundError(CredentialCustodyError, KeyError):
    pass


class CredentialRevokedError(CredentialCustodyError):
    pass


class IdempotencyConflictError(CredentialCustodyError):
    pass


class VersionConflictError(CredentialCustodyError):
    pass


# Short aliases are useful to callers that do not want to depend on the
# implementation's verbose exception names.
CredentialNotFound = CredentialNotFoundError
IdempotencyConflict = IdempotencyConflictError
VersionConflict = VersionConflictError


class CredentialReference(dict):
    """Safe, mapping-compatible credential reference.

    The class subclasses ``dict`` so API views can return it directly while
    callers may also use ``reference.credential_id``.  Its key set is kept
    deliberately small.  In particular, there is no suffix, length, secret,
    access token, refresh token, or encrypted value in a reference.
    """

    _FIELDS = (
        "credential_id",
        "token_id",
        "mask",
        "version",
        "expires_at",
        "status",
        "operation_id_hash",
    )

    def __init__(
        self,
        credential_id: str,
        token_id: str,
        mask: str = _DEFAULT_MASK,
        version: int = 1,
        expires_at: str | None = None,
        status: str = _ACTIVE,
        operation_id_hash: str | None = None,
    ) -> None:
        if not credential_id or not token_id:
            raise CredentialValidationError("Credential reference identifiers are required.")
        if status not in _STATUS_VALUES:
            raise CredentialValidationError("Unsupported credential status.")
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            raise CredentialValidationError("Credential version must be an integer.") from exc
        if version < 1:
            raise CredentialValidationError("Credential version must be positive.")
        # Never accept a caller-provided mask that could contain a secret
        # suffix.  Custody references intentionally expose a generic mask.
        safe_mask = _DEFAULT_MASK if not isinstance(mask, str) else _DEFAULT_MASK
        super().__init__(
            credential_id=str(credential_id),
            token_id=str(token_id),
            mask=safe_mask,
            version=version,
            expires_at=_normalise_expiry(expires_at),
            status=status,
            operation_id_hash=str(operation_id_hash) if operation_id_hash else None,
        )

    def __getattr__(self, name: str) -> Any:
        if name in self._FIELDS:
            return self[name]
        raise AttributeError(name)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._FIELDS:
            raise AttributeError("Credential references are immutable.")
        super().__setattr__(name, value)

    def to_dict(self) -> dict[str, Any]:
        return dict(self)

    # A stable representation helps keep accidental logs safe.  The default
    # dict repr is safe too, but this makes the intent explicit in audits.
    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        values = ", ".join(f"{key}={self[key]!r}" for key in self._FIELDS)
        return f"CredentialReference({values})"


def _normalise_expiry(value: Any) -> str | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        current = value
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Parse only to validate; retain the caller's precision/format where
        # possible so callers can compare metadata without surprises.
        try:
            datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise CredentialValidationError("expires_at must be an ISO-8601 timestamp.") from exc
        return text
    raise CredentialValidationError("expires_at must be an ISO-8601 timestamp.")


def _expiry_is_past(value: str | None, *, now: datetime | None = None) -> bool:
    if not value:
        return False
    try:
        expiry = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        # Values are validated on write.  A malformed legacy file should not
        # make read-only reference access leak data or fail unpredictably.
        return False
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return expiry <= current.astimezone(timezone.utc)


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise CredentialValidationError("Credentials must be JSON-compatible.") from exc


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _operation_hash(operation_id: str) -> str:
    # Prefixing avoids exposing raw idempotency keys even if a caller happens
    # to use a short or guessable value.
    return hashlib.sha256(("credential-custody:" + operation_id).encode("utf-8")).hexdigest()


def _safe_credentials(value: Any) -> dict[str, Any]:
    """Normalise a caller value without retaining references to mutable data."""
    if isinstance(value, Mapping):
        if not value:
            raise CredentialValidationError("At least one credential value is required.")
        try:
            result = copy.deepcopy(dict(value))
        except Exception as exc:  # pragma: no cover - defensive for custom mappings
            raise CredentialValidationError("Credentials could not be copied safely.") from exc
        # Empty names/values are almost always an accidental API call.  Do
        # not include the offending key/value in the error.
        if any(not isinstance(key, str) or not key.strip() for key in result):
            raise CredentialValidationError("Credential names must be non-empty strings.")
        if any(value in (None, "") for value in result.values()):
            raise CredentialValidationError("Credential values must be non-empty.")
        _canonical_json(result)
        return result
    if isinstance(value, str) and value:
        # A single opaque token is accepted for convenience.  It is kept under
        # an internal name and never appears in any returned reference.
        return {"value": value}
    raise CredentialValidationError("Credentials must be a non-empty mapping.")


def _extract_credentials(value: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Accept common service call shapes while keeping one safe contract."""
    if value is not None:
        return _safe_credentials(value)
    for key in ("credentials", "secret", "secrets", "credential", "value"):
        if key in kwargs:
            return _safe_credentials(kwargs[key])
    # Convenience for callers that provide sensitive keyword arguments.
    selected = {key: kwargs[key] for key in tuple(kwargs) if key in _SENSITIVE_NAMES and kwargs[key] not in (None, "")}
    if selected:
        return _safe_credentials(selected)
    raise CredentialValidationError("Credentials are required.")


def _resolve_path(path: str | os.PathLike[str] | None) -> Path:
    if path is not None:
        return Path(path).expanduser()
    env_path = os.getenv("CREDENTIAL_CUSTODY_PATH")
    if env_path:
        return Path(env_path).expanduser()
    # Importing Django settings is optional; this keeps pure-Python consumers
    # and command-line health checks independent from Django setup.
    try:
        from django.conf import settings  # type: ignore

        configured = getattr(settings, "CREDENTIAL_CUSTODY_PATH", None)
        if configured:
            return Path(configured).expanduser()
    except Exception:
        pass
    # Keep the fallback outside the repository.  Production settings should
    # always set CREDENTIAL_CUSTODY_PATH to a persistent, restricted volume;
    # this fallback is for local smoke tests and command-line probes only.
    return Path(tempfile.gettempdir()) / "saas-collab-system-credential-custody"


_LOCAL_LOCKS: dict[str, threading.RLock] = {}
_LOCAL_LOCKS_GUARD = threading.Lock()


def _local_lock(path: Path) -> threading.RLock:
    key = str(path.resolve())
    with _LOCAL_LOCKS_GUARD:
        lock = _LOCAL_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCAL_LOCKS[key] = lock
        return lock


@contextlib.contextmanager
def _process_lock(lock_path: Path) -> Iterator[None]:
    """Best-effort cross-process lock with a portable in-process fallback."""
    handle = None
    try:
        handle = lock_path.open("a+b")
        try:
            import fcntl  # type: ignore

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        except (ImportError, OSError):
            try:
                import msvcrt  # type: ignore

                # Lock one byte.  The lock file is never used for data.
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
            except (ImportError, OSError):
                pass
        yield
    finally:
        if handle is not None:
            try:
                try:
                    import fcntl  # type: ignore

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except (ImportError, OSError):
                    pass
                handle.close()
            except OSError:
                pass


class FileCredentialStore:
    """Permission-restricted, atomic local credential store.

    Records are separate JSON files to make the custody boundary visible and
    backup/restore operations explicit.  JSON is not encrypted: file-system
    permissions and process isolation are the security boundary.  A production
    deployment should put this directory on a restricted volume.
    """

    def __init__(
        self,
        path: str | os.PathLike[str] | None = None,
        *,
        storage_path: str | os.PathLike[str] | None = None,
        root: str | os.PathLike[str] | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        # ``storage_path``/``root`` are accepted as explicit aliases for
        # adapters and tests; there is still exactly one on-disk boundary.
        self.path = _resolve_path(path or storage_path or root)
        self.logger = logger or LOGGER
        self._lock = _local_lock(self.path)
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        try:
            self.path.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path, 0o700)
            except OSError:
                # Windows ACLs do not map cleanly to chmod.  The process lock
                # and explicit deployment ACL remain the boundary there.
                pass
        except OSError as exc:
            raise CredentialCustodyError("Credential custody storage is unavailable.") from exc
        if not self.path.is_dir():
            raise CredentialCustodyError("Credential custody storage is unavailable.")

    def _record_path(self, credential_id: str) -> Path:
        if not credential_id or Path(credential_id).name != credential_id or credential_id in {".", ".."}:
            raise CredentialValidationError("Invalid credential identifier.")
        return self.path / f"{credential_id}.json"

    def _iter_record_paths(self) -> Iterator[Path]:
        try:
            yield from sorted(self.path.glob("*.json"))
        except OSError as exc:
            raise CredentialCustodyError("Credential custody storage is unavailable.") from exc

    def _read_record(self, path: Path) -> dict[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                record = json.load(handle)
        except (OSError, ValueError, TypeError) as exc:
            raise CredentialCustodyError("Credential custody record is unavailable.") from exc
        if not isinstance(record, dict) or not isinstance(record.get("credential_id"), str):
            raise CredentialCustodyError("Credential custody record is invalid.")
        return record

    def _write_record(self, credential_id: str, record: Mapping[str, Any]) -> None:
        destination = self._record_path(credential_id)
        payload = _canonical_json(dict(record))
        temporary_fd = None
        temporary_path: str | None = None
        try:
            temporary_fd, temporary_path = tempfile.mkstemp(prefix=".credential-", suffix=".tmp", dir=self.path)
            try:
                os.fchmod(temporary_fd, 0o600)
            except (AttributeError, OSError):
                pass
            with os.fdopen(temporary_fd, "wb") as handle:
                temporary_fd = None
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            try:
                os.chmod(destination, 0o600)
            except OSError:
                pass
            # fsync the directory when supported so a crash cannot leave a
            # stale index/record after os.replace succeeds.
            try:
                directory_fd = os.open(self.path, os.O_RDONLY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except (OSError, TypeError):
                pass
        except OSError as exc:
            raise CredentialCustodyError("Credential custody record could not be written.") from exc
        finally:
            if temporary_fd is not None:
                try:
                    os.close(temporary_fd)
                except OSError:
                    pass
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except OSError:
                    pass

    def _reference_from_record(self, record: Mapping[str, Any], *, now: datetime | None = None) -> CredentialReference:
        status = str(record.get("status") or _ACTIVE)
        expiry = _normalise_expiry(record.get("expires_at")) if record.get("expires_at") else None
        if status == _ACTIVE and _expiry_is_past(expiry, now=now):
            status = _EXPIRED
        return CredentialReference(
            credential_id=str(record.get("credential_id", "")),
            token_id=str(record.get("token_id", "")),
            mask=_DEFAULT_MASK,
            version=int(record.get("version", 1)),
            expires_at=expiry,
            status=status,
            operation_id_hash=record.get("operation_id_hash"),
        )

    def _find_by_idempotency(self, key_hash: str) -> tuple[Path, dict[str, Any]] | None:
        for path in self._iter_record_paths():
            try:
                record = self._read_record(path)
            except CredentialCustodyError:
                # Ignore unrelated/partially written files; the operation can
                # still proceed atomically and the broken record is not read.
                continue
            if record.get("idempotency_key_hash") == key_hash:
                return path, record
        return None

    def _find_record(self, identifier: str | Mapping[str, Any] | CredentialReference) -> tuple[Path, dict[str, Any]]:
        if isinstance(identifier, Mapping):
            identifier = identifier.get("credential_id") or identifier.get("token_id")
        if not identifier or not isinstance(identifier, str):
            raise CredentialValidationError("A credential identifier is required.")
        candidate = self._record_path(identifier)
        if candidate.exists():
            return candidate, self._read_record(candidate)
        # token_id is intentionally not used as a file name, so resolve it by
        # scanning metadata.  This is slower but avoids a second index that
        # could accidentally become a secret-bearing database.
        for path in self._iter_record_paths():
            try:
                record = self._read_record(path)
            except CredentialCustodyError:
                continue
            if record.get("token_id") == identifier:
                return path, record
        raise CredentialNotFoundError("Credential reference was not found.")

    def _idempotency_hash(self, idempotency_key: str | None) -> str | None:
        if idempotency_key is None:
            return None
        if not isinstance(idempotency_key, str) or not idempotency_key.strip():
            raise CredentialValidationError("idempotency_key must be a non-empty string.")
        return _operation_hash(idempotency_key.strip())

    def store(
        self,
        credentials: Any = None,
        *args: Any,
        credential_id: str | None = None,
        token_id: str | None = None,
        version: int | None = None,
        expires_at: Any = None,
        idempotency_key: str | None = None,
        operation_id: str | None = None,
        status: str = _ACTIVE,
        **kwargs: Any,
    ) -> CredentialReference:
        """Store a secret and return metadata-only reference.

        ``credentials`` may be a mapping or one opaque string.  Keyword
        aliases such as ``secret=`` and ``access_token=`` are accepted for
        integration adapters.  Positional arguments after the first are
        ignored only when they are ``None``; a non-empty extra argument is
        rejected to prevent accidental tenant/secret argument confusion.
        """
        if args:
            # Some adapters pass a tenant/provider scope before the mapping
            # (``store(tenant_id, credentials)``).  Scope is not persisted in
            # the custody record, so accept that shape without returning it.
            if credentials is not None and len(args) == 1 and isinstance(args[0], (Mapping, str)):
                if isinstance(credentials, str):
                    credentials = args[0]
                args = ()
            elif any(item is not None for item in args):
                raise CredentialValidationError("Unsupported positional credential arguments.")
        values = _extract_credentials(credentials, kwargs)
        if status not in {_ACTIVE, _EXPIRED}:
            raise CredentialValidationError("New credentials must be active.")
        if expires_at is None:
            expires_at = kwargs.pop("expiry", kwargs.pop("expires", None))
        expiry = _normalise_expiry(expires_at)
        if version is None:
            version = 1
        try:
            version = int(version)
        except (TypeError, ValueError) as exc:
            raise CredentialValidationError("Credential version must be an integer.") from exc
        if version < 1:
            raise CredentialValidationError("Credential version must be positive.")
        key_hash = self._idempotency_hash(idempotency_key)
        payload_hash = _fingerprint(values)
        operation = str(operation_id or uuid.uuid4().hex)
        operation_hash = _operation_hash(operation)
        with self._lock, _process_lock(self.path / ".lock"):
            if key_hash:
                existing = self._find_by_idempotency(key_hash)
                if existing:
                    _, record = existing
                    if record.get("payload_hash") != payload_hash:
                        raise IdempotencyConflictError("Idempotency key was already used for another credential.")
                    return self._reference_from_record(record)
            new_credential_id = credential_id or f"cred_{uuid.uuid4().hex}"
            if self._record_path(new_credential_id).exists():
                # Explicit IDs are useful for migrations but must be
                # idempotent and never overwrite another credential.
                raise IdempotencyConflictError("Credential identifier already exists.")
            new_token_id = token_id or f"tok_{uuid.uuid4().hex}"
            record = {
                "credential_id": str(new_credential_id),
                "token_id": str(new_token_id),
                "version": version,
                "expires_at": expiry,
                "status": status,
                "operation_id_hash": operation_hash,
                "idempotency_key_hash": key_hash,
                "payload_hash": payload_hash,
                # The value is confined to this file and never copied to a
                # model, audit log, exception, or returned reference.
                "credentials": values,
            }
            self._write_record(str(new_credential_id), record)
            self.logger.info(
                "credential_custody_store credential_id=%s token_id=%s version=%s",
                new_credential_id,
                new_token_id,
                version,
            )
            return self._reference_from_record(record)

    def rotate(
        self,
        identifier: str | Mapping[str, Any] | CredentialReference | None = None,
        credentials: Any = None,
        *args: Any,
        expected_version: int | None = None,
        version: int | None = None,
        expires_at: Any = None,
        idempotency_key: str | None = None,
        operation_id: str | None = None,
        **kwargs: Any,
    ) -> CredentialReference:
        """Replace a credential value and return the next safe reference."""
        if identifier is None:
            identifier = kwargs.pop("credential_id", None) or kwargs.pop("token_id", None)
        if credentials is None and args:
            credentials, *remaining = args
            if any(item is not None for item in remaining):
                raise CredentialValidationError("Unsupported positional credential arguments.")
        values = _extract_credentials(credentials, kwargs)
        key_hash = self._idempotency_hash(idempotency_key)
        payload_hash = _fingerprint(values)
        if expires_at is None:
            expires_at = kwargs.pop("expiry", kwargs.pop("expires", None))
        expiry = _normalise_expiry(expires_at)
        operation = str(operation_id or uuid.uuid4().hex)
        operation_hash = _operation_hash(operation)
        with self._lock, _process_lock(self.path / ".lock"):
            path, record = self._find_record(identifier)
            if record.get("status") == _REVOKED:
                raise CredentialRevokedError("Credential has been revoked.")
            if key_hash and record.get("rotate_idempotency_key_hash") == key_hash:
                if record.get("rotate_payload_hash") != payload_hash:
                    raise IdempotencyConflictError("Idempotency key was already used for another rotation.")
                return self._reference_from_record(record)
            current_version = int(record.get("version", 1))
            if expected_version is None and version is not None:
                expected_version = version
            if expected_version is not None:
                try:
                    expected_version = int(expected_version)
                except (TypeError, ValueError) as exc:
                    raise CredentialValidationError("expected_version must be an integer.") from exc
                if expected_version != current_version:
                    raise VersionConflictError("Credential version has changed.")
            next_version = current_version + 1
            record = dict(record)
            record.update(
                {
                    "token_id": f"tok_{uuid.uuid4().hex}",
                    "version": next_version,
                    "expires_at": expiry if expires_at is not None else record.get("expires_at"),
                    "status": _ACTIVE,
                    "operation_id_hash": operation_hash,
                    "rotate_idempotency_key_hash": key_hash,
                    "rotate_payload_hash": payload_hash,
                    "credentials": values,
                }
            )
            self._write_record(str(record["credential_id"]), record)
            self.logger.info(
                "credential_custody_rotate credential_id=%s token_id=%s version=%s",
                record["credential_id"],
                record["token_id"],
                next_version,
            )
            return self._reference_from_record(record)

    def revoke(
        self,
        identifier: str | Mapping[str, Any] | CredentialReference | None = None,
        *args: Any,
        idempotency_key: str | None = None,
        operation_id: str | None = None,
        **kwargs: Any,
    ) -> CredentialReference:
        """Revoke a credential and erase its value from local storage."""
        if identifier is None:
            identifier = kwargs.pop("credential_id", None) or kwargs.pop("token_id", None)
        if args and any(item is not None for item in args):
            raise CredentialValidationError("Unsupported positional revoke arguments.")
        key_hash = self._idempotency_hash(idempotency_key)
        operation = str(operation_id or uuid.uuid4().hex)
        operation_hash = _operation_hash(operation)
        with self._lock, _process_lock(self.path / ".lock"):
            path, record = self._find_record(identifier)
            if key_hash and record.get("revoke_idempotency_key_hash") == key_hash:
                return self._reference_from_record(record)
            record = dict(record)
            record.update(
                {
                    "status": _REVOKED,
                    "operation_id_hash": operation_hash,
                    "revoke_idempotency_key_hash": key_hash,
                    # Do not leave the old value behind after revocation.
                    "credentials": {},
                }
            )
            self._write_record(str(record["credential_id"]), record)
            self.logger.info(
                "credential_custody_revoke credential_id=%s token_id=%s version=%s",
                record["credential_id"],
                record["token_id"],
                record.get("version", 1),
            )
            return self._reference_from_record(record)

    def get_reference(
        self,
        identifier: str | Mapping[str, Any] | CredentialReference | None = None,
        *args: Any,
        **kwargs: Any,
    ) -> CredentialReference:
        """Read metadata only; this method never writes or returns a value."""
        if identifier is None:
            identifier = kwargs.get("credential_id") or kwargs.get("token_id")
        if kwargs.get("include_secret"):
            raise CredentialValidationError("Secret retrieval is not supported by custody references.")
        if args and any(item is not None for item in args):
            raise CredentialValidationError("Unsupported positional reference arguments.")
        with self._lock:
            _, record = self._find_record(identifier)
            return self._reference_from_record(record)

    # Explicitly named aliases make it difficult for adapters to accidentally
    # call a secret-returning method when they only need a reference.
    reference = get_reference
    get_reference_only = get_reference


class CredentialCustody(FileCredentialStore):
    """Service facade used by integrations and workers.

    Keeping this as a subclass preserves a tiny public surface and allows a
    process boundary to be introduced later without changing callers.
    """


LocalCredentialCustody = CredentialCustody
FileCredentialCustody = FileCredentialStore


__all__ = [
    "CredentialCustody",
    "LocalCredentialCustody",
    "FileCredentialStore",
    "FileCredentialCustody",
    "CredentialReference",
    "CredentialCustodyError",
    "CredentialValidationError",
    "CredentialNotFoundError",
    "CredentialNotFound",
    "CredentialRevokedError",
    "IdempotencyConflictError",
    "IdempotencyConflict",
    "VersionConflictError",
    "VersionConflict",
]
