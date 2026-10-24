"""Real local filesystem plus database integration; no cloud resources."""
import shutil

import pytest
from django.test import override_settings

from apps.integrations.models import SyncRun
from apps.integrations.raw_services import archive_raw_page, load_raw_payload, replay_raw_envelope
from tests.test_mock_sync_isolation import context  # noqa: F401

pytestmark = pytest.mark.django_db


def test_local_archive_database_reference_and_restore(context, tmp_path):
    _, job = context
    root = tmp_path / "private-raw"
    root.mkdir(mode=0o700)
    config = {"raw_local": {
        "BACKEND": "apps.integrations.raw_local_storage.PrivateRawLocalStorage",
        "OPTIONS": {"location": str(root), "namespace": "local-test", "min_free_bytes": 0},
    }}
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job,
        run_id="local-roundtrip", idempotency_key="local-roundtrip")
    adapter = type("Adapter", (), {
        "adapter_name": "offline", "authorization": None,
        "validate_configuration": lambda self, sync_job: None,
        "bind_run": lambda self, sync_run: None,
        "normalize_record": lambda self, record: record,
        "validate_record": lambda self, record: True,
        "persist_record": lambda self, sync_job, record: {"action": "created"},
    })()
    with override_settings(STORAGES=config, RAW_PAYLOAD_STORAGE_ALIAS="raw_local",
                           RAW_PAYLOAD_STORAGE_NAMESPACE="local-test"):
        entry = archive_raw_page(job, run, adapter, "", {"records": [{"id": "测试记录"}]})
        entry.refresh_from_db()
        assert entry.payload == {}
        assert entry.payload_storage_alias == "raw_local"
        assert (root / entry.payload_object_key).is_file()
        assert load_raw_payload(entry)["records"] == [{"id": "测试记录"}]
        assert replay_raw_envelope(entry, adapter)["created"] == 1

    restored_root = tmp_path / "restored-private-raw"
    shutil.copytree(root, restored_root)
    config["raw_local"]["OPTIONS"]["location"] = str(restored_root)
    # After a backup restore, the alias/namespace/key remain stable while the
    # private root location can be changed; turning off writes must preserve reads.
    with override_settings(STORAGES=config, RAW_PAYLOAD_STORAGE_ALIAS="",
                           RAW_PAYLOAD_STORAGE_NAMESPACE="local-test"):
        assert load_raw_payload(entry)["records"] == [{"id": "测试记录"}]
