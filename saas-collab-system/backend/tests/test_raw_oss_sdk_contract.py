"""Exercise the actual SDK serializer and transport without sending any network IO."""
import io
import json

import requests
import pytest
from django.core.files.base import ContentFile
from django.test import override_settings

from apps.integrations.raw_oss_storage import PrivateRawOSSStorage
from tests.test_mock_sync_isolation import context  # noqa: F401


def test_real_sdk_private_upload_and_download_contract(tmp_path, monkeypatch):
    credential_file = tmp_path / "credentials.json"
    credential_file.write_text(json.dumps({"access_key_id": "offline-test-id",
                                         "access_key_secret": "offline-test-secret"}), encoding="utf-8")
    credential_file.chmod(0o600)
    calls = []
    closes = []
    response_closes = []
    payload = b"synthetic-gzip-bytes"

    def fake_request(session, method, url, **kwargs):
        calls.append((method, url, kwargs))
        if method == "PUT":
            body = kwargs["data"]
            uploaded = body if isinstance(body, bytes) else b"".join(body)
            assert uploaded == payload
        response = requests.Response()
        response.status_code = 200
        response.reason = "OK"
        response.url = url
        data = payload if method == "GET" else b""
        response.headers.update({"Content-Length": str(len(data)), "ETag": '"offline"',
                                 "x-oss-request-id": "offline-test-request"})
        response.raw = io.BytesIO(data)
        return response

    original_close = requests.Session.close
    def track_close(session):
        closes.append(session)
        original_close(session)

    original_response_close = requests.Response.close
    def track_response_close(response):
        response_closes.append(response)
        original_response_close(response)

    monkeypatch.setattr(requests.Session, "request", fake_request)
    monkeypatch.setattr(requests.Session, "close", track_close)
    monkeypatch.setattr(requests.Response, "close", track_response_close)
    storage = PrivateRawOSSStorage(endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        region="cn-hangzhou", bucket="offline-test-bucket", namespace="offline-test",
        credential_file=str(credential_file), connect_timeout=2, read_timeout=4)
    key = "raw/offline-test/tenant-1/" + "a" * 32 + ".json.gz"
    assert storage.save(key, ContentFile(payload)) == key
    with storage.open(key, "rb") as result:
        assert result.read() == payload

    assert [call[0] for call in calls] == ["PUT", "GET"]
    assert all(call[1].startswith("https://offline-test-bucket.oss-cn-hangzhou.aliyuncs.com/") for call in calls)
    headers = {key.lower(): value for key, value in calls[0][2]["headers"].items()}
    assert headers["x-oss-object-acl"] == "private"
    assert headers["x-oss-server-side-encryption"] == "AES256"
    assert headers["x-oss-forbid-overwrite"] == "true"
    assert "authorization" in headers
    assert all(call[2]["verify"] is True and call[2]["allow_redirects"] is False for call in calls)
    assert all(call[2]["timeout"] == (2, 4) for call in calls)
    assert len(closes) == 2
    assert len(response_closes) == 2


@pytest.mark.django_db
def test_archive_roundtrip_through_registered_oss_backend(context, tmp_path, monkeypatch):
    from apps.integrations.models import SyncRun
    from apps.integrations.raw_services import archive_raw_page, load_raw_payload
    _, job = context
    credential_file = tmp_path / "credentials.json"
    credential_file.write_text(json.dumps({"access_key_id": "offline-test-id",
                                         "access_key_secret": "offline-test-secret"}), encoding="utf-8")
    credential_file.chmod(0o600)
    objects = {}

    def fake_request(session, method, url, **kwargs):
        if method == "PUT":
            body = kwargs["data"]
            objects[url] = body if isinstance(body, bytes) else b"".join(body)
            data = b""
        else:
            assert method == "GET"
            data = objects[url]
        response = requests.Response()
        response.status_code, response.reason, response.url = 200, "OK", url
        response.headers.update({"Content-Length": str(len(data)), "ETag": '"offline"'})
        response.raw = io.BytesIO(data)
        return response

    monkeypatch.setattr(requests.Session, "request", fake_request)
    storage_config = {"raw_oss": {
        "BACKEND": "apps.integrations.raw_oss_storage.PrivateRawOSSStorage",
        "OPTIONS": {"endpoint": "https://oss-cn-hangzhou.aliyuncs.com",
                    "region": "cn-hangzhou", "bucket": "offline-test-bucket",
                    "namespace": "offline-test", "credential_file": str(credential_file)},
    }}
    run = SyncRun.objects.create(tenant=job.tenant, sync_job=job,
        run_id="oss-roundtrip", idempotency_key="oss-roundtrip")
    adapter = type("Adapter", (), {"adapter_name": "offline", "authorization": None})()
    with override_settings(STORAGES=storage_config, RAW_PAYLOAD_STORAGE_ALIAS="raw_oss",
                           RAW_PAYLOAD_STORAGE_NAMESPACE="offline-test"):
        entry = archive_raw_page(job, run, adapter, "", {"records": [{"id": "synthetic"}]})
        entry.refresh_from_db()
        assert entry.payload == {}
        assert entry.payload_storage_alias == "raw_oss"
        assert load_raw_payload(entry)["records"] == [{"id": "synthetic"}]
        assert len(objects) == 1
