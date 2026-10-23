import json
from unittest.mock import patch

import pytest
from django.test import override_settings

from apps.demo_sync.importer import _read_bundle, _value, SnapshotImportError
from apps.demo_sync.pipeline import RESOURCES
from apps.demo_sync.service import ReadonlyClient, SyncFailure


def test_bundle_duplicate_resource_and_traversal_rejected(tmp_path):
    entries = [{"resource": r, "path": r + ".jsonl", "count": 0, "sha256": ""} for r in RESOURCES]
    manifest = {"schema_version": "demo-snapshot.v1", "deidentified": True, "files": entries + [entries[0]]}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SnapshotImportError, match="exactly once"):
        _read_bundle(tmp_path)
    manifest["files"] = entries
    entries[0]["path"] = "../escape.jsonl"
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(SnapshotImportError, match="unsafe"):
        _read_bundle(tmp_path)


def test_non_finite_decimal_rejected():
    for value in ("NaN", "Infinity", "-Infinity"):
        with pytest.raises(SnapshotImportError, match="non-finite"):
            _value("order_total_amount", value)


@override_settings(DEMO_DATA_SYNC_ALLOWED_HOSTS=["approved.example"])
def test_readonly_transport_caps_pages_disables_redirects_and_rejects_auth(monkeypatch):
    monkeypatch.setenv("DEMO_TEST_ID", "synthetic-client")
    monkeypatch.setenv("DEMO_TEST_SECRET", "synthetic-secret")
    monkeypatch.setenv("DEMO_TEST_MASK", "synthetic-masking-secret-at-least-32-characters")
    client = ReadonlyClient({"url": "https://approved.example", "client_id_env": "DEMO_TEST_ID",
                             "client_secret_env": "DEMO_TEST_SECRET", "masking_key_env": "DEMO_TEST_MASK"})
    assert client.session.trust_env is False

    class Response:
        status_code = 200

        def iter_content(self, size):
            yield b'{"success":true,"data":{"items":[],"has_more":false,"next_cursor":null}}'

        def close(self):
            pass

    with patch.object(client.session, "get", return_value=Response()) as get, patch("apps.demo_sync.service.time.sleep"):
        assert client.fetch("products", {"limit": 1000})["items"] == []
        assert get.call_args.kwargs["params"]["limit"] == 100
        assert get.call_args.kwargs["allow_redirects"] is False
    rejected = Response()
    rejected.status_code = 403
    with patch.object(client.session, "get", return_value=rejected) as get:
        with pytest.raises(SyncFailure, match="SOURCE_ACCESS_DENIED"):
            client.fetch("products", {})
        assert get.call_count == 1
    client.close()
