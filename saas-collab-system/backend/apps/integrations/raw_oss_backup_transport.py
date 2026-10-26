"""Explicit independent-bucket transport; bounded chunks, GET/PUT only.

An upload is discoverable only by its returned backup ID. No listing or deletion.
Retention is reported by the offline package command, never enforced here.
"""
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
import uuid
from contextlib import contextmanager

from .raw_backup import _ordinary_dir, _ordinary_file, _ensure_capacity, _sha256_file
from .raw_oss_storage import PrivateRawOSSStorage, RawOSSStorageError

CHUNK = 8 * 1024 * 1024
INDEX_LIMIT = 32 * 1024 * 1024
MAX_LINE = 16384
ID = re.compile(r'^[0-9a-f]{32}$')


def safe_relative(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or value.startswith('/') or any(p in ('', '.', '..') for p in value.split('/'))):
        raise ValueError('Invalid backup path.')
    return PurePosixPath(value)


class _Reader(io.RawIOBase):
    def __init__(self, chunks):
        super().__init__()
        self.chunks, self.pending = iter(chunks), b''

    def readable(self):
        return True

    def readinto(self, target):
        if not self.pending:
            self.pending = next(self.chunks, b'')
        n = min(len(target), len(self.pending))
        target[:n], self.pending = self.pending[:n], self.pending[n:]
        return n


class OSSBackupStore:
    """Only private AES256 immutable writes. Configuration contains file paths, not keys."""
    def __init__(self, *, endpoint, region, bucket, credential_file, namespace='backup'):
        self.storage = PrivateRawOSSStorage(endpoint, region, bucket, credential_file, namespace)
        self.bucket = bucket

    @contextmanager
    def open(self, key):
        safe_relative(key)
        from alibabacloud_oss_v2 import models
        client, http = self.storage._client()
        body = None
        try:
            body = client.get_object(models.GetObjectRequest(bucket=self.bucket, key=key)).body
            with io.BufferedReader(_Reader(body.iter_bytes(block_size=65536))) as source:
                yield source
        except Exception:
            raise RawOSSStorageError('Backup object read failed.') from None
        finally:
            if body is not None:
                body.close()
            http.close()

    def put(self, key, data):
        safe_relative(key)
        if len(data) > INDEX_LIMIT:
            raise ValueError('Backup chunk exceeds limit.')
        from alibabacloud_oss_v2 import models
        client, http = self.storage._client()
        try:
            client.put_object(models.PutObjectRequest(
                bucket=self.bucket, key=key, body=data, content_length=len(data),
                acl='private', server_side_encryption='AES256', forbid_overwrite=True))
        except Exception:
            raise RawOSSStorageError('Backup object upload failed.') from None
        finally:
            http.close()
        with self.open(key) as source:
            actual = source.read(len(data) + 1)
        if hashlib.sha256(actual).digest() != hashlib.sha256(data).digest():
            raise ValueError('Backup object readback mismatch.')


def publish_package(package, store, source_bucket):
    from .raw_oss_backup import verify_package
    if not source_bucket or source_bucket == store.bucket:
        raise ValueError('An independent backup bucket is required.')
    package = Path(package)
    verify_package(package)
    backup_id = uuid.uuid4().hex
    prefix = 'raw-backups/' + backup_id + '/'
    # Index is capped independently of database size; chunks stay bounded.
    index = io.BytesIO()
    count = 0
    for root, directories, files in os.walk(package, followlinks=False):
        for directory in directories:
            _ordinary_dir(Path(root) / directory, 'Package directory')
        for filename in sorted(files):
            path = Path(root) / filename
            _ordinary_file(path, 'Package file')
            rel = path.relative_to(package).as_posix()
            safe_relative(rel)
            original_hash = _sha256_file(path, 'Package file')
            digest, total, chunks = hashlib.sha256(), 0, 0
            with path.open('rb') as source:
                while True:
                    data = source.read(CHUNK)
                    if not data:
                        break
                    key = prefix + 'chunks/' + str(count) + '/' + str(chunks)
                    store.put(key, data)
                    digest.update(data)
                    total += len(data)
                    chunks += 1
            if digest.hexdigest() != original_hash or _sha256_file(path, 'Package file') != original_hash:
                raise ValueError('Package changed during upload; upload remains incomplete.')
            row = {'path': rel, 'bytes': total, 'sha256': digest.hexdigest(), 'chunks': chunks, 'number': count}
            index.write((json.dumps(row, separators=(',', ':')) + '\n').encode())
            if index.tell() > INDEX_LIMIT:
                raise ValueError('Backup index exceeds limit; upload remains incomplete.')
            count += 1
    # Detect changes in verified package during upload, before publishing completion.
    verify_package(package)
    index_bytes = index.getvalue()
    store.put(prefix + 'index.jsonl', index_bytes)
    marker = {'format': 'raw-oss-backup-transport.v1', 'backup_id': backup_id,
              'file_count': count, 'index_bytes': len(index_bytes),
              'index_sha256': hashlib.sha256(index_bytes).hexdigest()}
    store.put(prefix + 'complete.json', json.dumps(marker, sort_keys=True).encode())
    return {'status': 'published', 'backup_id': backup_id, 'file_count': count,
            'backup_bucket': store.bucket, 'deleted_objects': 0}


def fetch_package(backup_id, store, output, min_free_bytes=10737418240):
    from .raw_oss_backup import verify_package
    if type(min_free_bytes) is not int or min_free_bytes < 0:
        raise ValueError('Invalid free space reserve.')
    if not isinstance(backup_id, str) or not ID.fullmatch(backup_id):
        raise ValueError('Invalid backup ID.')
    output = Path(output)
    if output.exists() or output.is_symlink():
        raise ValueError('Restore destination must not exist.')
    _ordinary_dir(output.parent, 'Restore parent')
    prefix = 'raw-backups/' + backup_id + '/'
    with store.open(prefix + 'complete.json') as stream:
        marker_raw = stream.read(MAX_LINE + 1)
    if len(marker_raw) > MAX_LINE:
        raise ValueError('Invalid backup marker.')
    marker = json.loads(marker_raw)
    if marker.get('format') != 'raw-oss-backup-transport.v1' or marker.get('backup_id') != backup_id:
        raise ValueError('Invalid backup marker.')
    with store.open(prefix + 'index.jsonl') as stream:
        data = stream.read(INDEX_LIMIT + 1)
    if len(data) > INDEX_LIMIT or len(data) != marker['index_bytes'] or hashlib.sha256(data).hexdigest() != marker['index_sha256']:
        raise ValueError('Backup index mismatch.')
    stage = Path(tempfile.mkdtemp(prefix='.oss-fetch-', dir=output.parent))
    try:
        (stage / 'objects').mkdir(mode=0o700)
        count = 0
        for line in io.BytesIO(data):
            if len(line) > MAX_LINE:
                raise ValueError('Invalid index row.')
            row = json.loads(line)
            rel = safe_relative(row['path'])
            size, chunks = row['bytes'], row['chunks']
            if (type(size) is not int or size < 0 or type(chunks) is not int
                    or chunks != (size + CHUNK - 1) // CHUNK or row['number'] != count):
                raise ValueError('Invalid index counts.')
            target = stage.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            digest, total = hashlib.sha256(), 0
            _ensure_capacity(stage, size, min_free_bytes)
            with target.open('xb') as dest:
                os.chmod(target, 0o600)
                for number in range(chunks):
                    expected = min(CHUNK, size - total)
                    with store.open(prefix + 'chunks/' + str(count) + '/' + str(number)) as src:
                        chunk = src.read(expected + 1)
                    if len(chunk) != expected:
                        raise ValueError('Backup chunk length mismatch.')
                    dest.write(chunk)
                    digest.update(chunk)
                    total += len(chunk)
                dest.flush()
                os.fsync(dest.fileno())
            if total != size or digest.hexdigest() != row['sha256']:
                raise ValueError('Backup file checksum mismatch.')
            count += 1
        if count != marker['file_count']:
            raise ValueError('Backup file count mismatch.')
        verify_package(stage)
        if output.exists():
            raise ValueError('Restore destination already exists.')
        stage.rename(output)
        return {'status': 'fetched_verified', 'backup_id': backup_id, 'file_count': count}
    finally:
        if stage.exists():
            shutil.rmtree(stage)
