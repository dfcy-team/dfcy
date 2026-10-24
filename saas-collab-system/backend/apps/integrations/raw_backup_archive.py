"""Create an offline .tgz containing one SQL backup and a verified RAW package."""
import hashlib
import gzip
import os
import secrets
import shutil
import stat
import tarfile
import zlib

from .raw_backup import RawBackupError, _CHUNK, _fsync_dir, _ordinary_dir, _ordinary_file, _stat_signature, verify_backup


def _snapshot_tree(root):
    """Return stable ordinary files and directories; reject links/specials."""
    _ordinary_dir(root, "RAW package")
    result = {}
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        for name in dirs:
            path = os.path.join(current, name)
            info = _ordinary_dir(path, "RAW package directory")
            result[os.path.relpath(path, root).replace(os.sep, "/") + "/"] = _stat_signature(info)
        for name in files:
            path = os.path.join(current, name)
            info = _ordinary_file(path, "RAW package file")
            result[os.path.relpath(path, root).replace(os.sep, "/")] = _stat_signature(info)
    return result


def _hash_file(path, expected_signature=None):
    info = _ordinary_file(path, "Archive source")
    if expected_signature is not None and _stat_signature(info) != expected_signature:
        raise RawBackupError("An archive source changed before reading.")
    digest, size = hashlib.sha256(), 0
    with open(path, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if expected_signature is not None and _path_signature(opened) != _path_signature(info):
            raise RawBackupError("An archive source changed while opening.")
        while True:
            chunk = stream.read(_CHUNK)
            if not chunk:
                break
            digest.update(chunk)
            size += len(chunk)
        if _stat_signature(opened) != _stat_signature(os.fstat(stream.fileno())):
            raise RawBackupError("An archive source changed while reading.")
    return size, digest.hexdigest()


def _path_signature(info):
    # On Windows, lstat/fstat can report different creation/change timestamps.
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


class _HashingReader:
    """Hash exactly the bytes tarfile consumes and recheck available space per read."""
    def __init__(self, stream, output_parent, reserve):
        self.stream, self.output_parent, self.reserve = stream, output_parent, reserve
        self.digest, self.bytes_read = hashlib.sha256(), 0

    def read(self, size=-1):
        chunk = self.stream.read(min(size, _CHUNK) if size >= 0 else _CHUNK)
        if chunk:
            self.digest.update(chunk)
            self.bytes_read += len(chunk)
            _capacity(self.output_parent, self.reserve)
        return chunk


def create_archive(package_dir, database_backup_path, output_path, min_free_bytes=10737418240):
    """Create a private, non-overwriting tar.gz after verifying its paired inputs."""
    if isinstance(min_free_bytes, bool) or not isinstance(min_free_bytes, int) or min_free_bytes < 0:
        raise RawBackupError("min_free_bytes must be a non-negative integer.")
    name = os.path.basename(os.fspath(database_backup_path)).lower()
    if name.endswith(".sql.gz"):
        db_member = "database.sql.gz"
    elif name.endswith(".sql"):
        db_member = "database.sql"
    else:
        raise RawBackupError("Database backup must have a .sql or .sql.gz suffix.")
    package_dir, database_backup_path = os.path.abspath(package_dir), os.path.abspath(database_backup_path)
    output_path = os.path.abspath(output_path)
    parent = os.path.dirname(output_path)
    _ordinary_dir(parent, "Archive output directory")
    if os.path.lexists(output_path):
        raise RawBackupError("Archive output already exists; refusing to overwrite it.")
    verified = verify_backup(package_dir, database_backup_path)
    package_snapshot = _snapshot_tree(package_dir)
    db_signature = _stat_signature(_ordinary_file(database_backup_path, "Database backup"))
    db_size, db_hash = _hash_file(database_backup_path, db_signature)
    _capacity(parent, min_free_bytes)
    temp = os.path.join(parent, ".raw-archive-" + secrets.token_hex(16) + ".tmp")
    names = {db_member: (database_backup_path, db_signature), "raw-package/": (None, None)}
    names.update({"raw-package/" + key: (os.path.join(package_dir, *key.rstrip("/").split("/")), sig)
                  for key, sig in package_snapshot.items()})
    hashes, sizes = {}, {}
    published = False
    completed = False
    try:
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as raw:
            with tarfile.open(fileobj=raw, mode="w:gz", compresslevel=1) as archive:
                archive.copybufsize = _CHUNK
                for member, (source, signature) in names.items():
                    if member.endswith("/"):
                        info = tarfile.TarInfo(member)
                        info.type, info.mode, info.size = tarfile.DIRTYPE, 0o700, 0
                        archive.addfile(info)
                        continue
                    if _stat_signature(_ordinary_file(source, "Archive source")) != signature:
                        raise RawBackupError("An archive source changed before reading.")
                    size = signature[2]
                    info = tarfile.TarInfo(member)
                    info.size, info.mode, info.mtime = size, 0o600, 0
                    with open(source, "rb") as stream:
                        opened = os.fstat(stream.fileno())
                        if _path_signature(opened) != _path_signature(os.stat(source, follow_symlinks=False)):
                            raise RawBackupError("An archive source changed while opening.")
                        reader = _HashingReader(stream, parent, min_free_bytes)
                        archive.addfile(info, reader)
                        if reader.bytes_read != size or _stat_signature(opened) != _stat_signature(os.fstat(stream.fileno())):
                            raise RawBackupError("An archive source changed while being archived.")
                    hashes[member], sizes[member] = reader.digest.hexdigest(), size
                    _capacity(parent, min_free_bytes)
            raw.flush()
            os.fsync(raw.fileno())
        _fsync_dir(parent)
        # Stream-read the completed archive and validate its exact member set and bytes.
        _validate_gzip(temp)
        seen = set()
        with tarfile.open(temp, mode="r:gz") as archive:
            for info in archive:
                member_name = info.name + "/" if info.isdir() and not info.name.endswith("/") else info.name
                if member_name not in names or member_name in seen or info.issym() or info.islnk() or info.isdev():
                    raise RawBackupError("Archive contains an invalid or unexpected member.")
                seen.add(member_name)
                expected_path, signature = names[member_name]
                if info.isdir():
                    continue
                if not info.isfile() or info.size != sizes.get(member_name):
                    raise RawBackupError("Archive member size or type is invalid.")
                digest = hashlib.sha256()
                stream = archive.extractfile(info)
                remaining = info.size
                while remaining:
                    chunk = stream.read(min(_CHUNK, remaining))
                    if not chunk:
                        raise RawBackupError("Archive member is truncated.")
                    digest.update(chunk)
                    remaining -= len(chunk)
                if digest.hexdigest() != hashes[member_name]:
                    raise RawBackupError("Archive member checksum validation failed.")
        if seen != set(names):
            raise RawBackupError("Archive member list is incomplete.")
        if _snapshot_tree(package_dir) != package_snapshot or _stat_signature(_ordinary_file(database_backup_path, "Database backup")) != db_signature:
            raise RawBackupError("An archive source changed during archive creation.")
        if _hash_file(database_backup_path, db_signature) != (db_size, db_hash):
            raise RawBackupError("Database backup changed during archive creation.")
        if verify_backup(package_dir, database_backup_path) != verified:
            raise RawBackupError("RAW package verification changed during archive creation.")
        # hard-link is atomic, same-directory, and cannot replace an existing archive.
        os.link(temp, output_path)
        published = True
        os.unlink(temp)
        _fsync_dir(parent)
        archive_size, archive_hash = _hash_file(output_path)
        result = {"status": "complete", "archive_sha256": archive_hash, "bytes": archive_size,
                "reference_count": verified["reference_count"], "object_count": verified["object_count"],
                "database_backup_sha256": db_hash}
        completed = True
        return result
    except RawBackupError:
        raise
    except Exception as exc:
        raise RawBackupError(f"Archive creation failed: {type(exc).__name__}.") from None
    finally:
        try:
            os.unlink(temp)
        except OSError:
            pass
        if published and not completed:
            # A failure after link publication must not leave a seemingly complete archive.
            try:
                os.unlink(output_path)
                _fsync_dir(parent)
            except OSError:
                pass


def _capacity(path, reserve):
    try:
        if shutil.disk_usage(path).free < reserve:
            raise RawBackupError("Insufficient free space to preserve the configured reserve.")
    except OSError:
        raise RawBackupError("Cannot determine available space on the archive filesystem.") from None


def _validate_gzip(path):
    """Consume the complete gzip stream so CRC and trailer truncation are checked."""
    try:
        with gzip.open(path, "rb") as stream:
            while stream.read(_CHUNK):
                pass
    except (OSError, EOFError, zlib.error):
        raise RawBackupError("Archive gzip stream is incomplete or corrupt.") from None
