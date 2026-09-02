"""Fail-closed client for the controlled pilot execution runner."""

import json
import os
import re
import ssl
import stat
import time
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings


MAX_SECRET_FILE_BYTES = 8192
MAX_SECRET_LENGTH = 4096
SAFE_SECRET_FILE_MODES = frozenset({0o400, 0o440, 0o600, 0o640})
RETRYABLE_HTTP_STATUSES = frozenset({408, 409, 429, 500, 502, 503, 504})
ALLOWED_METRICS = frozenset(
    {
        "p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent",
        "actual_rpo_minutes", "actual_rto_minutes", "metrics_source", "scope",
    }
)
ALLOWED_STATUSES = frozenset({"queued", "running", "succeeded", "failed", "manual_required"})


class RunnerError(Exception):
    def __init__(self, code, message, *, retryable=False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class RunnerConfigurationError(RunnerError):
    pass


class RunnerRequestError(RunnerError):
    pass


def _setting(name, default=None):
    return getattr(settings, name, default)


def _read_token_file(path):
    if not path:
        raise RunnerConfigurationError("RUNNER_TOKEN_FILE_MISSING", "Runner token file is not configured.")
    try:
        metadata = os.lstat(path)
    except OSError as exc:
        raise RunnerConfigurationError("RUNNER_TOKEN_FILE_UNAVAILABLE", "Runner token file is unavailable.") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RunnerConfigurationError("RUNNER_TOKEN_FILE_INVALID", "Runner token file must be a regular file.")
    mode = stat.S_IMODE(metadata.st_mode)
    if mode not in SAFE_SECRET_FILE_MODES:
        raise RunnerConfigurationError("RUNNER_TOKEN_FILE_PERMISSIONS", "Runner token file permissions are unsafe.")
    if metadata.st_size <= 0 or metadata.st_size > MAX_SECRET_FILE_BYTES:
        raise RunnerConfigurationError("RUNNER_TOKEN_FILE_SIZE", "Runner token file size is invalid.")
    try:
        with open(path, "r", encoding="utf-8", errors="strict") as handle:
            token = handle.read(MAX_SECRET_FILE_BYTES + 1)
    except (OSError, UnicodeError) as exc:
        raise RunnerConfigurationError("RUNNER_TOKEN_FILE_UNAVAILABLE", "Runner token file is unavailable.") from exc
    if len(token) > MAX_SECRET_FILE_BYTES:
        raise RunnerConfigurationError("RUNNER_TOKEN_FILE_SIZE", "Runner token file size is invalid.")
    token = token.strip()
    if not token or len(token) > MAX_SECRET_LENGTH:
        raise RunnerConfigurationError("RUNNER_TOKEN_INVALID", "Runner token is invalid.")
    return token


def _token():
    token_file = str(_setting("PILOT_RUNNER_TOKEN_FILE", "") or "").strip()
    if token_file:
        return _read_token_file(token_file)
    token = str(_setting("PILOT_RUNNER_TOKEN", "") or "").strip()
    if not token or len(token) > MAX_SECRET_LENGTH:
        raise RunnerConfigurationError("RUNNER_TOKEN_MISSING", "Runner token is not configured.")
    return token


def _ca_context():
    ca_file = str(_setting("PILOT_RUNNER_CA_FILE", "") or "").strip()
    if not ca_file:
        return ssl.create_default_context()
    try:
        metadata = os.lstat(ca_file)
    except OSError as exc:
        raise RunnerConfigurationError("RUNNER_CA_UNAVAILABLE", "Runner CA file is unavailable.") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise RunnerConfigurationError("RUNNER_CA_INVALID", "Runner CA file must be a regular file.")
    try:
        return ssl.create_default_context(cafile=ca_file)
    except (OSError, ssl.SSLError) as exc:
        raise RunnerConfigurationError("RUNNER_CA_INVALID", "Runner CA file is invalid.") from exc


def _endpoint():
    value = str(_setting("PILOT_RUNNER_URL", "") or "").strip().rstrip("/")
    parsed = urlsplit(value)
    if parsed.scheme != "https" and not bool(_setting("PILOT_RUNNER_ALLOW_INSECURE_FOR_TESTS", False)):
        raise RunnerConfigurationError("RUNNER_HTTPS_REQUIRED", "Runner endpoint must use HTTPS.")
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise RunnerConfigurationError("RUNNER_ENDPOINT_INVALID", "Runner endpoint is invalid.")
    if parsed.query or parsed.fragment:
        raise RunnerConfigurationError("RUNNER_ENDPOINT_INVALID", "Runner endpoint is invalid.")
    allowed = {str(item).strip().lower() for item in (_setting("PILOT_RUNNER_ALLOWED_HOSTS", []) or []) if str(item).strip()}
    if not allowed:
        raise RunnerConfigurationError("RUNNER_ALLOWLIST_MISSING", "Runner host allow-list is not configured.")
    netloc = parsed.netloc.lower()
    host = parsed.hostname.lower()
    if netloc not in allowed and host not in allowed:
        raise RunnerConfigurationError("RUNNER_HOST_NOT_ALLOWED", "Runner endpoint is outside the host allow-list.")
    return value


def runner_dependency_status():
    try:
        _endpoint()
        _token()
        _ca_context()
    except RunnerConfigurationError as exc:
        return {"status": "blocked" if exc.code in {"RUNNER_TOKEN_MISSING", "RUNNER_TOKEN_FILE_MISSING", "RUNNER_ALLOWLIST_MISSING"} else "degraded", "code": exc.code}
    return {"status": "connected", "code": "OK"}


def _clean_metrics(value):
    if not isinstance(value, dict):
        return {}
    metrics = {}
    for key in ALLOWED_METRICS:
        raw = value.get(key)
        if key in {"metrics_source", "scope"}:
            if isinstance(raw, str) and 1 <= len(raw) <= 80 and re.fullmatch(r"[A-Za-z0-9_.:-]+", raw):
                metrics[key] = raw
            continue
        if isinstance(raw, (int, float)) and not isinstance(raw, bool):
            # The runner reports error_rate as a percentage (0..100), matching
            # the approved PerformanceRun threshold contract.
            if key == "error_rate" and not 0 <= raw <= 100:
                continue
            if key in {"cpu_percent", "memory_percent"} and not 0 <= raw <= 100:
                continue
            if raw >= 0:
                metrics[key] = raw
    return metrics


def _clean_evidence(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [item[:200] for item in value[:20] if isinstance(item, str) and item.strip() and "\n" not in item and "\r" not in item]


class ControlledRunnerClient:
    """Submit and poll the fixed runner_release HTTP contract."""

    def _url(self, operation_id=None):
        base = _endpoint()
        if base.endswith("/v1/executions"):
            endpoint = base
        elif base.endswith("/v1"):
            endpoint = f"{base}/executions"
        else:
            endpoint = f"{base}/v1/executions"
        return f"{endpoint}/{operation_id}" if operation_id else endpoint

    def _request_json(self, method, url, *, body=None, idempotency_key=None):
        token = _token()
        maximum = max(4096, min(int(_setting("PILOT_RUNNER_MAX_RESPONSE_BYTES", 1048576)), 10_485_760))
        timeout = max(float(_setting("PILOT_RUNNER_CONNECT_TIMEOUT", 5)), float(_setting("PILOT_RUNNER_READ_TIMEOUT", 30)))
        context = _ca_context()
        data = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8") if body is not None else None
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "saas-collab-pilot-runner/production",
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with urlopen(request, timeout=timeout, context=context) as response:
                content_length = response.headers.get("Content-Length")
                if content_length and int(content_length) > maximum:
                    raise RunnerRequestError("RUNNER_RESPONSE_TOO_LARGE", "Runner response exceeded the limit.")
                raw = response.read(maximum + 1)
                if len(raw) > maximum:
                    raise RunnerRequestError("RUNNER_RESPONSE_TOO_LARGE", "Runner response exceeded the limit.")
        except HTTPError as exc:
            raise RunnerRequestError(
                f"RUNNER_HTTP_{exc.code}",
                "Runner request failed.",
                retryable=exc.code in RETRYABLE_HTTP_STATUSES,
            ) from None
        except (URLError, HTTPException, TimeoutError, OSError) as exc:
            raise RunnerRequestError("RUNNER_NETWORK_ERROR", "Runner request failed.", retryable=True) from None
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunnerRequestError("RUNNER_RESPONSE_INVALID", "Runner returned invalid JSON.") from exc
        if not isinstance(result, dict):
            raise RunnerRequestError("RUNNER_RESPONSE_INVALID", "Runner returned an invalid response.")
        return result

    def _normalize_result(self, result):
        raw_state = str(result.get("status", ""))
        state = {
            "rejected": "failed",
            "timed_out": "failed",
            "interrupted": "failed",
        }.get(raw_state, raw_state)
        if state not in ALLOWED_STATUSES:
            raise RunnerRequestError("RUNNER_RESPONSE_INVALID", "Runner returned an unsupported status.")
        operation_id = result.get("operation_id") or result.get("job_id") or result.get("id")
        if not operation_id:
            raise RunnerRequestError("RUNNER_RESPONSE_INVALID", "Runner response did not include an operation id.")
        error_code = str(result.get("error_code") or "")[:80]
        if not error_code and raw_state in {"rejected", "timed_out", "interrupted"}:
            error_code = {
                "rejected": "RUNNER_REJECTED",
                "timed_out": "RUNNER_TIMED_OUT",
                "interrupted": "RUNNER_INTERRUPTED",
            }[raw_state]
        if error_code and (not error_code.isascii() or not error_code.replace("_", "").isalnum()):
            error_code = "RUNNER_EXECUTION_FAILED"
        target_release_sha = result.get("target_release_sha")
        if not isinstance(target_release_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", target_release_sha):
            target_release_sha = ""
        target_release_version = result.get("target_release_version")
        if not isinstance(target_release_version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", target_release_version):
            target_release_version = ""
        target_release_plan_ref = result.get("target_release_plan_ref")
        if not isinstance(target_release_plan_ref, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", target_release_plan_ref):
            target_release_plan_ref = ""
        return {
            "status": state,
            "runner_job_id": str(operation_id)[:160],
            "runner_reference": str(result.get("reference") or "")[:240],
            "result_metrics": _clean_metrics(result.get("metrics")),
            "evidence_refs": _clean_evidence(result.get("evidence_refs") or result.get("evidence_ref")),
            "result_summary": str(result.get("summary") or result.get("result_summary") or "")[:1000],
            "error_code": error_code,
            "target_release_sha": target_release_sha,
            "target_release_version": target_release_version,
            "target_release_plan_ref": target_release_plan_ref,
        }

    def execute(self, execution_type, payload, *, idempotency_key=None, runner_job_id=None):
        if execution_type not in {"performance", "deploy", "recovery", "rollback"}:
            raise RunnerError("RUNNER_OPERATION_INVALID", "Unsupported runner operation.")
        allowed_fields = {"environment", "operation", "profile", "target_alias"} if execution_type == "performance" else {"environment", "operation"}
        if execution_type == "deploy":
            allowed_fields |= {"expected_release_sha", "release_plan_ref"}
        if not isinstance(payload, dict) or set(payload) - allowed_fields:
            raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner payload contains unsupported fields.")
        if not isinstance(payload.get("environment"), str) or not payload["environment"]:
            raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner environment is invalid.")
        if payload.get("operation") not in {None, execution_type}:
            raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner operation does not match execution type.")
        body = {"environment": payload["environment"], "operation": execution_type}
        # Profiles and target aliases are optional fixed identifiers; callers
        # cannot supply commands, URLs, commit refs, shell arguments, or tokens.
        if execution_type == "performance":
            profile = payload.get("profile") or "performance"
            if not isinstance(profile, str) or len(profile) > 64 or not profile.replace("-", "").replace("_", "").isalnum():
                raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner performance profile is invalid.")
            body["profile"] = profile
        elif execution_type == "deploy":
            expected_release_sha = payload.get("expected_release_sha")
            release_plan_ref = payload.get("release_plan_ref")
            if not isinstance(expected_release_sha, str) or len(expected_release_sha) != 40 or not all(char in "0123456789abcdef" for char in expected_release_sha):
                raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner expected release SHA is invalid.")
            if not isinstance(release_plan_ref, str) or not 1 <= len(release_plan_ref) <= 200 or not release_plan_ref.replace("-", "").replace("_", "").replace(".", "").replace(":", "").replace("/", "").isalnum():
                raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner release plan reference is invalid.")
            body["expected_release_sha"] = expected_release_sha
            body["release_plan_ref"] = release_plan_ref
        target_alias = payload.get("target_alias")
        if execution_type == "performance" and not target_alias:
            raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner performance target is missing.")
        if execution_type == "performance" and target_alias:
            if not isinstance(target_alias, str) or len(target_alias) > 64 or not target_alias.replace("-", "").isalnum():
                raise RunnerError("RUNNER_PAYLOAD_INVALID", "Runner target alias is invalid.")
            body["target_alias"] = target_alias
        retries = max(0, min(int(_setting("PILOT_RUNNER_MAX_RETRIES", 2)), 3))
        last_error = None
        for attempt in range(retries + 1):
            try:
                if runner_job_id:
                    # Polling is deliberately one bounded HTTP request per
                    # Celery delivery. The durable PilotExecution row carries
                    # the operation id and the next delivery polls again.
                    result = self._normalize_result(self._request_json("GET", self._url(runner_job_id)))
                else:
                    result = self._normalize_result(
                        self._request_json("POST", self._url(), body=body, idempotency_key=idempotency_key)
                    )
                if execution_type == "deploy" and result.get("status") == "succeeded" and (
                    result.get("target_release_sha") != body["expected_release_sha"]
                    or result.get("target_release_plan_ref") != body["release_plan_ref"]
                ):
                    raise RunnerRequestError("RUNNER_RELEASE_BINDING_MISMATCH", "Runner target release did not match the approved plan.")
                return result
            except RunnerRequestError as exc:
                last_error = exc
            if last_error is None or not last_error.retryable or attempt >= retries:
                break
            delay = min(float(_setting("PILOT_RUNNER_RETRY_BACKOFF", 0.5)) * (2 ** attempt), 8.0)
            if delay > 0:
                time.sleep(delay)
        raise last_error or RunnerRequestError("RUNNER_REQUEST_FAILED", "Runner request failed.")


# Stable alias for integrations and tests that used the generic name.
RunnerClient = ControlledRunnerClient
