"""Focused storage and operator-backup contract tests using private mocks."""

import hashlib
import io
import json
import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.reports import export_backup, export_services, object_storage
from apps.permissions.models import DataScope, Permission, UserRole
from tests.test_report_revision import _config, _report_access
from tests.test_sales_management import client_for, create_order, create_scope, grant, user_for


class PrivateMemoryStorage:
    """Test-only private object backend; no network or provider credentials."""

    namespace = "unit-test"

    def __init__(self):
        self.objects = {}

    def save(self, name, content):
        self.objects[name] = content.read()
        return name

    def open(self, name, mode="rb"):
        if name not in self.objects:
            raise FileNotFoundError(name)
        return io.BytesIO(self.objects[name])


def record(*, tenant_id=17, file_format="csv", **values):
    fields = dict(
        tenant_id=tenant_id,
        file_format=file_format,
        storage_alias="",
        storage_key="",
        file_size=None,
        file_sha256="",
        content_type="",
    )
    fields.update(values)
    return SimpleNamespace(**fields)


def test_legacy_empty_alias_reads_old_local_record(tmp_path, settings):
    settings.REPORT_EXPORT_ROOT = tmp_path
    key = f"17/{uuid.uuid4().hex}.csv"
    payload = b"old,export\n"
    (tmp_path / "17").mkdir()
    (tmp_path / key).write_bytes(payload)
    old = record(storage_key=key, file_sha256=hashlib.sha256(payload).hexdigest())

    with object_storage.open_verified_export(old) as source:
        assert source.read() == payload


def test_write_alias_switch_keeps_each_record_bound_to_its_original_alias(monkeypatch, settings):
    old_backend, new_backend = PrivateMemoryStorage(), PrivateMemoryStorage()
    backends = {"private_old": old_backend, "private_new": new_backend}
    monkeypatch.setattr(object_storage, "_storage", lambda alias: backends[alias])
    settings.REPORT_EXPORT_ALLOWED_STORAGE_ALIASES = ("private_old", "private_new")
    settings.REPORT_EXPORT_WRITE_STORAGE_ALIAS = "private_old"
    old = record()
    object_storage.write_export(old, b"bound to old\n")

    settings.REPORT_EXPORT_WRITE_STORAGE_ALIAS = "private_new"
    new = record()
    object_storage.write_export(new, b"bound to new\n")

    assert old.storage_alias == "private_old"
    assert new.storage_alias == "private_new"
    assert len(old_backend.objects) == len(new_backend.objects) == 1
    with object_storage.open_verified_export(old) as source:
        assert source.read() == b"bound to old\n"


def test_object_write_persists_metadata_and_verifies_full_content(monkeypatch, settings):
    backend = PrivateMemoryStorage()
    monkeypatch.setattr(object_storage, "_storage", lambda alias: backend)
    settings.REPORT_EXPORT_ALLOWED_STORAGE_ALIASES = ("private",)
    settings.REPORT_EXPORT_WRITE_STORAGE_ALIAS = "private"
    target = record(tenant_id=31, file_format="txt")
    payload = b"report contents\n"

    object_storage.write_export(target, payload)

    assert target.storage_key.startswith("reports/unit-test/tenant-31/")
    assert target.storage_key.endswith(".txt")
    assert target.file_size == len(payload)
    assert target.file_sha256 == hashlib.sha256(payload).hexdigest()
    assert target.content_type == "text/plain; charset=utf-8"
    with object_storage.open_verified_export(target) as source:
        assert source.read() == payload


def test_cross_tenant_object_key_is_rejected(monkeypatch, settings):
    monkeypatch.setattr(object_storage, "_storage", lambda alias: PrivateMemoryStorage())
    settings.REPORT_EXPORT_ALLOWED_STORAGE_ALIASES = ("private",)
    foreign = record(tenant_id=18, storage_alias="private",
                     storage_key=f"reports/unit-test/tenant-17/{uuid.uuid4().hex}.csv")

    with pytest.raises(ValidationError):
        object_storage.open_verified_export(foreign)


def test_corrupt_and_missing_object_exports_fail_without_local_fallback(tmp_path, monkeypatch, settings):
    backend = PrivateMemoryStorage()
    monkeypatch.setattr(object_storage, "_storage", lambda alias: backend)
    settings.REPORT_EXPORT_ROOT = tmp_path
    settings.REPORT_EXPORT_ALLOWED_STORAGE_ALIASES = ("private",)
    payload = b"original"
    key = f"reports/ns/tenant-17/{uuid.uuid4().hex}.csv"
    target = record(storage_alias="private", storage_key=key, file_size=len(payload),
                    file_sha256=hashlib.sha256(payload).hexdigest())
    backend.objects[key] = b"tampered"
    with pytest.raises(ValidationError, match="不可用或完整性校验失败"):
        object_storage.open_verified_export(target)
    backend.objects.pop(key)
    with pytest.raises(ValidationError):
        object_storage.open_verified_export(target)
    assert not list(tmp_path.rglob("*"))


def test_invalid_alias_and_provider_failure_are_generic_and_never_write_locally(tmp_path, monkeypatch, settings):
    settings.REPORT_EXPORT_ROOT = tmp_path
    settings.REPORT_EXPORT_ALLOWED_STORAGE_ALIASES = ("approved",)
    settings.REPORT_EXPORT_WRITE_STORAGE_ALIAS = "unapproved"
    target = record()
    with pytest.raises(ValidationError) as invalid_alias:
        object_storage.write_export(target, b"private bytes")
    assert "provider-secret" not in str(invalid_alias.value)

    class ExplodingStorage(PrivateMemoryStorage):
        def save(self, name, content):
            raise RuntimeError("provider-secret-token")

    monkeypatch.setattr(object_storage, "_storage", lambda alias: ExplodingStorage())
    settings.REPORT_EXPORT_WRITE_STORAGE_ALIAS = "approved"
    with pytest.raises(ValidationError) as write_error:
        object_storage.write_export(target, b"private bytes")
    assert "provider-secret-token" not in str(write_error.value)
    assert not list(tmp_path.rglob("*"))


def backup_record(pk, *, expires_at=None, **kwargs):
    return SimpleNamespace(
        pk=pk,
        id=pk,
        tenant_id=17,
        requested_by_id=4,
        report_type="sales_details",
        file_format="csv",
        storage_alias="private",
        storage_key=f"reports/ns/tenant-17/{uuid.uuid4().hex}.csv",
        file_size=8,
        file_sha256=hashlib.sha256(b"contents").hexdigest(),
        content_type="text/csv; charset=utf-8",
        expires_at=expires_at,
        **kwargs,
    )


def test_backup_package_copies_and_verifies_export(tmp_path, monkeypatch):
    payload = b"contents"
    monkeypatch.setattr(export_backup, "open_verified_export", lambda item: io.BytesIO(payload))
    output = tmp_path / "package"

    manifest = export_backup.build_package([backup_record(42)], output)

    assert manifest["requires_paired_database_snapshot"] is True
    assert manifest["exports"][0]["state"] == "verified"
    assert export_backup.verify_package(output) == manifest
    assert (output / "export-42.bin").read_bytes() == payload


def test_expired_backup_keeps_metadata_without_reading_body(tmp_path, monkeypatch):
    def should_not_open(_record):
        raise AssertionError("expired export body must not be read")

    monkeypatch.setattr(export_backup, "open_verified_export", should_not_open)
    expired = backup_record(43, expires_at=timezone.now() - timedelta(seconds=1))

    manifest = export_backup.build_package([expired], tmp_path / "expired")

    entry = manifest["exports"][0]
    assert entry["state"] == "expired_metadata_only"
    assert "package_file" not in entry
    assert not (tmp_path / "expired" / "export-43.bin").exists()
    assert export_backup.verify_package(tmp_path / "expired") == manifest


def test_backup_verifier_rejects_corrupted_package_file(tmp_path, monkeypatch):
    monkeypatch.setattr(export_backup, "open_verified_export", lambda item: io.BytesIO(b"contents"))
    package = tmp_path / "corrupt"
    export_backup.build_package([backup_record(44)], package)
    (package / "export-44.bin").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="integrity mismatch"):
        export_backup.verify_package(package)


@pytest.mark.django_db
def test_http_download_rechecks_revoked_permission_before_opening_storage(tmp_path, settings, monkeypatch):
    settings.REPORT_EXPORT_ROOT = tmp_path / "exports"
    tenant, _, store, _ = create_scope("object-storage-download-revoke")
    create_order(tenant, store, "object-storage-download-revoke")
    user = user_for(tenant, "object-storage-download-revoke-user")
    _report_access(user, "sales_management.view", "sales_management.export", "reports.export", "reports.download")
    client = client_for(user)
    config = _config("sales", ["store_id"], ["order_count"])
    response = client.post("/api/report/exports/", {
        "report_type": "self_service", "filters": {"config": config},
    }, format="json")
    assert response.status_code == 201
    export_id = response.data["data"]["id"]
    grant_response = client.post(f"/api/report/exports/{export_id}/download/", {}, format="json")
    assert grant_response.status_code == 200
    token = grant_response.data["data"]["download_reference"].split("token=", 1)[1]

    def must_not_open(_record):
        raise AssertionError("storage.open was reached after permission revocation")

    monkeypatch.setattr(export_services, "open_verified_export", must_not_open)
    permission = Permission.objects.get(code="reports.download")
    binding = UserRole.objects.get(tenant=tenant, user=user, role__permissions=permission)
    binding.role.permissions.remove(permission)
    DataScope.objects.filter(tenant=tenant, role=binding.role).delete()

    denied = client.get(f"/api/report/exports/{export_id}/file/", {"token": token})
    assert denied.status_code == 403
