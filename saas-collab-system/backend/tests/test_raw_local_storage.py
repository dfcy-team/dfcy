import os
import stat
from collections import namedtuple

import pytest
from django.core.files.base import ContentFile

from apps.integrations.raw_local_storage import (
    MAX_OBJECT_BYTES,
    PrivateRawLocalStorage,
    RawLocalStorageError,
)


KEY = "raw/test-ns/tenant-42/0123456789abcdef0123456789abcdef.json.gz"


def storage(root, **kwargs):
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != "nt":
        root.chmod(0o700)
    return PrivateRawLocalStorage(str(root), "test-ns", **{"min_free_bytes": 0, **kwargs})


def test_roundtrip_and_private_modes(tmp_path):
    backend = storage(tmp_path / "private")
    payload = b"synthetic gzip payload"
    assert backend.save(KEY, ContentFile(payload)) == KEY
    with backend.open(KEY, "rb") as source:
        assert source.read() == payload
    assert backend.open(KEY).read() == payload
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "private" / KEY).stat().st_mode) == 0o600
        assert stat.S_IMODE((tmp_path / "private" / "raw").stat().st_mode) == 0o700


def test_repeated_key_never_overwrites_existing_object(tmp_path):
    backend = storage(tmp_path / "private")
    backend.save(KEY, ContentFile(b"first"))
    with pytest.raises(RawLocalStorageError, match="already exists"):
        backend.save(KEY, ContentFile(b"replacement"))
    assert backend.open(KEY).read() == b"first"
    assert not list((tmp_path / "private").rglob(".raw-*.tmp"))


def test_capacity_reserve_fails_closed(tmp_path, monkeypatch):
    backend = storage(tmp_path / "private", min_free_bytes=100)
    Usage = namedtuple("Usage", "total used free")
    monkeypatch.setattr("apps.integrations.raw_local_storage.shutil.disk_usage",
                        lambda _path: Usage(1000, 950, 50))
    with pytest.raises(RawLocalStorageError, match="capacity reserve"):
        backend.save(KEY, ContentFile(b"x"))
    assert not list((tmp_path / "private").rglob("*.json.gz"))


def test_write_failure_leaves_no_completed_object_or_temp_file(tmp_path, monkeypatch):
    backend = storage(tmp_path / "private")
    real_fsync = os.fsync
    def fail_file_fsync(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError("disk write failure with private detail")
        return real_fsync(fd)
    monkeypatch.setattr("apps.integrations.raw_local_storage.os.fsync", fail_file_fsync)
    with pytest.raises(RawLocalStorageError, match="stored safely") as error:
        backend.save(KEY, ContentFile(b"payload"))
    assert "private detail" not in str(error.value)
    assert not list((tmp_path / "private").rglob("*.json.gz"))
    assert not list((tmp_path / "private").rglob(".raw-*.tmp"))


@pytest.mark.parametrize("key", [
    "../test-ns/tenant-42/0123456789abcdef0123456789abcdef.json.gz",
    "raw/test-ns/tenant-42/../0123456789abcdef0123456789abcdef.json.gz",
    "raw/other/tenant-42/0123456789abcdef0123456789abcdef.json.gz",
    "raw/test-ns/tenant-x/0123456789abcdef0123456789abcdef.json.gz",
    "raw/test-ns/tenant-42/ABCDEF0123456789abcdef0123456789.json.gz",
])
def test_malicious_or_malformed_keys_are_rejected(tmp_path, key):
    backend = storage(tmp_path / "private")
    with pytest.raises(ValueError, match="Invalid RAW object key"):
        backend.save(key, ContentFile(b"ignored"))


def test_symlink_root_and_parent_are_rejected(tmp_path):
    root = tmp_path / "private"
    root.mkdir(mode=0o700)
    if hasattr(root, "symlink_to"):
        link = tmp_path / "root-link"
        try:
            link.symlink_to(root, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable")
        with pytest.raises(ValueError, match="existing private directory"):
            PrivateRawLocalStorage(str(link), "test-ns", min_free_bytes=0)

    backend = PrivateRawLocalStorage(str(root), "test-ns", min_free_bytes=0)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    (root / "raw").symlink_to(outside, target_is_directory=True)
    with pytest.raises(RawLocalStorageError, match="stored safely"):
        backend.save(KEY, ContentFile(b"payload"))
    assert not list(outside.iterdir())


def test_size_and_non_regular_objects_are_rejected(tmp_path):
    backend = storage(tmp_path / "private")
    with pytest.raises(RawLocalStorageError, match="size limit"):
        backend.save(KEY, ContentFile(b"x" * (MAX_OBJECT_BYTES + 1)))
    target = tmp_path / "private" / KEY
    backend.save(KEY, ContentFile(b"initial"))
    with target.open("wb") as oversized:
        oversized.truncate(MAX_OBJECT_BYTES + 1)
    with pytest.raises(RawLocalStorageError, match="invalid type or size"):
        backend.open(KEY)
    target.unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(target, 0o600)
        with pytest.raises(RawLocalStorageError, match="invalid type or size"):
            backend.open(KEY)
    else:
        target.mkdir()
        with pytest.raises(RawLocalStorageError, match="invalid type or size"):
            backend.open(KEY)


@pytest.mark.skipif(os.name == "nt", reason="Windows ACLs are outside POSIX mode-bit checks")
def test_open_rejects_non_private_file_mode(tmp_path):
    backend = storage(tmp_path / "private")
    backend.save(KEY, ContentFile(b"private payload"))
    target = tmp_path / "private" / KEY
    target.chmod(0o644)
    with pytest.raises(RawLocalStorageError, match="invalid type or size"):
        backend.open(KEY)


def test_location_must_be_absolute_existing_and_private(tmp_path):
    with pytest.raises(ValueError, match="absolute directory"):
        PrivateRawLocalStorage("relative", "test-ns", min_free_bytes=0)
    with pytest.raises(ValueError, match="existing private directory"):
        PrivateRawLocalStorage(str(tmp_path / "missing"), "test-ns", min_free_bytes=0)
    root = tmp_path / "not-private"
    root.mkdir()
    if os.name != "nt":
        root.chmod(0o750)
        with pytest.raises(ValueError, match="existing private directory"):
            PrivateRawLocalStorage(str(root), "test-ns", min_free_bytes=0)


def test_failure_after_publication_preserves_object_and_cleans_temp(tmp_path, monkeypatch):
    backend = storage(tmp_path / "private")
    original_link = os.link
    def publish_then_fail(*args, **kwargs):
        original_link(*args, **kwargs)
        raise OSError("simulated failure after publication")
    monkeypatch.setattr(os, "link", publish_then_fail)
    with pytest.raises(RawLocalStorageError, match="stored safely"):
        backend.save(KEY, ContentFile(b"preserved"))
    assert backend.open(KEY).read() == b"preserved"
    assert not list((tmp_path / "private").rglob(".raw-*.tmp"))


def test_cross_filesystem_subdirectory_is_rejected(tmp_path, monkeypatch):
    from types import SimpleNamespace
    backend = storage(tmp_path / "private")
    subdir = tmp_path / "private" / "raw"
    subdir.mkdir(mode=0o700)
    original_info = subdir.stat()
    def different_device(info):
        return SimpleNamespace(st_mode=info.st_mode, st_dev=info.st_dev + 1,
                               st_file_attributes=getattr(info, "st_file_attributes", 0))
    if os.name == "nt":
        original = os.lstat
        def changed(path, *args, **kwargs):
            info = original(path, *args, **kwargs)
            return different_device(info) if os.fspath(path) == str(subdir) else info
        monkeypatch.setattr(os, "lstat", changed)
    else:
        original = os.fstat
        def changed(fd):
            info = original(fd)
            return different_device(info) if info.st_ino == original_info.st_ino else info
        monkeypatch.setattr(os, "fstat", changed)
    with pytest.raises(RawLocalStorageError, match="stored safely"):
        backend.save(KEY, ContentFile(b"do not write to an unmeasured disk"))
    assert not list(subdir.rglob("*.json.gz"))
