import gzip
import hashlib
import json
import os
import tempfile
import unittest
from unittest import mock

from apps.integrations.raw_backup import RawBackupError, create_backup, verify_backup


class RawBackupTests(unittest.TestCase):
    namespace = "unit-test"
    key = "raw/unit-test/tenant-7/0123456789abcdef0123456789abcdef.json.gz"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = self.temp.name
        self.source = os.path.join(self.root, "raw")
        os.mkdir(self.source)
        self.db = os.path.join(self.root, "db.sql")
        with open(self.db, "wb") as stream:
            stream.write(b"synthetic database snapshot")
        self.manifest = os.path.join(self.root, "manifest.jsonl")
        self.payload = {"records": [{"id": 1, "name": "测试"}]}
        self.payload_bytes = json.dumps(
            self.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        self.payload_hash = hashlib.sha256(self.payload_bytes).hexdigest()
        self.object_path = os.path.join(self.source, *self.key.split("/"))
        os.makedirs(os.path.dirname(self.object_path))
        with open(self.object_path, "wb") as stream:
            stream.write(gzip.compress(self.payload_bytes, mtime=0))
        self.write_manifest([self.row(1, "ref-one")])

    def tearDown(self):
        self.temp.cleanup()

    def row(self, ident, raw_ref, key=None, digest=None):
        return {"id": ident, "raw_ref": raw_ref, "tenant_id": 7,
                "payload_storage_alias": "raw_local", "payload_object_key": key or self.key,
                "payload_hash": digest or self.payload_hash}

    def write_manifest(self, rows):
        with open(self.manifest, "wb") as stream:
            for row in rows:
                stream.write(json.dumps(row, sort_keys=True, separators=(",", ":")).encode() + b"\n")

    def build(self, name="package"):
        target = os.path.join(self.root, name)
        result = create_backup(self.manifest, self.db, self.source, self.namespace, target,
                               min_free_bytes=0)
        return target, result

    def test_roundtrip_and_shared_object(self):
        self.write_manifest([self.row(1, "ref-one"), self.row(2, "ref-two")])
        package, result = self.build()
        verified = verify_backup(package, self.db)
        self.assertEqual((result["reference_count"], result["object_count"]), (2, 1))
        self.assertEqual(verified["status"], "verified")
        self.assertFalse(any(k in verified for k in ("payload", "records")))
        if os.name != "nt":
            self.assertEqual(os.stat(package).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(os.path.join(package, "objects", *self.key.split("/"))).st_mode & 0o777, 0o600)

    def test_tampered_object_missing_object_and_wrong_database(self):
        package, _ = self.build()
        obj = os.path.join(package, "objects", *self.key.split("/"))
        with open(obj, "ab") as stream:
            stream.write(b"x")
        with self.assertRaisesRegex(RawBackupError, "gzip|hash|payload"):
            verify_backup(package, self.db)
        os.remove(obj)
        with self.assertRaisesRegex(RawBackupError, "missing|invalid|Package"):
            verify_backup(package, self.db)
        other_db = os.path.join(self.root, "wrong.sql")
        with open(other_db, "wb") as stream:
            stream.write(b"different")
        with self.assertRaisesRegex(RawBackupError, "Database backup SHA256"):
            verify_backup(package, other_db)

    def test_rejects_paths_duplicates_and_alias(self):
        for row in (self.row(1, "ref", key="../../escape"),
                    dict(self.row(1, "ref"), payload_storage_alias="default")):
            self.write_manifest([row])
            with self.assertRaises(RawBackupError):
                self.build("bad-" + str(len(row["payload_object_key"])))
        self.write_manifest([self.row(1, "same"), self.row(2, "same")])
        with self.assertRaisesRegex(RawBackupError, "duplicate"):
            self.build("duplicate-ref")
        self.write_manifest([self.row(1, "one"), self.row(1, "two")])
        with self.assertRaisesRegex(RawBackupError, "duplicate"):
            self.build("duplicate-id")

    def test_empty_manifest_and_existing_output(self):
        self.write_manifest([])
        package, result = self.build()
        self.assertEqual((result["reference_count"], result["object_count"]), (0, 0))
        self.assertEqual(verify_backup(package, self.db)["total_bytes"], 0)
        with self.assertRaisesRegex(RawBackupError, "already exists"):
            create_backup(self.manifest, self.db, self.source, self.namespace, package,
                          min_free_bytes=0)

    def test_receipt_temp_cleanup_failure_is_not_reported_complete(self):
        original_unlink = os.unlink
        def fail_temp(path, *args, **kwargs):
            if os.path.basename(os.fspath(path)).startswith('.receipt-'):
                raise PermissionError('synthetic cleanup failure')
            return original_unlink(path, *args, **kwargs)
        with mock.patch('apps.integrations.raw_backup.os.unlink', side_effect=fail_temp):
            with self.assertRaises(RawBackupError):
                self.build('cleanup-failure')
        package = os.path.join(self.root, 'cleanup-failure')
        self.assertFalse(os.path.exists(os.path.join(package, 'receipt.json')))
        with self.assertRaises(RawBackupError):
            verify_backup(package, self.db)

    def test_failed_creation_leaves_no_completion_receipt(self):
        with open(self.object_path, "wb") as stream:
            stream.write(b"not gzip")
        target = os.path.join(self.root, "incomplete")
        with self.assertRaises(RawBackupError):
            create_backup(self.manifest, self.db, self.source, self.namespace, target,
                          min_free_bytes=0)
        self.assertTrue(os.path.isdir(target))
        self.assertFalse(os.path.exists(os.path.join(target, "receipt.json")))

    def test_manifest_tampering_and_source_symlink(self):
        package, _ = self.build()
        refs = os.path.join(package, "refs.jsonl")
        with open(refs, "rb") as stream:
            changed = stream.read().replace(b"\n", b" \n", 1)
        with open(refs, "wb") as stream:
            stream.write(changed)
        with self.assertRaisesRegex(RawBackupError, "manifest SHA256"):
            verify_backup(package, self.db)
        if hasattr(os, "symlink"):
            linked = os.path.join(self.source, "raw", "unit-test", "tenant-7", "fedcba9876543210fedcba9876543210.json.gz")
            try:
                os.symlink(self.object_path, linked)
            except (OSError, NotImplementedError):
                return
            self.write_manifest([self.row(3, "linked", key="raw/unit-test/tenant-7/fedcba9876543210fedcba9876543210.json.gz")])
            with self.assertRaises(RawBackupError):
                self.build("symlink-package")

    def test_canonical_json_receipt_bounds_and_capacity_reserve(self):
        raw = b'{"records": [1]}'
        self.payload_hash = hashlib.sha256(raw).hexdigest()
        with open(self.object_path, "wb") as stream:
            stream.write(gzip.compress(raw, mtime=0))
        self.write_manifest([self.row(1, "noncanonical")])
        target = os.path.join(self.root, "noncanonical-package")
        with self.assertRaisesRegex(RawBackupError, "canonical"):
            create_backup(self.manifest, self.db, self.source, self.namespace, target, min_free_bytes=0)
        self.assertFalse(os.path.exists(os.path.join(target, "receipt.json")))

        self.payload_hash = hashlib.sha256(self.payload_bytes).hexdigest()
        with open(self.object_path, "wb") as stream:
            stream.write(gzip.compress(self.payload_bytes, mtime=0))
        self.write_manifest([self.row(1, "valid")])
        package, _ = self.build("valid-package")
        if os.name != "nt":
            nested = os.path.join(package, "objects", "raw", "unit-test", "tenant-7")
            self.assertEqual(os.stat(nested).st_mode & 0o777, 0o700)
        receipt_path = os.path.join(package, "receipt.json")
        with open(receipt_path, "w", encoding="utf-8") as stream:
            json.dump({"format_version": 1, "namespace": self.namespace,
                       "database_backup_sha256": "0" * 64, "manifest_sha256": "0" * 64,
                       "reference_count": True, "object_count": 1, "total_bytes": 1}, stream)
        with self.assertRaisesRegex(RawBackupError, "reference_count"):
            verify_backup(package, self.db)
        with open(receipt_path, "wb") as stream:
            stream.write(b" " * (64 * 1024 + 1))
        with self.assertRaisesRegex(RawBackupError, "64 KiB"):
            verify_backup(package, self.db)

        capacity_target = os.path.join(self.root, "reserve-package")
        with mock.patch("apps.integrations.raw_backup.shutil.disk_usage",
                        return_value=mock.Mock(free=20)):
            with self.assertRaisesRegex(RawBackupError, "reserve"):
                create_backup(self.manifest, self.db, self.source, self.namespace,
                              capacity_target, min_free_bytes=21)
        self.assertFalse(os.path.exists(capacity_target))


if __name__ == "__main__":
    unittest.main()
