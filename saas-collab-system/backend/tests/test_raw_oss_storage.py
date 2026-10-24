import io
import json
import os
import stat

import pytest
from django.core.files.base import ContentFile
from alibabacloud_oss_v2 import models

from apps.integrations import raw_oss_storage as storage_module
from apps.integrations.raw_oss_storage import (
    MAX_OBJECT_BYTES,
    PrivateRawOSSStorage,
    RawOSSStorageError,
)


KEY = "raw/phase1/tenant-7/0123456789abcdef0123456789abcdef.json.gz"


class FakeTransport:
    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.closed = False
        self.__class__.instances.append(self)

    def close(self):
        self.closed = True


class TrackingStream:
    def __init__(self, data):
        self.data = data
        self.was_closed = False

    def iter_bytes(self, **kwargs):
        block_size = kwargs["block_size"]
        for start in range(0, len(self.data), block_size):
            yield self.data[start:start + block_size]

    def close(self):
        self.was_closed = True


class FakeClient:
    instances = []
    put_error = None
    get_error = None
    download = b"gzip bytes"

    def __init__(self, config):
        self.config = config
        self.put_requests = []
        self.get_requests = []
        self.stream = None
        self.__class__.instances.append(self)

    def put_object(self, request):
        self.put_requests.append(request)
        if self.put_error:
            raise self.put_error
        return object()

    def get_object(self, request):
        self.get_requests.append(request)
        if self.get_error:
            raise self.get_error
        self.stream = TrackingStream(self.download)
        return models.GetObjectResult(body=self.stream)


@pytest.fixture(autouse=True)
def fake_sdk(monkeypatch):
    FakeTransport.instances = []
    FakeClient.instances = []
    FakeClient.put_error = None
    FakeClient.get_error = None
    FakeClient.download = b"gzip bytes"
    monkeypatch.setattr(storage_module.transport, "RequestsHttpClient", FakeTransport)
    monkeypatch.setattr(storage_module, "Client", FakeClient)


def make_storage(tmp_path):
    credentials_file = tmp_path / "oss-credentials.json"
    credentials_file.write_text(json.dumps({"access_key_id": "id-a", "access_key_secret": "secret-a"}))
    if os.name != "nt":
        credentials_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    return PrivateRawOSSStorage(
        endpoint="https://oss-cn-hangzhou.aliyuncs.com",
        region="cn-hangzhou",
        bucket="raw-payloads",
        credential_file=credentials_file,
        namespace="phase1",
        connect_timeout=2,
        read_timeout=9,
    ), credentials_file


def test_save_uses_private_encrypted_non_overwrite_request_and_closes_transport(tmp_path):
    storage, _ = make_storage(tmp_path)
    assert storage.save(KEY, ContentFile(b"payload")) == KEY

    request = FakeClient.instances[0].put_requests[0]
    assert request.bucket == "raw-payloads"
    assert request.key == KEY
    assert request.body == b"payload"
    assert request.content_length == 7
    assert request.acl == "private"
    assert request.server_side_encryption == "AES256"
    assert request.forbid_overwrite is True
    assert FakeClient.instances[0].config.retry_max_attempts == 1
    assert FakeClient.instances[0].config.disable_ssl is False
    assert FakeClient.instances[0].config.enabled_redirect is False
    assert FakeTransport.instances[0].kwargs == {
        "connect_timeout": 2,
        "readwrite_timeout": 9,
        "enabled_redirect": False,
        "insecure_skip_verify": False,
    }
    assert FakeTransport.instances[0].closed


def test_open_is_read_only_bounded_and_closes_stream_and_transport(tmp_path):
    storage, _ = make_storage(tmp_path)
    with storage.open(KEY, "rb") as result:
        assert result.read() == b"gzip bytes"
    client = FakeClient.instances[0]
    assert client.get_requests[0].bucket == "raw-payloads"
    assert client.get_requests[0].key == KEY
    assert client.stream.was_closed
    assert FakeTransport.instances[0].closed
    with pytest.raises(ValueError):
        storage.open(KEY, "wb")


def test_credentials_are_reloaded_for_each_operation(tmp_path):
    storage, credential_file = make_storage(tmp_path)
    storage.save(KEY, ContentFile(b"one"))
    credential_file.write_text(json.dumps({"access_key_id": "id-b", "access_key_secret": "secret-b", "security_token": "token-b"}))
    if os.name != "nt":
        credential_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    storage.save(KEY, ContentFile(b"two"))

    providers = [client.config.credentials_provider.get_credentials() for client in FakeClient.instances]
    assert [(item.access_key_id, item.access_key_secret, item.security_token) for item in providers] == [
        ("id-a", "secret-a", None),
        ("id-b", "secret-b", "token-b"),
    ]


@pytest.mark.parametrize("endpoint", [
    "http://oss-cn-hangzhou.aliyuncs.com",
    "https://example.com",
    "https://oss-cn-hangzhou.aliyuncs.com:443",
    "https://oss-cn-hangzhou.aliyuncs.com/path",
    "https://oss-cn-hangzhou.aliyuncs.com/?x=1",
    "https://oss-cn-beijing.aliyuncs.com",
])
def test_rejects_noncanonical_endpoint(tmp_path, endpoint):
    _, credential_file = make_storage(tmp_path)
    with pytest.raises(ValueError):
        PrivateRawOSSStorage(endpoint, "cn-hangzhou", "raw-payloads", credential_file, "phase1")


@pytest.mark.parametrize("key", [
    "raw/other/tenant-7/0123456789abcdef0123456789abcdef.json.gz",
    "raw/phase1/tenant-7/sub/0123456789abcdef0123456789abcdef.json.gz",
    "raw/phase1/tenant-7/ABCDEF0123456789abcdef0123456789.json.gz",
    "raw/phase1/tenant-7/0123456789abcdef0123456789abcdef.json.gz?x=1",
])
def test_rejects_keys_outside_namespace_or_shape_without_network(tmp_path, key):
    storage, _ = make_storage(tmp_path)
    with pytest.raises(ValueError):
        storage.save(key, ContentFile(b"x"))
    assert FakeClient.instances == []


def test_rejects_oversize_upload_without_network(tmp_path):
    storage, _ = make_storage(tmp_path)
    with pytest.raises(RawOSSStorageError, match="size limit"):
        storage.save(KEY, ContentFile(b"x" * (MAX_OBJECT_BYTES + 1)))
    assert FakeClient.instances == []


def test_upload_failure_hides_provider_details_and_still_closes_transport(tmp_path):
    storage, _ = make_storage(tmp_path)
    FakeClient.put_error = RuntimeError("secret-a provider response body")
    with pytest.raises(RawOSSStorageError, match="upload failed") as error:
        storage.save(KEY, ContentFile(b"payload"))
    assert "secret-a" not in str(error.value)
    assert error.value.__cause__ is None
    assert FakeTransport.instances[0].closed


def test_download_failure_hides_provider_details_and_closes_transport(tmp_path):
    storage, _ = make_storage(tmp_path)
    FakeClient.get_error = RuntimeError("secret-a provider response body")
    with pytest.raises(RawOSSStorageError, match="download failed") as error:
        storage.open(KEY)
    assert "secret-a" not in str(error.value)
    assert error.value.__cause__ is None
    assert FakeTransport.instances[0].closed


def test_credentials_validation_does_not_disclose_values(tmp_path):
    storage, credential_file = make_storage(tmp_path)
    credential_file.write_text(json.dumps({"access_key_id": "secret-id", "access_key_secret": "secret-value"}))
    if os.name != "nt":
        credential_file.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP)
    else:
        # Windows does not expose POSIX mode bits; exercise the same sanitized
        # failure behavior with malformed credential content there.
        credential_file.write_text("not-json")
    with pytest.raises(RawOSSStorageError, match="credentials") as error:
        storage.save(KEY, ContentFile(b"payload"))
    assert "secret-id" not in str(error.value)
    assert "secret-value" not in str(error.value)
    assert FakeClient.instances == []


def test_download_size_is_bounded_and_stream_is_closed(tmp_path):
    storage, _ = make_storage(tmp_path)
    FakeClient.download = b"x" * (MAX_OBJECT_BYTES + 1)
    with pytest.raises(RawOSSStorageError, match="size limit"):
        storage.open(KEY)
    assert FakeClient.instances[0].stream.was_closed
    assert FakeTransport.instances[0].closed


def test_unsupported_storage_operations_are_not_available(tmp_path):
    storage, _ = make_storage(tmp_path)
    with pytest.raises(NotImplementedError):
        storage.url(KEY)
    with pytest.raises(NotImplementedError):
        storage.delete(KEY)
    with pytest.raises(NotImplementedError):
        storage.listdir("")


def test_credential_open_requests_nonblocking_when_supported(tmp_path, monkeypatch):
    storage, _ = make_storage(tmp_path)
    flag = getattr(os, "O_NONBLOCK", 0x40000000)
    monkeypatch.setattr(os, "O_NONBLOCK", flag, raising=False)
    def fake_open(path, flags):
        assert flags & flag
        raise OSError("simulated nonregular credential input")
    monkeypatch.setattr(os, "open", fake_open)
    with pytest.raises(RawOSSStorageError, match="credentials"):
        storage._load_credentials()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="POSIX FIFO is unavailable")
def test_fifo_credentials_are_rejected_without_waiting_for_writer(tmp_path):
    # Run in a bounded child so a regression cannot hang the entire test runner.
    import subprocess
    import sys
    storage, credential_file = make_storage(tmp_path)
    credential_file.unlink()
    os.mkfifo(credential_file)
    script = (
        "from apps.integrations.raw_oss_storage import PrivateRawOSSStorage, RawOSSStorageError; "
        "import sys; s = PrivateRawOSSStorage(endpoint='https://oss-cn-hangzhou.aliyuncs.com', "
        "region='cn-hangzhou', bucket='test-bucket', namespace='phase1', credential_file=sys.argv[1]); "
        "\ntry: s._load_credentials()\nexcept RawOSSStorageError: sys.exit(0)\nelse: sys.exit(1)"
    )
    result = subprocess.run([sys.executable, "-c", script, str(credential_file)],
                            capture_output=True, timeout=10)
    assert result.returncode == 0
