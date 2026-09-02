"""Independent HTTPS credential-custody WSGI sidecar.

The SaaS application talks to this process over an approved HTTPS endpoint.
The sidecar owns a dedicated 0700 directory and stores each credential record
with Fernet authenticated encryption.  The existing :class:`FileCredentialStore`
remains available to local synthetic tests; this module never uses its plain
JSON record format for the default sidecar application.

Run the WSGI object behind a TLS-terminating, private-network listener, for
example ``gunicorn apps.integrations.custody_service:application``.  The
sidecar itself has no Django/database dependency and exposes only the small
contract consumed by ``HttpCustodyBackend``.
"""

from __future__ import annotations

import copy
import hmac
import json
import os
from pathlib import Path
import stat
import urllib.parse
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken

from .file_custody import (
    FileCredentialStore,
    FileCustodyError,
    _canonical_json,
)


MAX_REQUEST_BYTES = 64 * 1024
MAX_SECRET_FILE_BYTES = 4096
HEALTH_PATH = "/healthz"

_SECRET_KEYS = {
    "secret",
    "app_secret",
    "partner_key",
    "signing_secret",
    "webhook_secret",
    "api_key",
    "api_secret",
    "access_token",
    "refresh_token",
    "private_key",
}
_SECRET_NAME_PARTS = {
    "secret",
    "token",
    "password",
    "cookie",
    "private_key",
    "credential",
    "authorization",
    "bearer",
}


class CustodyServiceConfigurationError(Exception):
    """A non-sensitive configuration failure that must fail closed."""


def _read_secret_file(path, *, name, read_only=False, max_bytes=MAX_SECRET_FILE_BYTES):
    """Read a mounted secret file without following symlinks.

    ``read_only`` is used for the Fernet key.  On POSIX only owner-readable
    0400 is accepted for that file.  The bearer token additionally accepts the
    conventional owner-only 0600 mount because a secret manager may create it
    with that mode before handing it to the sidecar.
    """
    raw_path = str(path or "").strip()
    candidate = Path(raw_path).expanduser()
    if not raw_path or not candidate.is_absolute():
        raise CustodyServiceConfigurationError(f"{name} must be an absolute file path.")
    try:
        link_stat = candidate.lstat()
    except OSError:
        raise CustodyServiceConfigurationError(f"{name} is unavailable.") from None
    if stat.S_ISLNK(link_stat.st_mode) or not stat.S_ISREG(link_stat.st_mode):
        raise CustodyServiceConfigurationError(f"{name} is unavailable.")
    if os.name != "nt":
        mode = stat.S_IMODE(link_stat.st_mode)
        if mode & 0o077 or mode & 0o111 or not mode & 0o400:
            raise CustodyServiceConfigurationError(f"{name} permissions are unsafe.")
        if read_only and mode != 0o400:
            raise CustodyServiceConfigurationError(f"{name} permissions are unsafe.")
        if not read_only and mode not in {0o400, 0o600}:
            raise CustodyServiceConfigurationError(f"{name} permissions are unsafe.")
    descriptor = None
    try:
        flags = os.O_RDONLY
        no_follow = getattr(os, "O_NOFOLLOW", 0)
        if no_follow:
            flags |= no_follow
        descriptor = os.open(str(candidate), flags)
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise CustodyServiceConfigurationError(f"{name} is unavailable.")
        if no_follow and (
            opened_stat.st_dev != link_stat.st_dev or opened_stat.st_ino != link_stat.st_ino
        ):
            raise CustodyServiceConfigurationError(f"{name} is unavailable.")
        with os.fdopen(descriptor, "rb") as handle:
            descriptor = None
            data = handle.read(max_bytes + 1)
    except CustodyServiceConfigurationError:
        raise
    except (OSError, UnicodeError):
        raise CustodyServiceConfigurationError(f"{name} is unavailable.") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
    if len(data) > max_bytes:
        raise CustodyServiceConfigurationError(f"{name} is unavailable.")
    try:
        value = data.decode("utf-8").strip()
    except UnicodeDecodeError:
        raise CustodyServiceConfigurationError(f"{name} is unavailable.") from None
    if not value:
        raise CustodyServiceConfigurationError(f"{name} is unavailable.")
    return value


def _load_fernet_key(path):
    value = _read_secret_file(path, name="CUSTODY_SERVICE_KEY_FILE", read_only=True)
    try:
        return Fernet(value.encode("ascii"))
    except (ValueError, TypeError, UnicodeEncodeError):
        raise CustodyServiceConfigurationError("CUSTODY_SERVICE_KEY_FILE is invalid.") from None


class EncryptedFileCredentialStore(FileCredentialStore):
    """FileCredentialStore-compatible store with encrypted record payloads."""

    _ENCRYPTED_FIELD = "credentials_encrypted"
    _ALGORITHM = "fernet-v1"

    def __init__(self, path, key_file):
        storage_path = Path(str(path or "").strip()).expanduser()
        if not str(path or "").strip() or not storage_path.is_absolute():
            raise CustodyServiceConfigurationError("CUSTODY_SERVICE_STORAGE_PATH must be an absolute path.")
        self._fernet = _load_fernet_key(key_file)
        super().__init__(storage_path)
        if os.name != "nt":
            try:
                if stat.S_IMODE(self.path.stat().st_mode) != 0o700:
                    raise FileCustodyError("Credential custody directory permissions are unsafe.")
            except OSError:
                raise FileCustodyError("Credential custody directory is unavailable.") from None

    @staticmethod
    def _encode_values(values):
        return _canonical_json(values)

    def _encrypt_values(self, values):
        ciphertext = self._fernet.encrypt(self._encode_values(values)).decode("ascii")
        return {"algorithm": self._ALGORITHM, "ciphertext": ciphertext}

    def _decrypt_values(self, encrypted):
        if not isinstance(encrypted, Mapping):
            raise FileCustodyError("Credential custody record is invalid.")
        if encrypted.get("algorithm") != self._ALGORITHM:
            raise FileCustodyError("Credential custody record is invalid.")
        ciphertext = encrypted.get("ciphertext")
        if not isinstance(ciphertext, str) or not ciphertext or len(ciphertext) > 2 * 1024 * 1024:
            raise FileCustodyError("Credential custody record is invalid.")
        try:
            decoded = self._fernet.decrypt(ciphertext.encode("ascii"))
            values = json.loads(decoded.decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, UnicodeEncodeError, ValueError, TypeError, json.JSONDecodeError):
            raise FileCustodyError("Credential custody record is unavailable.") from None
        if not isinstance(values, dict):
            raise FileCustodyError("Credential custody record is invalid.")
        return values

    def _read(self, path):
        try:
            record_stat = path.lstat()
        except OSError:
            raise FileCustodyError("Credential custody record is unavailable.") from None
        if stat.S_ISLNK(record_stat.st_mode) or not stat.S_ISREG(record_stat.st_mode):
            raise FileCustodyError("Credential custody record is invalid.")
        if os.name != "nt" and stat.S_IMODE(record_stat.st_mode) != 0o600:
            raise FileCustodyError("Credential custody record permissions are unsafe.")
        record = super()._read(path)
        encrypted = record.get(self._ENCRYPTED_FIELD)
        # Plain ``credentials`` records are deliberately not accepted by the
        # production sidecar, even though FileCredentialStore still supports
        # them for local synthetic/test compatibility.
        if encrypted is None:
            raise FileCustodyError("Credential custody record is invalid.")
        record["credentials"] = self._decrypt_values(encrypted)
        return record

    def _write(self, credential_id, record):
        safe_record = copy.deepcopy(dict(record))
        values = safe_record.pop("credentials", None)
        if not isinstance(values, dict):
            raise FileCustodyError("Credential custody record is invalid.")
        safe_record[self._ENCRYPTED_FIELD] = self._encrypt_values(values)
        super()._write(credential_id, safe_record)


class EncryptedFileCustodyBackend:
    """Small custody adapter with the same contract as FileCustodyBackend."""

    def __init__(self, path, key_file):
        self._store = EncryptedFileCredentialStore(path, key_file)

    @staticmethod
    def _result(reference, *, previous_reference_status="not_required"):
        return {
            "credential_id": reference["credential_id"],
            "token_id": reference["token_id"],
            "credential_mask": {"configured": "********"},
            "expires_at": reference.get("expires_at"),
            "reference_version": reference["version"],
            "operation_id_hash": reference.get("operation_id_hash") or "",
            "previous_reference_status": previous_reference_status,
        }

    def _values(self, identifier, *, allow_expired=False):
        try:
            return self._store._resolve_credentials(identifier, allow_expired=allow_expired)
        except FileCustodyError:
            raise

    @staticmethod
    def _metadata(payload):
        metadata = payload.pop("metadata", {}) or {}
        if not isinstance(metadata, Mapping):
            raise FileCustodyError("Credential metadata is invalid.")
        metadata = dict(metadata)
        for key in metadata:
            normalized = str(key).strip().lower()
            if normalized in _SECRET_KEYS or any(part in normalized for part in _SECRET_NAME_PARTS):
                raise FileCustodyError("Credential metadata is invalid.")
        return metadata

    def store_secrets(self, **kwargs):
        payload = dict(kwargs)
        try:
            metadata = self._metadata(payload)
            credential_type = str(payload.pop("credential_type", "") or "")
            if credential_type:
                metadata["credential_type"] = credential_type
            reference_version = int(payload.pop("reference_version", 1))
            expires_at = payload.pop("expires_at", None)
            idempotency_key = payload.pop("idempotency_key", None)
            operation_id = payload.pop("operation_id", None)
            credentials = {key: value for key, value in payload.items() if key in _SECRET_KEYS}
            reference = self._store.store(
                credentials,
                version=reference_version,
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                metadata=metadata,
            )
            return self._result(reference)
        finally:
            payload.clear()
            kwargs.clear()

    def rotate_secrets(self, **kwargs):
        payload = dict(kwargs)
        try:
            credential_id = str(payload.pop("previous_credential_id", "") or "")
            token_id = str(payload.pop("previous_token_id", "") or "")
            current = self._store.get_reference(credential_id or token_id)
            if credential_id and token_id and current["token_id"] != token_id:
                raise FileCustodyError("Credential and token references do not match.")
            metadata = self._metadata(payload)
            credential_type = str(payload.pop("credential_type", "") or "")
            if credential_type:
                metadata["credential_type"] = credential_type
            requested_version = int(payload.pop("reference_version", current["version"] + 1))
            if requested_version != current["version"] + 1:
                raise FileCustodyError("Credential version has changed.")
            expires_at = payload.pop("expires_at", None)
            idempotency_key = payload.pop("idempotency_key", None)
            operation_id = payload.pop("operation_id", None)
            credentials = self._values(credential_id or token_id, allow_expired=True)
            credentials.update({key: value for key, value in payload.items() if key in _SECRET_KEYS})
            reference = self._store.rotate(
                credential_id or token_id,
                credentials,
                expected_version=current["version"],
                expires_at=expires_at,
                idempotency_key=idempotency_key,
                operation_id=operation_id,
                metadata=metadata,
            )
            return self._result(reference, previous_reference_status="revoked")
        finally:
            payload.clear()
            kwargs.clear()

    def retrieve_secret(self, reference_id):
        values = self._values(reference_id)
        for key in ("app_secret", "partner_key", "api_secret", "signing_secret", "secret", "private_key"):
            value = values.get(key)
            if isinstance(value, str) and value:
                return value
        raise FileCustodyError("Credential reference does not contain an application secret.")

    def retrieve_access_token(self, token_id):
        value = self._values(token_id).get("access_token")
        if not isinstance(value, str) or not value:
            raise FileCustodyError("Credential reference does not contain an access token.")
        return value

    def retrieve_refresh_token(self, token_id):
        value = self._values(token_id, allow_expired=True).get("refresh_token")
        if not isinstance(value, str) or not value:
            raise FileCustodyError("Credential reference does not contain a refresh token.")
        return value

    def revoke(self, credential_id, token_id):
        if not credential_id and not token_id:
            return {"status": "not_required", "error_code": "", "operation_id_hash": ""}
        try:
            current = self._store.get_reference(credential_id or token_id)
            if credential_id and token_id and current["token_id"] != token_id:
                raise FileCustodyError("Credential and token references do not match.")
            reference = self._store.revoke(credential_id or token_id)
            return {
                "status": reference["status"],
                "error_code": "",
                "operation_id_hash": reference.get("operation_id_hash") or "",
            }
        except FileCustodyError:
            return {"status": "failed", "error_code": "CUSTODY_REVOCATION_FAILED", "operation_id_hash": ""}


class CustodyService:
    """Bearer-authenticated WSGI application for the custody contract."""

    def __init__(
        self,
        *,
        store=None,
        auth_token=None,
        auth_token_file=None,
        storage_path=None,
        encryption_key_file=None,
        max_request_bytes=MAX_REQUEST_BYTES,
    ):
        if store is None:
            storage_path = storage_path or os.getenv("CUSTODY_SERVICE_STORAGE_PATH", "")
            encryption_key_file = encryption_key_file or os.getenv("CUSTODY_SERVICE_KEY_FILE", "")
            if not storage_path or not encryption_key_file:
                raise CustodyServiceConfigurationError("Custody service storage is not configured.")
            store = EncryptedFileCustodyBackend(storage_path, encryption_key_file)
        if auth_token_file:
            auth_token = _read_secret_file(
                auth_token_file,
                name="CUSTODY_SERVICE_TOKEN_FILE",
                read_only=False,
            )
        elif auth_token is None:
            token_file = os.getenv("CUSTODY_SERVICE_TOKEN_FILE", "") or os.getenv(
                "LIVE_CUSTODY_SERVICE_TOKEN_FILE", ""
            )
            if token_file:
                auth_token = _read_secret_file(token_file, name="CUSTODY_SERVICE_TOKEN_FILE")
            else:
                auth_token = os.getenv("CUSTODY_SERVICE_TOKEN", "") or os.getenv(
                    "LIVE_CUSTODY_SERVICE_TOKEN", ""
                )
        self._store = store
        self._auth_token = str(auth_token or "").strip()
        if not self._auth_token:
            raise CustodyServiceConfigurationError("Custody service authentication is not configured.")
        try:
            self._max_request_bytes = int(max_request_bytes)
        except (TypeError, ValueError):
            raise CustodyServiceConfigurationError("Custody service request limit is invalid.") from None
        if not 1024 <= self._max_request_bytes <= 1024 * 1024:
            raise CustodyServiceConfigurationError("Custody service request limit is invalid.")

    @staticmethod
    def _response(start_response, status_code, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        reason = {
            200: "OK",
            400: "Bad Request",
            401: "Unauthorized",
            404: "Not Found",
            405: "Method Not Allowed",
            413: "Payload Too Large",
            415: "Unsupported Media Type",
            503: "Service Unavailable",
        }.get(status_code, "Error")
        start_response(
            f"{status_code} {reason}",
            [
                ("Content-Type", "application/json; charset=utf-8"),
                ("Content-Length", str(len(body))),
                ("Cache-Control", "no-store"),
            ],
        )
        return [body]

    def _authorized(self, environ):
        header = str(environ.get("HTTP_AUTHORIZATION", ""))
        scheme, separator, candidate = header.partition(" ")
        candidate = candidate.strip() if separator and scheme.lower() == "bearer" else ""
        matches = hmac.compare_digest(candidate, self._auth_token)
        return bool(candidate) and matches

    def _read_json(self, environ):
        content_type = str(environ.get("CONTENT_TYPE", "")).split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise ValueError("json content type required")
        content_length = str(environ.get("CONTENT_LENGTH", "")).strip()
        if content_length:
            try:
                declared = int(content_length)
            except ValueError:
                raise ValueError("invalid content length") from None
            if declared < 0 or declared > self._max_request_bytes:
                raise OverflowError
        else:
            declared = self._max_request_bytes + 1
        stream = environ.get("wsgi.input")
        if stream is None:
            raise ValueError("request body is required")
        body = stream.read(min(declared, self._max_request_bytes + 1))
        if len(body) > self._max_request_bytes:
            raise OverflowError
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, TypeError, ValueError):
            raise ValueError("invalid json") from None
        if not isinstance(payload, dict):
            raise ValueError("json object required")
        return payload

    @staticmethod
    def _required_text(payload, key):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            raise ValueError("required field missing")
        return value.strip()

    def _dispatch(self, path, payload):
        if path == "/tokens":
            return self._store.store_secrets(**payload)
        if path == "/tokens/rotate":
            return self._store.rotate_secrets(**payload)
        if path == "/tokens/resolve":
            token_id = self._required_text(payload, "token_id")
            kind = self._required_text(payload, "kind").lower()
            if kind == "access":
                value = self._store.retrieve_access_token(token_id)
            elif kind == "refresh":
                value = self._store.retrieve_refresh_token(token_id)
            else:
                raise ValueError("token kind is invalid")
            return {"value": value}
        if path == "/secrets/resolve":
            reference_id = self._required_text(payload, "reference_id")
            return {"value": self._store.retrieve_secret(reference_id)}
        if path == "/tokens/revoke":
            credential_id = str(payload.get("credential_id") or "").strip()
            token_id = str(payload.get("token_id") or "").strip()
            if not credential_id and not token_id:
                raise ValueError("reference is required")
            return self._store.revoke(credential_id, token_id)
        raise LookupError

    def __call__(self, environ, start_response):
        method = str(environ.get("REQUEST_METHOD", "GET")).upper()
        path = urllib.parse.urlsplit(str(environ.get("PATH_INFO", ""))).path or "/"
        if path == HEALTH_PATH:
            if method != "GET":
                return self._response(start_response, 405, {"error_code": "METHOD_NOT_ALLOWED", "detail": "Method not allowed."})
            # Deliberately reveal no path, host, key, token, or backend detail.
            return self._response(start_response, 200, {"status": "ok"})
        if path not in {"/tokens", "/tokens/rotate", "/tokens/resolve", "/tokens/revoke", "/secrets/resolve"}:
            return self._response(start_response, 404, {"error_code": "NOT_FOUND", "detail": "Not found."})
        if method != "POST":
            return self._response(start_response, 405, {"error_code": "METHOD_NOT_ALLOWED", "detail": "Method not allowed."})
        if not self._authorized(environ):
            return self._response(start_response, 401, {"error_code": "CUSTODY_AUTHENTICATION_FAILED", "detail": "Request is not authorized."})
        try:
            payload = self._read_json(environ)
            result = self._dispatch(path, payload)
            if not isinstance(result, dict):
                raise FileCustodyError("invalid custody result")
            return self._response(start_response, 200, result)
        except OverflowError:
            return self._response(start_response, 413, {"error_code": "REQUEST_TOO_LARGE", "detail": "Request is too large."})
        except ValueError:
            return self._response(start_response, 400, {"error_code": "INVALID_REQUEST", "detail": "Invalid custody request."})
        except (FileCustodyError, OSError, InvalidToken):
            return self._response(start_response, 400, {"error_code": "CUSTODY_OPERATION_FAILED", "detail": "Custody operation failed."})
        except Exception:
            # Do not serialize exception text: it could contain a secret from
            # a provider or a filesystem path from the sidecar boundary.
            return self._response(start_response, 503, {"error_code": "CUSTODY_UNAVAILABLE", "detail": "Custody service unavailable."})


class _LazyApplication:
    """Keep importing the module safe when the sidecar is not configured."""

    def __init__(self):
        self._service = None
        self._load_failed = False

    def __call__(self, environ, start_response):
        if self._service is None and not self._load_failed:
            try:
                self._service = create_application()
            except Exception:
                self._load_failed = True
        if self._service is None:
            return CustodyService._response(
                start_response,
                503,
                {"error_code": "CUSTODY_UNAVAILABLE", "detail": "Custody service unavailable."},
            )
        return self._service(environ, start_response)


def create_application(**kwargs):
    """Build a configured sidecar application for tests or WSGI runners."""
    return CustodyService(**kwargs)


create_app = create_application


application = _LazyApplication()
app = application


def serve_https(wsgi_application=None, *, host=None, port=None, cert_file=None, private_key_file=None):
    """Serve the sidecar with TLS when launched directly.

    Production may instead terminate TLS in a private reverse proxy before
    gunicorn, but the direct launcher refuses to start without a certificate
    and private key so it cannot accidentally expose bearer-authenticated
    endpoints over clear-text HTTP.
    """
    import ssl
    from wsgiref.simple_server import make_server

    cert_file = cert_file or os.getenv("CUSTODY_SERVICE_TLS_CERT_FILE", "")
    private_key_file = private_key_file or os.getenv("CUSTODY_SERVICE_TLS_KEY_FILE", "")
    if not cert_file or not private_key_file:
        raise CustodyServiceConfigurationError("TLS certificate and private key are required.")

    def checked_tls_path(path, name, *, private=False):
        candidate = Path(str(path).strip()).expanduser()
        if not candidate.is_absolute():
            raise CustodyServiceConfigurationError(f"{name} must be an absolute file path.")
        try:
            file_stat = candidate.lstat()
        except OSError:
            raise CustodyServiceConfigurationError(f"{name} is unavailable.") from None
        if stat.S_ISLNK(file_stat.st_mode) or not stat.S_ISREG(file_stat.st_mode):
            raise CustodyServiceConfigurationError(f"{name} is unavailable.")
        if private and os.name != "nt" and stat.S_IMODE(file_stat.st_mode) != 0o400:
            raise CustodyServiceConfigurationError(f"{name} permissions are unsafe.")
        return str(candidate)

    cert_path = checked_tls_path(cert_file, "CUSTODY_SERVICE_TLS_CERT_FILE")
    key_path = checked_tls_path(private_key_file, "CUSTODY_SERVICE_TLS_KEY_FILE", private=True)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    server = make_server(host or os.getenv("CUSTODY_SERVICE_BIND_HOST", "127.0.0.1"), int(port or os.getenv("CUSTODY_SERVICE_BIND_PORT", "8443")), wsgi_application or application)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    server.serve_forever()


if __name__ == "__main__":  # pragma: no cover - deployment convenience only
    serve_https()
