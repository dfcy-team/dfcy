"""Private local filesystem storage for immutable RAW payload objects.

The configured root and its mount must be trusted and writable only by the
application operator. Capacity checks are best effort under concurrent writes;
they cannot guarantee the reserve against an external writer. Windows cannot
enforce POSIX mode bits or provide the POSIX dirfd protections used on Unix.
"""

import io
import os
import re
import secrets
import shutil
import stat

from django.core.files.base import File
from django.core.files.storage import Storage


MAX_OBJECT_BYTES = 32 * 1024 * 1024
_NAMESPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_KEY_RE = re.compile(
    r"^raw/(?P<namespace>[A-Za-z0-9][A-Za-z0-9._-]{0,63})/"
    r"tenant-[0-9]+/(?P<uuid>[0-9a-f]{32})\.json\.gz$"
)
_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class RawLocalStorageError(Exception):
    """Fixed-message storage error that never exposes payload data or paths."""


class PrivateRawLocalStorage(Storage):
    """Store immutable RAW objects under an existing private directory."""

    def __init__(self, location, namespace, min_free_bytes=10737418240):
        super().__init__()
        try:
            location = os.fspath(location)
        except TypeError:
            raise ValueError("RAW storage location must be an absolute directory.") from None
        if not isinstance(location, str) or not os.path.isabs(location):
            raise ValueError("RAW storage location must be an absolute directory.")
        if not isinstance(namespace, str) or not _NAMESPACE_RE.fullmatch(namespace):
            raise ValueError("Invalid RAW storage namespace.")
        if (isinstance(min_free_bytes, bool) or not isinstance(min_free_bytes, int)
                or min_free_bytes < 0):
            raise ValueError("Invalid RAW storage free-space reserve.")
        try:
            root_info = os.lstat(location)
            if (not stat.S_ISDIR(root_info.st_mode)
                    or getattr(root_info, "st_file_attributes", 0) & _REPARSE_POINT):
                raise ValueError
            self._check_private_dir(root_info)
        except (OSError, ValueError):
            raise ValueError("RAW storage location must be an existing private directory.") from None
        self.location = os.path.abspath(location)
        self.namespace = namespace
        self.min_free_bytes = min_free_bytes

    @staticmethod
    def _check_private_dir(info):
        if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
            raise ValueError("Directory is not private.")

    def _validate_key(self, name):
        match = _KEY_RE.fullmatch(name) if isinstance(name, str) else None
        if not match or match.group("namespace") != self.namespace:
            raise ValueError("Invalid RAW object key.")
        return name

    def _open_root(self):
        flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_DIRECTORY", 0)
                 | getattr(os, "O_NOFOLLOW", 0))
        fd = os.open(self.location, flags)
        try:
            info = os.fstat(fd)
            if not stat.S_ISDIR(info.st_mode):
                raise OSError("not a directory")
            self._check_private_dir(info)
            return fd
        except Exception:
            os.close(fd)
            raise

    def _parent_fd(self, key, create=False):
        """Open validated parent components without following POSIX symlinks."""
        components = key.split("/")[:-1]
        if os.name != "nt" and os.open in getattr(os, "supports_dir_fd", set()):
            fd = self._open_root()
            try:
                root_device = os.fstat(fd).st_dev
                for component in components:
                    try:
                        child = os.open(component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                        | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
                    except FileNotFoundError:
                        if not create:
                            raise
                        try:
                            os.mkdir(component, 0o700, dir_fd=fd)
                            if hasattr(os, "fsync"):
                                os.fsync(fd)
                        except FileExistsError:
                            # Another writer created the path; opening below
                            # still verifies that it is a private real directory.
                            pass
                        child = os.open(component, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
                                        | getattr(os, "O_NOFOLLOW", 0), dir_fd=fd)
                    info = os.fstat(child)
                    try:
                        if not stat.S_ISDIR(info.st_mode) or info.st_dev != root_device:
                            raise OSError("not a directory")
                        self._check_private_dir(info)
                    except Exception:
                        os.close(child)
                        raise
                    os.close(fd)
                    fd = child
                return fd, components[-1]
            except Exception:
                os.close(fd)
                raise

        # Windows has no dir_fd/O_NOFOLLOW equivalent in the Python runtime.
        # Reject reparse points and require the configured tree to be trusted.
        root_info = os.lstat(self.location)
        if (not stat.S_ISDIR(root_info.st_mode)
                or getattr(root_info, "st_file_attributes", 0) & _REPARSE_POINT):
            raise OSError("not a private directory")
        self._check_private_dir(root_info)
        current = self.location
        for component in components:
            current = os.path.join(current, component)
            try:
                info = os.lstat(current)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(current, 0o700)
                except FileExistsError:
                    pass
                info = os.lstat(current)
            if (not stat.S_ISDIR(info.st_mode)
                    or info.st_dev != root_info.st_dev
                    or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT):
                raise OSError("not a private directory")
            self._check_private_dir(info)
        return None, os.path.join(self.location, *components)

    def save(self, name, content, max_length=None):
        self._validate_key(name)
        if max_length is not None and len(name) > max_length:
            raise ValueError("RAW object key exceeds the maximum name length.")
        return self._save(name, content)

    def _save(self, name, content):
        self._validate_key(name)
        temp_name = ".raw-" + secrets.token_hex(16) + ".tmp"
        parent_fd = None
        temp_path = None
        temp_created = False
        try:
            body = content.read(MAX_OBJECT_BYTES + 1)
            if not isinstance(body, bytes) or len(body) > MAX_OBJECT_BYTES:
                raise RawLocalStorageError("RAW object exceeds the configured size limit.")
            if shutil.disk_usage(self.location).free - len(body) < self.min_free_bytes:
                raise RawLocalStorageError("RAW storage capacity reserve would be exceeded.")
            parent_fd, parent = self._parent_fd(name, create=True)
            basename = name.rsplit("/", 1)[-1]
            if parent_fd is None:
                temp_path = os.path.join(parent, temp_name)
            open_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
            if parent_fd is not None:
                temp_fd = os.open(temp_name, open_flags, 0o600, dir_fd=parent_fd)
            else:
                temp_fd = os.open(temp_path, open_flags, 0o600)
            temp_created = True
            try:
                if os.name != "nt":
                    os.fchmod(temp_fd, 0o600)
                target = os.fdopen(temp_fd, "wb")
            except Exception:
                # fdopen has not taken ownership yet.
                os.close(temp_fd)
                raise
            with target:
                target.write(body)
                target.flush()
                os.fsync(target.fileno())
            if parent_fd is not None:
                os.link(temp_name, basename, src_dir_fd=parent_fd, dst_dir_fd=parent_fd,
                        follow_symlinks=False)
                os.unlink(temp_name, dir_fd=parent_fd)
                temp_created = False
                if hasattr(os, "fsync"):
                    os.fsync(parent_fd)
            else:
                os.link(temp_path, os.path.join(parent, basename), follow_symlinks=False)
                os.unlink(temp_path)
                temp_created = False
                if os.name != "nt":
                    dir_fd = os.open(parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
                    try:
                        if hasattr(os, "fsync"):
                            os.fsync(dir_fd)
                    finally:
                        os.close(dir_fd)
            return name
        except RawLocalStorageError:
            raise
        except FileExistsError:
            raise RawLocalStorageError("RAW object already exists.") from None
        except Exception:
            raise RawLocalStorageError("RAW object could not be stored safely.") from None
        finally:
            if temp_created:
                try:
                    if parent_fd is not None:
                        os.unlink(temp_name, dir_fd=parent_fd)
                    elif temp_path:
                        os.unlink(temp_path)
                except OSError:
                    pass
            if parent_fd is not None:
                os.close(parent_fd)

    def _open(self, name, mode="rb"):
        self._validate_key(name)
        if mode != "rb":
            raise ValueError("RAW objects can only be opened in binary read mode.")
        parent_fd = None
        try:
            parent_fd, parent = self._parent_fd(name)
            basename = name.rsplit("/", 1)[-1]
            flags = (os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
                     | getattr(os, "O_NONBLOCK", 0))
            if parent_fd is not None:
                fd = os.open(basename, flags, dir_fd=parent_fd)
            else:
                object_path = os.path.join(parent, basename)
                info = os.lstat(object_path)
                if (not stat.S_ISREG(info.st_mode)
                        or getattr(info, "st_file_attributes", 0) & _REPARSE_POINT):
                    raise RawLocalStorageError("RAW object has an invalid type or size.")
                fd = os.open(object_path, flags)
            with os.fdopen(fd, "rb") as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_OBJECT_BYTES:
                    raise RawLocalStorageError("RAW object has an invalid type or size.")
                if os.name != "nt" and stat.S_IMODE(info.st_mode) & 0o077:
                    raise RawLocalStorageError("RAW object has an invalid type or size.")
                body = source.read(MAX_OBJECT_BYTES + 1)
            if len(body) > MAX_OBJECT_BYTES:
                raise RawLocalStorageError("RAW object exceeds the configured size limit.")
            return File(io.BytesIO(body), name=name)
        except RawLocalStorageError:
            raise
        except Exception:
            raise RawLocalStorageError("RAW object could not be opened safely.") from None
        finally:
            if parent_fd is not None:
                os.close(parent_fd)

    def exists(self, name):
        raise NotImplementedError("RAW object existence checks are not supported.")

    def url(self, name):
        raise NotImplementedError("Private RAW objects do not have public URLs.")

    def delete(self, name):
        raise NotImplementedError("RAW object deletion is not supported.")

    def listdir(self, path):
        raise NotImplementedError("RAW object listing is not supported.")
