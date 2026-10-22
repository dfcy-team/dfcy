"""Intranet-only orchestration. No production DB connection or automatic scheduler."""
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone as dt_timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from apps.permissions.services import check_user_permission

from .contracts import RESOURCES, enabled
from .models import SnapshotBatch, SyncAudit, SyncEnvironment


class SyncFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class ReadonlyClient:
    def __init__(self, source):
        parsed = urlsplit(source.get("url", ""))
        hosts = getattr(settings, "DEMO_DATA_SYNC_ALLOWED_HOSTS", [])
        if (parsed.scheme != "https" or not parsed.hostname or parsed.hostname not in hosts
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in ("", "/") or parsed.port not in (None, 443, 8443)):
            raise SyncFailure("SOURCE_URL_NOT_ALLOWED")
        self.url = source["url"].rstrip("/") + "/api/internal-readonly/v1/"
        # Configuration contains ENVIRONMENT VARIABLE NAMES, never secret values.
        client_id = os.environ.get(source.get("client_id_env", ""), "")
        secret = os.environ.get(source.get("client_secret_env", ""), "")
        masking = os.environ.get(source.get("masking_key_env", ""), "")
        if not client_id or not secret or len(masking.encode()) < 32:
            raise SyncFailure("SOURCE_CREDENTIALS_MISSING")
        self.masking_key = masking.encode()
        self.page_size = max(1, min(int(source.get("page_size", 100)), 1000))
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.auth = (client_id, secret)
        self.request_count = 0

    def close(self):
        self.session.close()

    def fetch(self, resource, params):
        if resource not in RESOURCES:
            raise SyncFailure("RESOURCE_NOT_ALLOWED")
        if self.request_count >= 10000:
            raise SyncFailure("REQUEST_BUDGET_EXCEEDED")
        for attempt in range(3):
            self.request_count += 1
            response = None
            try:
                request_params = {**params, "limit": min(int(params.get("limit", self.page_size)), self.page_size)}
                response = self.session.get(self.url + resource + "/", params=request_params,
                                            timeout=(5, 20), allow_redirects=False, stream=True)
                if response.status_code in (429, 500, 502, 503, 504):
                    if attempt < 2:
                        response.close()
                        time.sleep(2 ** attempt)
                        continue
                    raise SyncFailure("SOURCE_RETRY_EXHAUSTED")
                if response.status_code != 200:
                    raise SyncFailure("SOURCE_ACCESS_DENIED" if response.status_code in (401, 403) else "SOURCE_HTTP_ERROR")
                raw = bytearray()
                for chunk in response.iter_content(64 * 1024):
                    raw.extend(chunk)
                    if len(raw) > 8 * 1024 * 1024:
                        raise SyncFailure("SOURCE_PAGE_TOO_LARGE")
                envelope = json.loads(raw)
                data = envelope.get("data")
                if envelope.get("success") is not True or not isinstance(data, dict) or not isinstance(data.get("items"), list):
                    raise SyncFailure("SOURCE_CONTRACT_INVALID")
                # Conservative single-thread pacing; production quota still applies.
                time.sleep(1)
                return data
            except (requests.Timeout, requests.ConnectionError):
                if attempt == 2:
                    raise SyncFailure("SOURCE_UNAVAILABLE") from None
                time.sleep(2 ** attempt)
            except (ValueError, TypeError):
                raise SyncFailure("SOURCE_CONTRACT_INVALID") from None
            finally:
                if response is not None:
                    response.close()
        raise SyncFailure("SOURCE_UNAVAILABLE")


def artifact_path(batch_id):
    configured = getattr(settings, "DEMO_DATA_SYNC_ARTIFACT_ROOT", "")
    if not configured or not Path(configured).is_absolute():
        raise SyncFailure("ARTIFACT_ROOT_NOT_CONFIGURED")
    root = Path(configured)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise SyncFailure("ARTIFACT_SYMLINK_REJECTED")
    path = root / str(batch_id)
    if path.is_symlink():
        raise SyncFailure("ARTIFACT_SYMLINK_REJECTED")
    return path


def verified_bundle_files(folder):
    """Never trust manifest paths, sizes or hashes during authenticated download."""
    manifest_path = folder / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file() or manifest_path.stat().st_size > 1024 * 1024:
        raise SyncFailure("MANIFEST_INVALID")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "demo-snapshot.v1" or manifest.get("deidentified") is not True:
        raise SyncFailure("MANIFEST_INVALID")
    entries = manifest.get("files", [])
    if not isinstance(entries, list) or not entries or len(entries) > len(RESOURCES):
        raise SyncFailure("MANIFEST_INVALID")
    paths, seen, total = [manifest_path], set(), 0
    for entry in entries:
        resource = entry.get("resource")
        name = entry.get("path")
        if resource not in RESOURCES or resource in seen or name != resource + ".jsonl":
            raise SyncFailure("MANIFEST_INVALID")
        seen.add(resource)
        path = folder / name
        if path.is_symlink() or not path.is_file():
            raise SyncFailure("ARTIFACT_INVALID")
        total += path.stat().st_size
        if total > 512 * 1024 * 1024:
            raise SyncFailure("ARTIFACT_TOO_LARGE")
        digest = hashlib.sha256()
        count = 0
        with path.open("rb") as stream:
            for line in stream:
                digest.update(line)
                count += 1
        if digest.hexdigest() != entry.get("sha256") or count != entry.get("count"):
            raise SyncFailure("ARTIFACT_HASH_MISMATCH")
        paths.append(path)
    return paths


def run_batch(batch_id, *, client=None):
    if not enabled() or not getattr(settings, "DEMO_DATA_SYNC_WORKER_ENABLED", False):
        raise SyncFailure("WORKER_DISABLED")
    if client is None and not getattr(settings, "DEMO_DATA_SYNC_SERVICE_INSTANCE", False):
        raise SyncFailure("INTRANET_SERVICE_ROLE_REQUIRED")
    from .pipeline import build_snapshot
    with transaction.atomic():
        batch = SnapshotBatch.objects.select_for_update().select_related("environment").get(pk=batch_id)
        if batch.status != "queued":
            raise SyncFailure("BATCH_NOT_QUEUED")
        batch.status, batch.started_at = "running", timezone.now()
        batch.heartbeat_at = batch.started_at
        batch.save(update_fields=["status", "started_at", "heartbeat_at"])
        SyncAudit.objects.create(tenant_id=batch.tenant_id, batch=batch, event="batch.started")
    owned_client = client is None
    try:
        check_batch_access(batch)
        source = getattr(settings, "DEMO_DATA_SYNC_SOURCES", {}).get(batch.environment.source_alias, {})
        if client is None:
            if source.get("tenant_id") != batch.tenant_id:
                raise SyncFailure("SOURCE_TENANT_NOT_BOUND")
            client = ReadonlyClient(source)
        folder = artifact_path(batch.pk)
        folder.mkdir(parents=True, exist_ok=False, mode=0o700)
        manifest = build_snapshot(client=GuardedClient(client, batch), resources=batch.resources,
                                  store_ids=batch.environment.store_ids,
                                  warehouse_ids=batch.environment.warehouse_ids,
                                  date_from=batch.date_from.isoformat(), date_to=batch.date_to.isoformat(),
                                  output_dir=folder, scope_key=f"{batch.tenant_id}:{batch.environment_id}")
        verified_bundle_files(folder)
        with transaction.atomic():
            env = SyncEnvironment.objects.select_for_update().get(pk=batch.environment_id)
            check_batch_access(batch)
            # Only counts and contract metadata are exposed, never source rows.
            batch.summary = {"rows": sum(f["count"] for f in manifest["files"]),
                             "counts": {f["resource"]: f["count"] for f in manifest["files"]},
                             "schema_version": manifest["schema_version"], "deidentified": True,
                             "consistency": "collection_window", "requests": client.request_count if hasattr(client, "request_count") else 0}
            batch.status, batch.finished_at = "ready", timezone.now()
            batch.save(update_fields=["status", "summary", "finished_at"])
            SyncAudit.objects.create(tenant_id=batch.tenant_id, batch=batch, event="batch.ready")
    except Exception as error:
        # Suppress arbitrary upstream/DB exception text: it can contain credentials or PII.
        batch.status = "failed"
        code = getattr(error, "code", "SNAPSHOT_FAILED")
        batch.error_code = code if isinstance(code, str) and re.fullmatch(r"[A-Z_]{1,64}", code) else "SNAPSHOT_FAILED"
        batch.finished_at = timezone.now()
        batch.save(update_fields=["status", "error_code", "finished_at"])
        SyncAudit.objects.create(tenant_id=batch.tenant_id, batch=batch, event="batch.failed")
    finally:
        if owned_client and client is not None:
            client.close()
    return batch


def check_batch_access(batch):
    if not SnapshotBatch.objects.filter(pk=batch.pk, status="running").update(heartbeat_at=timezone.now()):
        raise SyncFailure("BATCH_LEASE_LOST")
    if not enabled() or not SyncEnvironment.objects.filter(pk=batch.environment_id, active=True, owner__is_active=True).exists():
        raise SyncFailure("ENVIRONMENT_REVOKED")
    user = type(batch.requested_by).objects.get(pk=batch.requested_by_id)
    if (not user.is_active or user.user_type != "internal" or user.tenant_id != batch.tenant_id
            or not all(check_user_permission(user, f"system.demo_sync.{p}") for p in ("view", "run"))
            or (user.pk != batch.environment.owner_id and not check_user_permission(user, "system.demo_sync.manage"))):
        raise SyncFailure("REQUESTER_PERMISSION_REVOKED")


class GuardedClient:
    def __init__(self, client, batch):
        self.client, self.batch = client, batch
        self.masking_key = client.masking_key

    def fetch(self, resource, params):
        # Check each page; revocation stops further requests and blocks publication.
        check_batch_access(self.batch)
        return self.client.fetch(resource, params)
