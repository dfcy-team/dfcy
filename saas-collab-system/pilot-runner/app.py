#!/usr/bin/env python3
"""A fail-closed, architect-controlled pilot execution service.

The runner is intentionally independent of Django.  A backend calls it over
the private TLS network with a bearer token that is read from a protected file.
Operations are selected from a server-side environment/operation map; request
bodies can select only an already allowlisted performance profile.  No client
value is ever interpolated into a command or URL.

This module has no third-party dependencies so that the runner image can be
small and its security gate can run in an isolated Python image.
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import datetime as _datetime
import hashlib
import hmac
import http.server
import json
import math
import os
import pathlib
import re
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from statistics import median
from typing import Any, Iterable, Mapping, Optional

VERSION = "2.44.59"
ALLOWED_OPERATIONS = frozenset({"deploy", "recovery", "rollback", "performance"})
MAX_OPERATION_ID_LENGTH = 64
MAX_IDEMPOTENCY_KEY_LENGTH = 128
MAX_SUMMARY_LENGTH = 1000
MAX_EVIDENCE_OUTPUT_BYTES = 12_000
MAX_HTTP_RESPONSE_BYTES = 1_048_576
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class RunnerError(Exception):
    """An expected error with a stable API error code."""

    def __init__(self, code: str, message: str, http_status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


def utc_now() -> str:
    return _datetime.datetime.now(_datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _regular_file(path: pathlib.Path, label: str, *, modes: Optional[set[int]] = None) -> None:
    """Reject absent files and symlinks before opening security-sensitive paths."""

    try:
        st = path.lstat()
    except FileNotFoundError as exc:
        raise RunnerError("CONFIG_INVALID", f"{label} is missing", 503) from exc
    except OSError as exc:
        raise RunnerError("CONFIG_INVALID", f"{label} cannot be inspected", 503) from exc
    if not pathlib.Path(path).is_file() or pathlib.Path(path).is_symlink():
        raise RunnerError("CONFIG_INVALID", f"{label} must be a regular non-symlink file", 503)
    # Windows development hosts do not expose POSIX ACL/mode bits.  The
    # production VM is Linux, where the strict mode gate below is mandatory.
    if modes is not None and os.name != "nt" and hasattr(st, "st_mode"):
        mode = st.st_mode & 0o777
        if mode not in modes:
            raise RunnerError("CONFIG_INVALID", f"{label} has an unsafe mode", 503)


def _secure_directory(path: pathlib.Path, label: str, *, create: bool = True) -> None:
    if path.exists() and path.is_symlink():
        raise RunnerError("CONFIG_INVALID", f"{label} must not be a symlink", 503)
    if not path.exists():
        if not create:
            raise RunnerError("CONFIG_INVALID", f"{label} is missing", 503)
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    if not path.is_dir() or path.is_symlink():
        raise RunnerError("CONFIG_INVALID", f"{label} must be a directory", 503)
    try:
        mode = path.stat().st_mode & 0o777
        # The service may tighten a directory created by the image/entrypoint,
        # but never silently accept a group/world writable evidence directory.
        if mode & 0o077:
            path.chmod(0o700)
    except OSError as exc:
        raise RunnerError("CONFIG_INVALID", f"{label} permissions cannot be checked", 503) from exc


def _absolute_path(value: Any, label: str) -> pathlib.Path:
    if not isinstance(value, str) or not value or not os.path.isabs(value):
        raise RunnerError("CONFIG_INVALID", f"{label} must be an absolute path", 503)
    if "\x00" in value:
        raise RunnerError("CONFIG_INVALID", f"{label} contains NUL", 503)
    return pathlib.Path(value)


def _bounded_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise RunnerError("CONFIG_INVALID", f"{label} must be an integer in range", 503)
    return value


def _bounded_float(value: Any, label: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise RunnerError("CONFIG_INVALID", f"{label} must be a finite number", 503)
    value = float(value)
    if not minimum <= value <= maximum:
        raise RunnerError("CONFIG_INVALID", f"{label} is outside the configured range", 503)
    return value


def _hash_payload(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _json_safe(value: Any) -> Any:
    """Return a JSON-safe, bounded representation for evidence and errors."""

    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    if isinstance(value, Mapping):
        return {str(k): _json_safe(v) for k, v in list(value.items())[:50]}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in list(value)[:50]]
    return str(value)


def _redact_text(value: str, secrets: Iterable[str] = ()) -> str:
    text = value
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    # Catch common key/token forms even when a fixed command accidentally
    # prints one.  This is defense in depth; commands must still be reviewed.
    text = re.sub(r"(?i)(authorization\s*:\s*bearer\s+)[^\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)\b(sk-[A-Za-z0-9_-]{12,}|sk-proj-[A-Za-z0-9_-]{12,})\b", "[REDACTED]", text)
    text = re.sub(r"(?i)\b(api[_-]?key|token|password|secret)\s*([:=])\s*([^\s,;]+)", r"\1\2[REDACTED]", text)
    return text


def _safe_summary(stdout: str, stderr: str, secrets: Iterable[str]) -> str:
    combined = _redact_text((stdout or "") + ("\n" if stdout and stderr else "") + (stderr or ""), secrets)
    lines = [line.strip() for line in combined.splitlines() if line.strip()]
    if not lines:
        return "operation completed without command output"
    return lines[-1][:MAX_SUMMARY_LENGTH]


def _percentile(values: list[float], percentile: float) -> Optional[float]:
    if not values:
        return None
    values = sorted(values)
    if len(values) == 1:
        return round(values[0], 3)
    position = (len(values) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return round(values[lower], 3)
    result = values[lower] + (values[upper] - values[lower]) * (position - lower)
    return round(result, 3)


def _sleep_until(deadline: float, *, clock=time.monotonic, sleeper=time.sleep) -> None:
    """Sleep in bounded slices until a scheduled request deadline.

    Keeping the loop here makes low-RPS scheduling deterministic and testable:
    one 200 ms sleep must never be mistaken for having reached a deadline that
    is several seconds away.  The bounded slices also let shutdown/interrupt
    handling regain control promptly on a long-duration profile.
    """

    while True:
        wait = deadline - clock()
        if wait <= 0:
            return
        sleeper(min(wait, 0.2))


def _host_cpu_counters() -> Optional[tuple[int, int]]:
    """Read aggregate host CPU counters, never the runner process counters."""

    try:
        with open("/proc/stat", "r", encoding="ascii") as handle:
            fields = handle.readline().split()
        if not fields or fields[0] != "cpu" or len(fields) < 5:
            return None
        values = [int(value) for value in fields[1:]]
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return sum(values), idle
    except (OSError, ValueError, IndexError):
        return None


def _host_cpu_percent(before: Optional[tuple[int, int]], after: Optional[tuple[int, int]]) -> Optional[float]:
    if before is None or after is None:
        return None
    total_delta = after[0] - before[0]
    idle_delta = after[1] - before[1]
    if total_delta <= 0 or idle_delta < 0:
        return None
    return round(max(0.0, min(100.0, (1.0 - idle_delta / total_delta) * 100.0)), 3)


def _host_memory_percent() -> Optional[float]:
    """Return host used-memory percentage from trusted kernel counters."""

    values: dict[str, int] = {}
    try:
        with open("/proc/meminfo", "r", encoding="ascii") as handle:
            for line in handle:
                name, _, rest = line.partition(":")
                if name in {"MemTotal", "MemAvailable"}:
                    values[name] = int(rest.split()[0])
        total = values.get("MemTotal", 0)
        available = values.get("MemAvailable", 0)
        if total <= 0 or not 0 <= available <= total:
            return None
        return round((total - available) / total * 100.0, 3)
    except (OSError, ValueError, IndexError):
        return None


@dataclass(frozen=True)
class CommandSpec:
    argv: tuple[str, ...]
    timeout_seconds: int
    cwd: Optional[str] = None
    environment: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PerformanceSpec:
    mode: str
    timeout_seconds: int
    argv: tuple[str, ...] = ()
    cwd: Optional[str] = None
    environment: Mapping[str, str] = field(default_factory=dict)
    targets: Mapping[str, str] = field(default_factory=dict)
    profiles: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)


@dataclass(frozen=True)
class EnvironmentSpec:
    name: str
    commands: Mapping[str, CommandSpec]
    performance: PerformanceSpec


class RunnerConfig:
    """Validated immutable configuration loaded from a non-secret JSON file."""

    def __init__(self, data: Mapping[str, Any]):
        if not isinstance(data, Mapping):
            raise RunnerError("CONFIG_INVALID", "configuration root must be an object", 503)
        self._data = dict(data)
        listen = data.get("listen")
        if not isinstance(listen, Mapping):
            raise RunnerError("CONFIG_INVALID", "listen configuration is required", 503)
        self.host = listen.get("host", "127.0.0.1")
        if not isinstance(self.host, str) or not self.host or "\x00" in self.host:
            raise RunnerError("CONFIG_INVALID", "listen.host is invalid", 503)
        self.port = _bounded_int(listen.get("port"), "listen.port", 1, 65535)

        auth = data.get("auth")
        if not isinstance(auth, Mapping):
            raise RunnerError("CONFIG_INVALID", "auth configuration is required", 503)
        self.token_file = _absolute_path(auth.get("token_file"), "auth.token_file")

        paths = data.get("paths")
        if not isinstance(paths, Mapping):
            raise RunnerError("CONFIG_INVALID", "paths configuration is required", 503)
        self.state_file = _absolute_path(paths.get("state_file"), "paths.state_file")
        self.audit_file = _absolute_path(paths.get("audit_file"), "paths.audit_file")
        self.evidence_dir = _absolute_path(paths.get("evidence_dir"), "paths.evidence_dir")
        self.candidate_manifest_file = _absolute_path(
            paths.get("candidate_manifest_file", "/etc/saas-collab/runner/approved-candidate.json"),
            "paths.candidate_manifest_file",
        )

        limits = data.get("limits", {})
        if not isinstance(limits, Mapping):
            raise RunnerError("CONFIG_INVALID", "limits must be an object", 503)
        self.max_body_bytes = _bounded_int(limits.get("max_body_bytes", 65536), "limits.max_body_bytes", 1024, 1_048_576)
        self.max_concurrent = _bounded_int(limits.get("max_concurrent", 2), "limits.max_concurrent", 1, 32)
        self.max_operation_timeout = _bounded_int(limits.get("max_operation_timeout_seconds", 1800), "limits.max_operation_timeout_seconds", 1, 86_400)
        self.max_performance_rps = _bounded_float(limits.get("max_performance_rps", 20), "limits.max_performance_rps", 0.1, 100)
        self.max_performance_concurrency = _bounded_int(limits.get("max_performance_concurrency", 20), "limits.max_performance_concurrency", 1, 64)
        self.max_performance_duration = _bounded_int(limits.get("max_performance_duration_seconds", 300), "limits.max_performance_duration_seconds", 1, 900)
        self.request_timeout_seconds = _bounded_int(limits.get("request_timeout_seconds", 15), "limits.request_timeout_seconds", 1, 120)

        environments = data.get("environments")
        if not isinstance(environments, Mapping) or not environments:
            raise RunnerError("CONFIG_INVALID", "at least one environment is required", 503)
        self.environments: dict[str, EnvironmentSpec] = {}
        for name, env_data in environments.items():
            if not isinstance(name, str) or not SAFE_IDENTIFIER.fullmatch(name):
                raise RunnerError("CONFIG_INVALID", "environment name is invalid", 503)
            if not isinstance(env_data, Mapping):
                raise RunnerError("CONFIG_INVALID", f"environment {name} must be an object", 503)
            operations = env_data.get("operations")
            if not isinstance(operations, Mapping):
                raise RunnerError("CONFIG_INVALID", f"environment {name}.operations is required", 503)
            commands: dict[str, CommandSpec] = {}
            for operation in ("deploy", "recovery", "rollback"):
                spec = operations.get(operation)
                if not isinstance(spec, Mapping):
                    raise RunnerError("CONFIG_INVALID", f"{name}/{operation} command is required", 503)
                commands[operation] = self._parse_command(name, operation, spec)
            performance = self._parse_performance(name, operations.get("performance"))
            self.environments[name] = EnvironmentSpec(name, commands, performance)

    @classmethod
    def from_file(cls, path: os.PathLike[str] | str) -> "RunnerConfig":
        config_path = pathlib.Path(path)
        _regular_file(config_path, "runner configuration", modes={0o400, 0o440, 0o600, 0o640, 0o644})
        try:
            with config_path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise RunnerError("CONFIG_INVALID", "runner configuration cannot be read", 503) from exc
        return cls(data)

    def _parse_command(self, environment: str, operation: str, spec: Mapping[str, Any]) -> CommandSpec:
        argv = spec.get("argv")
        if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv):
            raise RunnerError("CONFIG_INVALID", f"{environment}/{operation}.argv must be a fixed non-empty string list", 503)
        # Require an absolute executable path.  The command is still reviewed
        # by the release owner; this check prevents PATH hijacking in a VM.
        if not os.path.isabs(argv[0]):
            raise RunnerError("CONFIG_INVALID", f"{environment}/{operation} executable must be absolute", 503)
        if "shell" in spec and spec.get("shell") is not False:
            raise RunnerError("CONFIG_INVALID", f"{environment}/{operation}.shell must be false if present", 503)
        timeout = _bounded_int(spec.get("timeout_seconds", 900), f"{environment}/{operation}.timeout_seconds", 1, self.max_operation_timeout)
        cwd = spec.get("cwd")
        if cwd is not None:
            cwd_path = _absolute_path(cwd, f"{environment}/{operation}.cwd")
            cwd = str(cwd_path)
        env = spec.get("environment", {})
        if not isinstance(env, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) or "\x00" in k or "\x00" in v for k, v in env.items()):
            raise RunnerError("CONFIG_INVALID", f"{environment}/{operation}.environment must contain fixed strings", 503)
        return CommandSpec(tuple(argv), timeout, cwd, dict(env))

    def _parse_performance(self, environment: str, spec: Any) -> PerformanceSpec:
        if not isinstance(spec, Mapping):
            raise RunnerError("CONFIG_INVALID", f"{environment}/performance configuration is required", 503)
        mode = spec.get("mode", "http")
        if mode not in {"http", "argv"}:
            raise RunnerError("CONFIG_INVALID", f"{environment}/performance.mode is invalid", 503)
        timeout = _bounded_int(spec.get("timeout_seconds", 30), f"{environment}/performance.timeout_seconds", 1, self.max_operation_timeout)
        cwd = spec.get("cwd")
        if cwd is not None:
            cwd = str(_absolute_path(cwd, f"{environment}/performance.cwd"))
        env = spec.get("environment", {})
        if not isinstance(env, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) or "\x00" in k or "\x00" in v for k, v in env.items()):
            raise RunnerError("CONFIG_INVALID", f"{environment}/performance.environment is invalid", 503)
        if mode == "argv":
            argv = spec.get("argv")
            if not isinstance(argv, list) or not argv or any(not isinstance(item, str) or not item or "\x00" in item for item in argv) or not os.path.isabs(argv[0]):
                raise RunnerError("CONFIG_INVALID", f"{environment}/performance.argv must be fixed with an absolute executable", 503)
            return PerformanceSpec(mode, timeout, tuple(argv), cwd, dict(env))
        targets = spec.get("targets")
        if not isinstance(targets, Mapping) or not targets:
            raise RunnerError("CONFIG_INVALID", f"{environment}/performance.targets is required", 503)
        clean_targets: dict[str, str] = {}
        for alias, url in targets.items():
            if not isinstance(alias, str) or not SAFE_IDENTIFIER.fullmatch(alias) or not isinstance(url, str):
                raise RunnerError("CONFIG_INVALID", f"{environment}/performance target allowlist is invalid", 503)
            parsed = urllib.parse.urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
                raise RunnerError("CONFIG_INVALID", f"{environment}/performance target must be an HTTPS URL without credentials/fragments", 503)
            if "\r" in url or "\n" in url:
                raise RunnerError("CONFIG_INVALID", f"{environment}/performance target contains a newline", 503)
            clean_targets[alias] = url
        profiles = spec.get("profiles")
        if not isinstance(profiles, Mapping) or not profiles:
            raise RunnerError("CONFIG_INVALID", f"{environment}/performance.profiles is required", 503)
        clean_profiles: dict[str, Mapping[str, Any]] = {}
        for profile, profile_data in profiles.items():
            if not isinstance(profile, str) or not SAFE_IDENTIFIER.fullmatch(profile) or not isinstance(profile_data, Mapping):
                raise RunnerError("CONFIG_INVALID", f"{environment}/performance profile is invalid", 503)
            target = profile_data.get("target")
            if not isinstance(target, str) or target not in clean_targets:
                raise RunnerError("CONFIG_INVALID", f"{environment}/performance profile target is not allowlisted", 503)
            rps = _bounded_float(profile_data.get("rps", 1), f"{environment}/{profile}.rps", 0.1, self.max_performance_rps)
            concurrency = _bounded_int(profile_data.get("concurrency", 1), f"{environment}/{profile}.concurrency", 1, self.max_performance_concurrency)
            duration = _bounded_int(profile_data.get("duration_seconds", 10), f"{environment}/{profile}.duration_seconds", 1, self.max_performance_duration)
            timeout_seconds = _bounded_int(profile_data.get("request_timeout_seconds", min(10, timeout)), f"{environment}/{profile}.request_timeout_seconds", 1, timeout)
            if duration > timeout or duration + timeout_seconds > timeout:
                raise RunnerError(
                    "CONFIG_INVALID",
                    f"{environment}/{profile} duration and request timeout must fit within performance.timeout_seconds",
                    503,
                )
            method = profile_data.get("method", "GET")
            if not isinstance(method, str) or method not in {"GET", "HEAD"}:
                raise RunnerError("CONFIG_INVALID", f"{environment}/{profile}.method must be GET or HEAD", 503)
            headers = profile_data.get("headers", {})
            if not isinstance(headers, Mapping) or any(not isinstance(k, str) or not isinstance(v, str) or "\r" in k or "\n" in k or "\r" in v or "\n" in v for k, v in headers.items()):
                raise RunnerError("CONFIG_INVALID", f"{environment}/{profile}.headers are invalid", 503)
            clean_profiles[profile] = {"target": target, "rps": rps, "concurrency": concurrency, "duration_seconds": duration, "request_timeout_seconds": timeout_seconds, "method": method, "headers": dict(headers)}
        return PerformanceSpec(mode, timeout, (), cwd, dict(env), clean_targets, clean_profiles)

    def environment(self, name: str) -> EnvironmentSpec:
        try:
            return self.environments[name]
        except KeyError as exc:
            raise RunnerError("UNKNOWN_ENVIRONMENT", "environment is not allowlisted", 404) from exc


class AuditLog:
    def __init__(self, path: pathlib.Path):
        self.path = path
        _secure_directory(path.parent, "audit parent directory")
        if path.exists() or path.is_symlink():
            if path.is_symlink() or not path.is_file():
                raise RunnerError("CONFIG_INVALID", "audit path must be a regular file", 503)
            mode = path.stat().st_mode & 0o777
            if mode & 0o077:
                path.chmod(0o600)
        else:
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            os.close(fd)
        self._lock = threading.Lock()

    def ensure_writable(self) -> None:
        """Check the append-only ledger before admitting an operation."""

        with self._lock:
            if self.path.is_symlink():
                raise RunnerError("AUDIT_UNAVAILABLE", "audit path became a symlink", 503)
            flags = os.O_WRONLY | os.O_APPEND
            flags |= getattr(os, "O_NOFOLLOW", 0)
            try:
                fd = os.open(self.path, flags)
            except OSError as exc:
                raise RunnerError("AUDIT_UNAVAILABLE", "audit ledger is not writable", 503) from exc
            else:
                os.close(fd)

    def append(self, event: Mapping[str, Any]) -> None:
        record = json.dumps(_json_safe(dict(event)), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with self._lock:
            if self.path.is_symlink():
                raise RunnerError("AUDIT_UNAVAILABLE", "audit path became a symlink", 503)
            flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(self.path, flags, 0o600)
            try:
                with os.fdopen(fd, "a", encoding="utf-8") as handle:
                    handle.write(record)
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise


class EvidenceStore:
    def __init__(self, directory: pathlib.Path, secrets: Iterable[str] = ()):
        _secure_directory(directory, "evidence directory")
        self.directory = directory
        self.secrets = tuple(secret for secret in secrets if secret)
        self._lock = threading.Lock()

    def add_secrets(self, secrets: Iterable[str]) -> None:
        with self._lock:
            self.secrets = tuple(dict.fromkeys((*self.secrets, *(secret for secret in secrets if secret))))

    def write(self, operation_id: str, evidence: Mapping[str, Any]) -> str:
        if not SAFE_IDENTIFIER.fullmatch(operation_id):
            raise RunnerError("EVIDENCE_WRITE_FAILED", "invalid operation id", 503)
        safe = _redact_text(json.dumps(_json_safe(dict(evidence)), ensure_ascii=False, sort_keys=True), self.secrets)
        filename = f"{operation_id}.json"
        path = self.directory / filename
        with self._lock:
            if path.exists() or path.is_symlink():
                raise RunnerError("EVIDENCE_WRITE_FAILED", "evidence file already exists", 503)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            flags |= getattr(os, "O_NOFOLLOW", 0)
            fd = os.open(path, flags, 0o600)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(safe)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
            except Exception:
                try:
                    os.close(fd)
                except OSError:
                    pass
                raise
        return f"evidence/{filename}"


class OperationStore:
    """Durable idempotency and operation result store backed by SQLite."""

    def __init__(self, path: pathlib.Path):
        _secure_directory(path.parent, "state parent directory")
        if path.exists() and path.is_symlink():
            raise RunnerError("CONFIG_INVALID", "state database must not be a symlink", 503)
        self.path = path
        self._lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        with self._lock:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            self.db.execute("PRAGMA busy_timeout=5000")
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS operations (
                    id TEXT PRIMARY KEY,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    environment TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    exit_code INTEGER,
                    summary TEXT NOT NULL DEFAULT '',
                    evidence_ref TEXT,
                    metrics_json TEXT,
                    error_code TEXT,
                    started_at TEXT,
                    deadline_at TEXT,
                    target_release_sha TEXT,
                    target_release_version TEXT,
                    target_release_plan_ref TEXT,
                    finished_at TEXT
                );
                CREATE INDEX IF NOT EXISTS operations_environment_idx ON operations(environment, id);
                """
            )
            columns = {row[1] for row in self.db.execute("PRAGMA table_info(operations)").fetchall()}
            if "deadline_at" not in columns:
                self.db.execute("ALTER TABLE operations ADD COLUMN deadline_at TEXT")
            for column in ("target_release_sha", "target_release_version", "target_release_plan_ref"):
                if column not in columns:
                    self.db.execute(f"ALTER TABLE operations ADD COLUMN {column} TEXT")
            now = utc_now()
            self.db.execute(
                "UPDATE operations SET status='interrupted', error_code='RUNNER_RESTARTED', summary=?, finished_at=? WHERE status='running'",
                ("runner restarted before the operation completed", now),
            )

    def claim(
        self,
        key: str,
        payload_hash: str,
        environment: str,
        operation: str,
        *,
        target_release_sha: Optional[str] = None,
        target_release_version: Optional[str] = None,
        target_release_plan_ref: Optional[str] = None,
    ) -> tuple[str, Optional[dict[str, Any]], bool]:
        with self._lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                row = self.db.execute("SELECT * FROM operations WHERE idempotency_key=?", (key,)).fetchone()
                if row is not None:
                    if row["payload_hash"] != payload_hash:
                        self.db.execute("COMMIT")
                        raise RunnerError("IDEMPOTENCY_CONFLICT", "idempotency key was used with a different payload", 409)
                    self.db.execute("COMMIT")
                    return row["id"], self._row_result(row), False
                operation_id = uuid.uuid4().hex
                self.db.execute(
                    "INSERT INTO operations(id,idempotency_key,environment,operation,payload_hash,status,target_release_sha,target_release_version,target_release_plan_ref) VALUES(?,?,?,?,?, 'accepted',?,?,?)",
                    (operation_id, key, environment, operation, payload_hash, target_release_sha, target_release_version, target_release_plan_ref),
                )
                self.db.execute("COMMIT")
                return operation_id, None, True
            except Exception:
                try:
                    self.db.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise

    def mark_running(self, operation_id: str, started_at: str, deadline_at: str) -> None:
        with self._lock:
            self.db.execute("UPDATE operations SET status='running', started_at=?, deadline_at=? WHERE id=?", (started_at, deadline_at, operation_id))

    def finish(
        self,
        operation_id: str,
        *,
        status: str,
        exit_code: Optional[int],
        summary: str,
        evidence_ref: Optional[str],
        metrics: Optional[Mapping[str, Any]] = None,
        error_code: Optional[str] = None,
        finished_at: Optional[str] = None,
    ) -> dict[str, Any]:
        if status not in {"succeeded", "failed", "timed_out", "rejected", "interrupted"}:
            raise ValueError("invalid operation status")
        result_metrics = json.dumps(_json_safe(metrics), ensure_ascii=False, sort_keys=True) if metrics is not None else None
        with self._lock:
            self.db.execute(
                "UPDATE operations SET status=?, exit_code=?, summary=?, evidence_ref=?, metrics_json=?, error_code=?, finished_at=? WHERE id=?",
                (status, exit_code, summary[:MAX_SUMMARY_LENGTH], evidence_ref, result_metrics, error_code, finished_at or utc_now(), operation_id),
            )
            row = self.db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
            if row is None:
                raise RunnerError("STATE_UNAVAILABLE", "operation result is unavailable", 503)
            return self._row_result(row)

    def get(self, operation_id: str) -> Optional[dict[str, Any]]:
        with self._lock:
            row = self.db.execute("SELECT * FROM operations WHERE id=?", (operation_id,)).fetchone()
        return self._row_result(row) if row is not None else None

    def close(self) -> None:
        with self._lock:
            self.db.close()

    @staticmethod
    def _row_result(row: sqlite3.Row) -> dict[str, Any]:
        internal_status = row["status"]
        # Keep the wire contract compatible with the backend state machine:
        # accepted is exposed as queued, while timeout/restart/admission
        # failures are terminal failed results with a stable error_code.
        public_status = "queued" if internal_status == "accepted" else internal_status
        if internal_status in {"timed_out", "rejected", "interrupted"}:
            public_status = "failed"
        metrics = None
        if row["metrics_json"]:
            try:
                metrics = json.loads(row["metrics_json"])
            except json.JSONDecodeError:
                metrics = None
        return {
            "operation_id": row["id"],
            "idempotency_key": row["idempotency_key"],
            "environment": row["environment"],
            "operation": row["operation"],
            "status": public_status,
            "exit_code": row["exit_code"],
            "summary": row["summary"],
            "evidence_ref": row["evidence_ref"],
            "metrics": metrics,
            "error_code": row["error_code"],
            "started_at": row["started_at"],
            "deadline_at": row["deadline_at"],
            "target_release_sha": row["target_release_sha"],
            "target_release_version": row["target_release_version"],
            "target_release_plan_ref": row["target_release_plan_ref"],
            "finished_at": row["finished_at"],
        }


def _read_approved_candidate(path: pathlib.Path) -> dict[str, str]:
    """Read the owner-staged non-secret release binding for deploy admission."""

    _regular_file(path, "approved candidate manifest", modes={0o400, 0o440, 0o600, 0o640})
    if os.name != "nt":
        metadata = path.stat()
        if metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise RunnerError("CANDIDATE_INVALID", "approved candidate ownership is unsafe", 503)
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RunnerError("CANDIDATE_INVALID", "approved candidate manifest is invalid", 503) from exc
    if not isinstance(value, Mapping):
        raise RunnerError("CANDIDATE_INVALID", "approved candidate manifest is invalid", 503)
    release_sha = value.get("release_sha")
    release_version = value.get("release_version")
    release_plan = value.get("release_plan")
    plan_ref = release_plan.get("ref") if isinstance(release_plan, Mapping) else None
    plan_version = release_plan.get("version") if isinstance(release_plan, Mapping) else None
    if not isinstance(release_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", release_sha):
        raise RunnerError("CANDIDATE_INVALID", "approved candidate release SHA is invalid", 503)
    if not isinstance(release_version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", release_version):
        raise RunnerError("CANDIDATE_INVALID", "approved candidate release version is invalid", 503)
    if not isinstance(plan_ref, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", plan_ref):
        raise RunnerError("CANDIDATE_INVALID", "approved candidate release plan reference is invalid", 503)
    if plan_version != release_version:
        raise RunnerError("CANDIDATE_INVALID", "approved candidate release plan version is inconsistent", 503)
    return {"release_sha": release_sha, "release_version": release_version, "plan_ref": plan_ref}


class RunnerService:
    def __init__(self, config: RunnerConfig):
        self.config = config
        _regular_file(config.token_file, "runner bearer token", modes={0o400, 0o440, 0o600, 0o640})
        try:
            token = config.token_file.read_text(encoding="utf-8").strip()
        except (OSError, UnicodeError) as exc:
            raise RunnerError("CONFIG_INVALID", "runner bearer token cannot be read", 503) from exc
        if not token or len(token) > 4096 or "\r" in token or "\n" in token:
            raise RunnerError("CONFIG_INVALID", "runner bearer token is invalid", 503)
        # Store only a digest with constant length.  The token value is not
        # placed in logs, SQLite, result JSON, or process arguments.
        self._token_digest = hashlib.sha256(token.encode("utf-8")).digest()
        self._token_for_redaction = token
        self.store = OperationStore(config.state_file)
        self.audit = AuditLog(config.audit_file)
        self.evidence = EvidenceStore(config.evidence_dir, [token])
        self.slots = threading.BoundedSemaphore(config.max_concurrent)
        self._environment_locks: dict[str, threading.Lock] = {name: threading.Lock() for name in config.environments}
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=config.max_concurrent, thread_name_prefix="pilot-runner")
        self._closed = False
        self._audit_broken = False
        self._close_lock = threading.Lock()

    def authenticate(self, authorization: Optional[str]) -> bool:
        if not isinstance(authorization, str) or not authorization.startswith("Bearer "):
            return False
        supplied = authorization[7:]
        if not supplied or any(char.isspace() for char in supplied):
            return False
        supplied_digest = hashlib.sha256(supplied.encode("utf-8")).digest()
        return hmac.compare_digest(self._token_digest, supplied_digest)

    def readiness(self) -> tuple[bool, str]:
        if self._closed:
            return False, "runner_closed"
        try:
            _regular_file(self.config.token_file, "runner bearer token", modes={0o400, 0o440, 0o600, 0o640})
            _secure_directory(self.config.evidence_dir, "evidence directory", create=False)
            _secure_directory(self.config.state_file.parent, "state parent directory", create=False)
            self.audit.ensure_writable()
        except RunnerError as exc:
            return False, exc.code
        if self._audit_broken:
            return False, "audit_unavailable"
        return True, "ready"

    def submit(self, payload: Mapping[str, Any], idempotency_key: str) -> tuple[int, dict[str, Any]]:
        if self._closed:
            raise RunnerError("RUNNER_UNAVAILABLE", "runner is shutting down", 503)
        if self._audit_broken:
            raise RunnerError("AUDIT_UNAVAILABLE", "audit ledger is unavailable", 503)
        self.audit.ensure_writable()
        if not isinstance(payload, Mapping):
            raise RunnerError("INVALID_PAYLOAD", "request body must be an object", 400)
        allowed_fields = {"environment", "operation", "profile", "target_alias", "expected_release_sha", "release_plan_ref"}
        if any(field not in allowed_fields for field in payload):
            raise RunnerError("INVALID_FIELD", "request contains an unsupported field", 400)
        environment = payload.get("environment")
        operation = payload.get("operation")
        if not isinstance(environment, str) or not SAFE_IDENTIFIER.fullmatch(environment):
            raise RunnerError("INVALID_ENVIRONMENT", "environment is invalid", 400)
        if not isinstance(operation, str) or operation not in ALLOWED_OPERATIONS:
            raise RunnerError("INVALID_OPERATION", "operation is invalid", 400)
        env_spec = self.config.environment(environment)
        target_binding: Optional[dict[str, str]] = None
        if operation == "performance":
            profile = payload.get("profile", "smoke")
            if not isinstance(profile, str) or not SAFE_IDENTIFIER.fullmatch(profile) or profile not in env_spec.performance.profiles:
                raise RunnerError("INVALID_PROFILE", "performance profile is not allowlisted", 400)
            target_alias = payload.get("target_alias")
            expected_target = env_spec.performance.profiles[profile].get("target")
            if target_alias is not None and target_alias != expected_target:
                raise RunnerError("TARGET_NOT_ALLOWLISTED", "target must match the server-side profile", 400)
        elif operation == "deploy":
            if set(payload) != {"environment", "operation", "expected_release_sha", "release_plan_ref"}:
                raise RunnerError("INVALID_FIELD", "deploy requires the expected release SHA and plan reference", 400)
            expected_release_sha = payload.get("expected_release_sha")
            release_plan_ref = payload.get("release_plan_ref")
            if not isinstance(expected_release_sha, str) or not re.fullmatch(r"[0-9a-f]{40}", expected_release_sha):
                raise RunnerError("INVALID_RELEASE_BINDING", "expected release SHA is invalid", 400)
            if not isinstance(release_plan_ref, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", release_plan_ref):
                raise RunnerError("INVALID_RELEASE_BINDING", "release plan reference is invalid", 400)
            candidate = _read_approved_candidate(self.config.candidate_manifest_file)
            if candidate["release_sha"] != expected_release_sha or candidate["plan_ref"] != release_plan_ref:
                raise RunnerError("RELEASE_BINDING_MISMATCH", "deploy request does not match the approved candidate", 409)
            target_binding = candidate
        else:
            if set(payload) != {"environment", "operation"}:
                raise RunnerError("INVALID_FIELD", "command operations accept only environment and operation", 400)
        if not isinstance(idempotency_key, str) or not SAFE_IDENTIFIER.fullmatch(idempotency_key) or len(idempotency_key) > MAX_IDEMPOTENCY_KEY_LENGTH:
            raise RunnerError("INVALID_IDEMPOTENCY_KEY", "Idempotency-Key is required and invalid", 400)
        normalized_payload = dict(payload)
        if operation == "performance" and "profile" not in normalized_payload:
            normalized_payload["profile"] = "smoke"
        payload_hash = _hash_payload(normalized_payload)
        operation_id, existing, created = self.store.claim(
            idempotency_key,
            payload_hash,
            environment,
            operation,
            target_release_sha=target_binding["release_sha"] if target_binding else None,
            target_release_version=target_binding["release_version"] if target_binding else None,
            target_release_plan_ref=target_binding["plan_ref"] if target_binding else None,
        )
        if not created:
            status = 200 if existing and existing["status"] in {"succeeded", "failed", "timed_out", "rejected", "interrupted"} else 202
            return status, existing or {"operation_id": operation_id, "status": "accepted"}

        # Admission is non-blocking.  An operation that cannot acquire the
        # global/environment slot is durably rejected under its idempotency key.
        if not self.slots.acquire(blocking=False):
            result = self.store.finish(operation_id, status="rejected", exit_code=None, summary="runner concurrency limit reached", evidence_ref=None, error_code="CONCURRENCY_LIMIT")
            self._audit("operation_rejected", result, error_code="CONCURRENCY_LIMIT")
            return 429, result
        environment_lock = self._environment_locks[environment]
        if not environment_lock.acquire(blocking=False):
            self.slots.release()
            result = self.store.finish(operation_id, status="rejected", exit_code=None, summary="another operation is running for this environment", evidence_ref=None, error_code="ENVIRONMENT_BUSY")
            self._audit("operation_rejected", result, error_code="ENVIRONMENT_BUSY")
            return 409, result
        started_at = utc_now()
        timeout_seconds = env_spec.performance.timeout_seconds if operation == "performance" else env_spec.commands[operation].timeout_seconds
        deadline_at = (_datetime.datetime.now(_datetime.timezone.utc) + _datetime.timedelta(seconds=timeout_seconds)).isoformat().replace("+00:00", "Z")
        self.store.mark_running(operation_id, started_at, deadline_at)
        try:
            self._audit("operation_started", {**(self.store.get(operation_id) or {}), "started_at": started_at, "deadline_at": deadline_at})
        except Exception as exc:
            environment_lock.release()
            self.slots.release()
            result = self.store.finish(operation_id, status="rejected", exit_code=None, summary="audit ledger is unavailable", evidence_ref=None, error_code="AUDIT_UNAVAILABLE")
            self._audit_broken = True
            raise RunnerError("AUDIT_UNAVAILABLE", "audit ledger is unavailable", 503) from exc
        try:
            self._executor.submit(self._execute, operation_id, normalized_payload, env_spec, environment_lock)
        except Exception as exc:
            environment_lock.release()
            self.slots.release()
            result = self.store.finish(operation_id, status="failed", exit_code=None, summary="runner could not schedule the operation", evidence_ref=None, error_code="SCHEDULING_FAILED")
            self._audit("operation_finished", result, error_code="SCHEDULING_FAILED")
            raise RunnerError("SCHEDULING_FAILED", "runner could not schedule the operation", 503) from exc
        result = self.store.get(operation_id) or {"operation_id": operation_id, "status": "running"}
        return 202, result

    def get_result(self, operation_id: str) -> dict[str, Any]:
        if not isinstance(operation_id, str) or not SAFE_IDENTIFIER.fullmatch(operation_id) or len(operation_id) > MAX_OPERATION_ID_LENGTH:
            raise RunnerError("INVALID_OPERATION_ID", "operation id is invalid", 400)
        result = self.store.get(operation_id)
        if result is None:
            raise RunnerError("NOT_FOUND", "operation result was not found", 404)
        return result

    def _execute(self, operation_id: str, payload: Mapping[str, Any], env_spec: EnvironmentSpec, environment_lock: threading.Lock) -> None:
        operation = str(payload["operation"])
        environment = str(payload["environment"])
        try:
            if operation == "performance":
                outcome = self._run_performance(operation_id, payload, env_spec)
            else:
                outcome = self._run_command(operation_id, env_spec.commands[operation])
            if operation == "recovery" and outcome.get("status") == "succeeded":
                elapsed_ms = outcome.get("evidence", {}).get("elapsed_ms")
                if isinstance(elapsed_ms, (int, float)) and not isinstance(elapsed_ms, bool) and math.isfinite(float(elapsed_ms)) and elapsed_ms >= 0:
                    recovery_metrics = {
                        "actual_rpo_minutes": 0,
                        "actual_rto_minutes": int(math.ceil(float(elapsed_ms) / 60_000.0)),
                        "metrics_source": "runner-command-elapsed",
                        "scope": "application_service_reconciliation",
                    }
                    outcome["metrics"] = recovery_metrics
                    outcome["evidence"] = {**outcome["evidence"], "recovery_metrics": recovery_metrics, "scope": "application_service_reconciliation"}
                else:
                    outcome["status"] = "failed"
                    outcome["exit_code"] = 1
                    outcome["error_code"] = "RECOVERY_METRICS_UNAVAILABLE"
                    outcome["summary"] = "recovery completed without a trusted reconciliation duration"
            evidence_ref = self.evidence.write(operation_id, outcome["evidence"])
            result = self.store.finish(operation_id, status=outcome["status"], exit_code=outcome.get("exit_code"), summary=outcome["summary"], evidence_ref=evidence_ref, metrics=outcome.get("metrics"), error_code=outcome.get("error_code"))
            self._audit("operation_finished", result, error_code=outcome.get("error_code"))
        except Exception as exc:
            # Unexpected failures are converted to a generic, non-sensitive
            # terminal result.  The traceback is intentionally not returned.
            result = self.store.finish(operation_id, status="failed", exit_code=None, summary="runner operation failed before a result was produced", evidence_ref=None, error_code="EXECUTION_FAILED")
            self._audit("operation_finished", result, error_code="EXECUTION_FAILED")
        finally:
            environment_lock.release()
            self.slots.release()

    def _run_command(self, operation_id: str, spec: CommandSpec) -> dict[str, Any]:
        command_hash = hashlib.sha256(json.dumps(spec.argv, separators=(",", ":")).encode("utf-8")).hexdigest()
        process_environment = os.environ.copy()
        process_environment.update(spec.environment)
        stdout = b""
        stderr = b""
        exit_code: Optional[int] = None
        timed_out = False
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                list(spec.argv),
                cwd=spec.cwd,
                env=process_environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                shell=False,
                start_new_session=(os.name != "nt"),
            )
            try:
                stdout, stderr = process.communicate(timeout=spec.timeout_seconds)
                exit_code = process.returncode
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                if exc.output:
                    stdout = exc.output if isinstance(exc.output, bytes) else str(exc.output).encode()
                if exc.stderr:
                    stderr = exc.stderr if isinstance(exc.stderr, bytes) else str(exc.stderr).encode()
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except (OSError, ProcessLookupError):
                        process.kill()
                else:
                    process.kill()
                trailing_stdout, trailing_stderr = process.communicate()
                stdout += trailing_stdout or b""
                stderr += trailing_stderr or b""
        except (OSError, ValueError) as exc:
            return {
                "status": "failed",
                "exit_code": None,
                "summary": "fixed operation could not be started",
                "error_code": "COMMAND_START_FAILED",
                "evidence": {"kind": "command", "argv_sha256": command_hash, "error": type(exc).__name__},
            }
        elapsed_ms = round((time.monotonic() - started) * 1000, 3)
        stdout_text = stdout[:MAX_EVIDENCE_OUTPUT_BYTES].decode("utf-8", errors="replace")
        stderr_text = stderr[:MAX_EVIDENCE_OUTPUT_BYTES].decode("utf-8", errors="replace")
        stdout_text = _redact_text(stdout_text, self.evidence.secrets)
        stderr_text = _redact_text(stderr_text, self.evidence.secrets)
        status = "timed_out" if timed_out else ("succeeded" if exit_code == 0 else "failed")
        error_code = "COMMAND_TIMEOUT" if timed_out else (None if exit_code == 0 else "COMMAND_EXIT_NONZERO")
        return {
            "status": status,
            "exit_code": exit_code,
            "summary": _safe_summary(stdout_text, stderr_text, self.evidence.secrets),
            "error_code": error_code,
            "evidence": {"kind": "command", "argv_sha256": command_hash, "exit_code": exit_code, "timed_out": timed_out, "elapsed_ms": elapsed_ms, "stdout": stdout_text, "stderr": stderr_text},
        }

    def _run_performance(self, operation_id: str, payload: Mapping[str, Any], env_spec: EnvironmentSpec) -> dict[str, Any]:
        perf = env_spec.performance
        if perf.mode == "argv":
            command_outcome = self._run_command(operation_id, CommandSpec(perf.argv, perf.timeout_seconds, perf.cwd, perf.environment))
            if command_outcome["status"] != "succeeded":
                command_outcome["evidence"]["kind"] = "performance-command"
                return command_outcome
            raw = command_outcome["evidence"].get("stdout", "")
            metrics = self._parse_metrics(raw)
            if metrics is None:
                command_outcome["status"] = "failed"
                command_outcome["error_code"] = "PERFORMANCE_METRICS_INVALID"
                command_outcome["summary"] = "performance adapter did not return the required metrics"
                command_outcome["evidence"]["kind"] = "performance-command"
                return command_outcome
            command_outcome["metrics"] = metrics
            command_outcome["evidence"]["kind"] = "performance-command"
            command_outcome["evidence"]["metrics"] = metrics
            command_outcome["summary"] = "fixed performance adapter completed"
            return command_outcome

        profile_name = str(payload.get("profile", "smoke"))
        profile = perf.profiles[profile_name]
        target_alias = str(profile["target"])
        target_url = perf.targets[target_alias]
        return self._run_http_performance(profile_name, target_alias, target_url, profile)

    @staticmethod
    def _parse_metrics(text: str) -> Optional[dict[str, Any]]:
        for line in reversed(text.splitlines()):
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(value, Mapping):
                continue
            required = ("p50_ms", "p95_ms", "error_rate", "cpu_percent", "memory_percent")
            if all(key in value and isinstance(value[key], (int, float)) and not isinstance(value[key], bool) and math.isfinite(float(value[key])) for key in required):
                if not 0 <= float(value["error_rate"]) <= 100:
                    continue
                if not 0 <= float(value["cpu_percent"]) <= 100 or not 0 <= float(value["memory_percent"]) <= 100:
                    continue
                parsed = {key: round(float(value[key]), 3) for key in required}
                for key in ("requests", "successful_requests", "failed_requests", "rps", "concurrency", "duration_seconds"):
                    raw = value.get(key)
                    if isinstance(raw, (int, float)) and not isinstance(raw, bool) and math.isfinite(float(raw)) and raw >= 0:
                        parsed[key] = round(float(raw), 3)
                parsed["metrics_source"] = "trusted-performance-adapter"
                return parsed
        return None

    def _run_http_performance(self, profile_name: str, target_alias: str, target_url: str, profile: Mapping[str, Any]) -> dict[str, Any]:
        rps = float(profile["rps"])
        concurrency = int(profile["concurrency"])
        duration = int(profile["duration_seconds"])
        timeout = int(profile["request_timeout_seconds"])
        method = str(profile["method"])
        headers = dict(profile.get("headers", {}))
        # All values above originate in validated server configuration, never
        # from the request body.  Do not add an Authorization header here.
        count = max(1, min(int(math.ceil(rps * duration)), int(self.config.max_performance_rps * self.config.max_performance_duration)))
        results: list[tuple[bool, float, Optional[int], Optional[str]]] = []
        result_lock = threading.Lock()
        host_cpu_before = _host_cpu_counters()

        def one_request() -> tuple[bool, float, Optional[int], Optional[str]]:
            request_started = time.monotonic()
            status_code: Optional[int] = None
            error_name: Optional[str] = None
            ok = False
            try:
                request = urllib.request.Request(target_url, headers=headers, method=method)
                context = ssl.create_default_context()
                with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                    status_code = int(response.status)
                    response.read(MAX_HTTP_RESPONSE_BYTES)
                    ok = 200 <= status_code < 400
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                error_name = type(exc).__name__
            elapsed = round((time.monotonic() - request_started) * 1000, 3)
            return ok, elapsed, status_code, error_name

        with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency, thread_name_prefix="pilot-http") as pool:
            futures: list[concurrent.futures.Future[tuple[bool, float, Optional[int], Optional[str]]]] = []
            interval = 1.0 / rps
            next_at = time.monotonic()
            for _ in range(count):
                _sleep_until(next_at)
                futures.append(pool.submit(one_request))
                next_at += interval
            for future in futures:
                try:
                    result = future.result(timeout=timeout + 5)
                except Exception as exc:
                    result = (False, float((timeout + 5) * 1000), None, type(exc).__name__)
                with result_lock:
                    results.append(result)
        latencies = [result[1] for result in results]
        failures = sum(1 for result in results if not result[0])
        status_counts: dict[str, int] = {}
        errors: dict[str, int] = {}
        for ok, _latency, status_code, error_name in results:
            if status_code is not None:
                key = str(status_code)
                status_counts[key] = status_counts.get(key, 0) + 1
            if error_name:
                errors[error_name] = errors.get(error_name, 0) + 1
        metrics = {
            "requests": len(results),
            "successful_requests": len(results) - failures,
            "failed_requests": failures,
            "p50_ms": _percentile(latencies, 0.50),
            "p95_ms": _percentile(latencies, 0.95),
            "error_rate": round((failures / len(results) * 100) if results else 100.0, 3),
        # When runner is installed on the same application VM, these are
        # kernel host counters (not runner process counters). The scope is
        # explicit so consumers do not mistake host saturation for a precise
        # per-container measurement.
        "cpu_percent": _host_cpu_percent(host_cpu_before, _host_cpu_counters()),
        "memory_percent": _host_memory_percent(),
        "metrics_source": "app-vm-host-proc",
        "scope": "app_vm_host",
            "rps": rps,
            "concurrency": concurrency,
            "duration_seconds": duration,
        }
        evidence = {"kind": "performance-http", "profile": profile_name, "target_alias": target_alias, "requests": len(results), "status_counts": status_counts, "errors": errors, "metrics": metrics}
        status = "succeeded" if failures == 0 else "failed"
        error_code = None if status == "succeeded" else "PERFORMANCE_ERRORS"
        if status == "succeeded" and (metrics["cpu_percent"] is None or metrics["memory_percent"] is None):
            # A production threshold decision must include trusted target
            # resource telemetry. If host counters are unavailable, fail
            # closed even when every request was successful.
            status = "failed"
            error_code = "PERFORMANCE_RESOURCE_METRICS_UNAVAILABLE"
        summary = f"HTTPS performance profile {profile_name} completed for allowlisted target {target_alias}"
        if error_code == "PERFORMANCE_RESOURCE_METRICS_UNAVAILABLE":
            summary += "; target CPU and memory telemetry is unavailable"
        return {"status": status, "exit_code": 0 if status == "succeeded" else 1, "summary": summary, "error_code": error_code, "metrics": metrics, "evidence": evidence}

    def _audit(self, event: str, result: Mapping[str, Any], *, error_code: Optional[str] = None) -> None:
        event_data = {"schema_version": 1, "event": event, "time": utc_now(), "operation_id": result.get("operation_id"), "environment": result.get("environment"), "operation": result.get("operation"), "status": result.get("status"), "error_code": error_code or result.get("error_code"), "exit_code": result.get("exit_code"), "evidence_ref": result.get("evidence_ref")}
        try:
            self.audit.append(event_data)
        except Exception:
            # An audit failure is a hard operational fault.  The current
            # operation cannot be made invisible, so retain its result for
            # diagnosis but fail readiness and reject subsequent operations.
            self._audit_broken = True
            raise

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
            self._executor.shutdown(wait=True, cancel_futures=False)
            self.store.close()


class RunnerHTTPServer(http.server.ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, address: tuple[str, int], service: RunnerService, tls_context: ssl.SSLContext):
        self.service = service
        self.request_timeout_seconds = service.config.request_timeout_seconds
        super().__init__(address, RunnerRequestHandler)
        # Wrap the listening socket before accept().  No plaintext listener is
        # ever exposed, including during startup.
        self.socket = tls_context.wrap_socket(self.socket, server_side=True)


class RunnerRequestHandler(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pilot-runner/" + VERSION
    sys_version = ""

    @property
    def runner_server(self) -> RunnerHTTPServer:
        return self.server  # type: ignore[return-value]

    def setup(self) -> None:
        super().setup()
        self.connection.settimeout(self.runner_server.request_timeout_seconds)

    def log_message(self, fmt: str, *args: Any) -> None:
        # Never log Authorization headers or request bodies.  The default
        # logger only receives method/path/status/size below.
        sys.stderr.write("pilot-runner http " + (fmt % args) + "\n")

    def do_GET(self) -> None:  # noqa: N802
        try:
            if self.path == "/healthz":
                self._send(200, {"status": "ok", "service": "pilot-runner", "version": VERSION})
                return
            if self.path == "/readyz":
                ready, reason = self.runner_server.service.readiness()
                self._send(200 if ready else 503, {"status": "ready" if ready else "not_ready", "reason": reason})
                return
            if not self.runner_server.service.authenticate(self.headers.get("Authorization")):
                self._send_error(401, "UNAUTHORIZED", "bearer authentication required")
                return
            parsed = urllib.parse.urlsplit(self.path)
            prefixes = ("/v1/executions/", "/v1/operations/")
            prefix = next((candidate for candidate in prefixes if parsed.path.startswith(candidate)), None)
            if prefix is not None:
                operation_id = urllib.parse.unquote(parsed.path[len(prefix):])
                result = self.runner_server.service.get_result(operation_id)
                self._send(200, result)
                return
            self._send_error(404, "NOT_FOUND", "resource not found")
        except RunnerError as exc:
            self._send_error(exc.http_status, exc.code, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            self._send_error(503, "RUNNER_UNAVAILABLE", "runner request failed")

    def do_POST(self) -> None:  # noqa: N802
        try:
            if not self.runner_server.service.authenticate(self.headers.get("Authorization")):
                self._send_error(401, "UNAUTHORIZED", "bearer authentication required")
                return
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path not in {"/v1/executions", "/v1/operations"}:
                self._send_error(404, "NOT_FOUND", "resource not found")
                return
            payload = self._read_json_body()
            status, result = self.runner_server.service.submit(payload, self.headers.get("Idempotency-Key", ""))
            self._send(status, result)
        except RunnerError as exc:
            self._send_error(exc.http_status, exc.code, exc.message)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True
        except Exception:
            self._send_error(503, "RUNNER_UNAVAILABLE", "runner request failed")

    def _read_json_body(self) -> Mapping[str, Any]:
        content_length = self.headers.get("Content-Length")
        if self.headers.get("Transfer-Encoding"):
            raise RunnerError("REQUEST_BODY_INVALID", "chunked request bodies are not accepted", 400)
        try:
            size = int(content_length or "-1")
        except ValueError as exc:
            raise RunnerError("REQUEST_BODY_INVALID", "Content-Length is invalid", 400) from exc
        if size < 1:
            raise RunnerError("REQUEST_BODY_INVALID", "JSON request body is required", 400)
        if size > self.runner_server.service.config.max_body_bytes:
            raise RunnerError("REQUEST_BODY_TOO_LARGE", "request body exceeds the configured limit", 413)
        raw = self.rfile.read(size)
        if len(raw) != size:
            raise RunnerError("REQUEST_BODY_INVALID", "request body was truncated", 400)
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RunnerError("INVALID_JSON", "request body must be valid JSON", 400) from exc
        if not isinstance(value, Mapping):
            raise RunnerError("INVALID_PAYLOAD", "request body must be a JSON object", 400)
        return value

    def _send_error(self, status: int, code: str, message: str) -> None:
        self._send(status, {"code": code, "message": message})

    def _send(self, status: int, payload: Mapping[str, Any]) -> None:
        body = json.dumps(_json_safe(dict(payload)), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True


def build_tls_context(config: RunnerConfig) -> ssl.SSLContext:
    tls = config._data.get("tls")
    if not isinstance(tls, Mapping):
        raise RunnerError("CONFIG_INVALID", "tls configuration is required", 503)
    cert_file = _absolute_path(tls.get("cert_file"), "tls.cert_file")
    key_file = _absolute_path(tls.get("key_file"), "tls.key_file")
    _regular_file(cert_file, "TLS certificate", modes={0o400, 0o440, 0o600, 0o640, 0o644})
    _regular_file(key_file, "TLS private key", modes={0o400, 0o440, 0o600})
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.options |= getattr(ssl, "OP_NO_COMPRESSION", 0)
    context.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    client_ca_file = tls.get("client_ca_file")
    require_client_certificate = bool(tls.get("require_client_certificate", False))
    if client_ca_file is not None:
        ca_path = _absolute_path(client_ca_file, "tls.client_ca_file")
        _regular_file(ca_path, "TLS client CA", modes={0o400, 0o440, 0o600, 0o640, 0o644})
        context.load_verify_locations(cafile=str(ca_path))
        context.verify_mode = ssl.CERT_REQUIRED if require_client_certificate else ssl.CERT_OPTIONAL
    elif require_client_certificate:
        raise RunnerError("CONFIG_INVALID", "client CA is required when client certificate validation is enabled", 503)
    return context


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="controlled pilot runner")
    parser.add_argument("--config", default=os.environ.get("PILOT_RUNNER_CONFIG_FILE", "/etc/saas-collab/runner/config.json"))
    args = parser.parse_args(argv)
    try:
        config = RunnerConfig.from_file(args.config)
        tls_context = build_tls_context(config)
        service = RunnerService(config)
    except RunnerError as exc:
        sys.stderr.write(f"pilot-runner startup blocked: {exc.code}\n")
        return 78
    except Exception:
        sys.stderr.write("pilot-runner startup blocked: CONFIG_INVALID\n")
        return 78
    server: Optional[RunnerHTTPServer] = None
    stop_event = threading.Event()

    def stop(_signum: int, _frame: Any) -> None:
        if not stop_event.is_set():
            stop_event.set()
            if server is not None:
                threading.Thread(target=server.shutdown, daemon=True).start()

    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, stop)
    try:
        server = RunnerHTTPServer((config.host, config.port), service, tls_context)
        sys.stderr.write(f"pilot-runner listening on TLS {config.host}:{config.port}\n")
        server.serve_forever(poll_interval=0.5)
    except (OSError, ssl.SSLError) as exc:
        sys.stderr.write(f"pilot-runner stopped: {type(exc).__name__}\n")
        return 1
    finally:
        if server is not None:
            server.server_close()
        service.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
