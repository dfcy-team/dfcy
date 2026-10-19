"""Private, scope-bound projected-page journal. Never persist provider envelopes."""

import json
import os
import csv
import subprocess
from pathlib import Path

from .tiktok_shop_dataset import MAX_ARTIFACT_BYTES, DatasetError, canonical_bytes, digest_bytes

PARSER_VERSION = "shop-dataset-2.2"


class DatasetCheckpoint:
    def __init__(self, root, scope, *, resume=False):
        self.root = Path(root)
        self.scope = {**scope, "parser_version": PARSER_VERSION}
        self.resume = resume
        self.state = {"scope": self.scope, "pages": {}}
        self.lock_fd = None
        self.touched = set()

    def __enter__(self):
        if self.root.is_symlink():
            raise DatasetError("unsafe_checkpoint_directory")
        if self.resume:
            if not self.root.is_dir():
                raise DatasetError("resume_directory_missing")
        else:
            self.root.mkdir(mode=0o700, parents=True, exist_ok=False)
        if os.name == "nt" and not self.resume:
            self._restrict_windows_acl()
        try:
            self.lock_fd = os.open(self.root / ".lock", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            raise DatasetError("export_directory_locked") from None
        try:
            path = self.root / ".checkpoint.json"
            if self.resume:
                self.state = json.loads(self._read(path))
                if self.state.get("scope") != self.scope or not isinstance(self.state.get("pages"), dict):
                    raise DatasetError("checkpoint_scope_mismatch")
                if os.name == "nt":
                    self._restrict_windows_acl()
            else:
                self._atomic(path, canonical_bytes(self.state))
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def _restrict_windows_acl(self):
        try:
            result = subprocess.run(["whoami", "/user", "/fo", "csv", "/nh"], check=True,
                                    capture_output=True, text=True)
            sid = next(csv.reader(result.stdout.strip().splitlines()))[1]
            if not sid.startswith("S-1-") or not all(c.isdigit() or c in "S-" for c in sid):
                raise ValueError
            subprocess.run(["icacls", str(self.root), "/inheritance:r", "/grant:r",
                            f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F"],
                           check=True, capture_output=True)
        except (OSError, ValueError, IndexError, subprocess.CalledProcessError):
            raise DatasetError("checkpoint_permissions_failed") from None

    def __exit__(self, *args):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None
            (self.root / ".lock").unlink()

    def _read(self, path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise DatasetError("invalid_checkpoint_file")
        return path.read_bytes()

    def _atomic(self, path, content):
        if path.is_symlink():
            raise DatasetError("unsafe_checkpoint_file")
        total = sum(p.stat().st_size for p in self.root.iterdir() if p.is_file())
        if total + len(content) > MAX_ARTIFACT_BYTES:
            raise DatasetError("artifact_size_exceeded")
        temporary = self.root / ".pending"
        # A crash may leave this private temporary file; it is never trusted.
        if temporary.is_symlink():
            raise DatasetError("unsafe_checkpoint_file")
        fd = os.open(temporary, os.O_CREAT | os.O_TRUNC | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)

    def key(self, descriptor):
        return digest_bytes(canonical_bytes({"scope": self.scope, "query": descriptor}))

    def load(self, descriptor):
        key = self.key(descriptor)
        self.touched.add(key)
        entry = self.state["pages"].get(key)
        if entry is None:
            return None
        content = self._read(self.root / (".page-" + key + ".json"))
        if digest_bytes(content) != entry.get("sha256"):
            raise DatasetError("checkpoint_page_digest_mismatch")
        page = json.loads(content)
        if page.get("key") != key or page.get("status") != "complete":
            raise DatasetError("invalid_checkpoint_page")
        return page["result"]

    def save(self, descriptor, result):
        key = self.key(descriptor)
        self.touched.add(key)
        content = canonical_bytes({"key": key, "status": "complete", "result": result})
        self._atomic(self.root / (".page-" + key + ".json"), content)
        self.state["pages"][key] = {"sha256": digest_bytes(content)}
        self._atomic(self.root / ".checkpoint.json", canonical_bytes(self.state))

    def begin_day(self):
        self.touched = set()

    def fail_day(self):
        for key in self.touched:
            self.state["pages"].pop(key, None)
        self._atomic(self.root / ".checkpoint.json", canonical_bytes(self.state))

    def write_artifact(self, filename, content):
        if Path(filename).name != filename or any(c in filename for c in "/\\:"):
            raise DatasetError("unsafe_component_path")
        self._atomic(self.root / filename, content)
