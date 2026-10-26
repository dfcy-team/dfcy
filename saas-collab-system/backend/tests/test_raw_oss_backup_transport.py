import io
from pathlib import Path

import pytest

from apps.integrations.raw_oss_backup_transport import publish_package, fetch_package
from tests import test_raw_oss_backup as backup_tests


class MemoryStore:
    bucket = 'independent-backup'

    def __init__(self):
        self.objects = {}

    def put(self, key, data):
        assert key not in self.objects
        self.objects[key] = data

    def open(self, key):
        return io.BytesIO(self.objects[key])


@pytest.fixture
def builder():
    helper = backup_tests.RawOssBackupTests()
    helper.setUp()
    try:
        yield helper
    finally:
        helper.tearDown()


@pytest.mark.parametrize('empty', [False, True])
def test_independent_backup_recovers_without_source(builder, empty):
    package, _ = builder.build(rows=[] if empty else None)
    store = MemoryStore()
    published = publish_package(package, store, 'original-raw')
    builder.blobs.clear()  # Recovery uses only the independent backup.
    output = Path(builder.root) / 'recovered'
    result = fetch_package(published['backup_id'], store, output, min_free_bytes=0)
    assert result['status'] == 'fetched_verified'
    for original in Path(package).rglob('*'):
        if original.is_file():
            assert (output / original.relative_to(package)).read_bytes() == original.read_bytes()


def test_corrupt_backup_never_publishes_recovery(builder):
    package, _ = builder.build()
    store = MemoryStore()
    published = publish_package(package, store, 'original-raw')
    key = next(k for k in store.objects if '/chunks/' in k)
    store.objects[key] += b'tampered'
    output = Path(builder.root) / 'recovered'
    with pytest.raises(ValueError):
        fetch_package(published['backup_id'], store, output, min_free_bytes=0)
    assert not output.exists()
    assert not list(output.parent.glob('.oss-fetch-*'))


def test_same_bucket_is_rejected_before_writing(builder):
    package, _ = builder.build()
    store = MemoryStore()
    with pytest.raises(ValueError, match='independent'):
        publish_package(package, store, store.bucket)
    assert store.objects == {}


def test_failed_upload_has_no_complete_marker(builder):
    package, _ = builder.build()
    store = MemoryStore()
    def fail(key, data):
        raise OSError('synthetic failure')
    store.put = fail
    with pytest.raises(OSError):
        publish_package(package, store, 'original-raw')
    assert not any(k.endswith('complete.json') for k in store.objects)
