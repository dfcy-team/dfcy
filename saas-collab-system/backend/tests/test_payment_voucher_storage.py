import base64
import gzip
import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings
from apps.supply_chain import payment_voucher_storage as subject


class MemoryStorage:
    def __init__(self):
        self.objects = {}
        self.writes = []
        self.reads = []
        self.fail = False
        self.lost_response = False
        self.renamed = False

    def save(self, key, source):
        self.writes.append(key)
        if self.fail:
            raise OSError("write failed")
        if key not in self.objects:
            self.objects[key] = source.read()
        if self.lost_response:
            raise OSError("response lost after immutable PUT")
        return key + "x" if self.renamed else key

    def open(self, key, mode):
        self.reads.append(key)
        return BytesIO(self.objects[key])


@override_settings(PAYMENT_VOUCHER_STORAGE_ALIAS="raw_oss", RAW_PAYLOAD_STORAGE_NAMESPACE="unit-test")
class VoucherStorageTests(SimpleTestCase):
    def setUp(self):
        self.body = b"%PDF-1.4\nreceipt\n%%EOF"
        self.sha = hashlib.sha256(self.body).hexdigest()
        self.args = dict(body=self.body, tenant_id=7, parent_kind="payment", parent_id=9,
                         idempotency_key="upload-1", sha256=self.sha)
        self.storage = MemoryStorage()
        self.mock = patch.object(subject, "storages", {"raw_oss": self.storage})
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def voucher(self, fields):
        return SimpleNamespace(tenant_id=7, payment_id=9, settlement_revision_id=None,
            idempotency_key="upload-1", sha256=self.sha, byte_size=len(self.body), **fields)

    def test_external_readback_and_contract(self):
        fields = subject.store_content(**self.args)
        self.assertEqual(fields["content"], b"")
        key = fields["content_object_key"]
        self.assertRegex(key, r"^raw/unit-test/tenant-7/[0-9a-f]{32}\.json\.gz$")
        raw = gzip.decompress(self.storage.objects[key])
        self.assertEqual(json.loads(raw), dict(schema="payment-voucher-v1",
            content_base64=base64.b64encode(self.body).decode("ascii"), sha256=self.sha,
            byte_size=len(self.body)))
        self.assertEqual(subject.read_content(self.voucher(fields)), self.body)
        self.assertEqual(self.storage.reads, [key, key])

    def test_disabled_inline_compatibility_with_hash_and_size(self):
        with override_settings(PAYMENT_VOUCHER_STORAGE_ALIAS=""):
            fields = subject.store_content(**self.args)
        row = self.voucher(fields)
        self.assertEqual(subject.read_content(row), self.body)
        self.assertFalse(self.storage.writes)
        row.byte_size += 1
        with self.assertRaises(subject.VoucherStorageError):
            subject.read_content(row)
        row.byte_size -= 1
        row.sha256 = "0" * 64
        with self.assertRaises(subject.VoucherStorageError):
            subject.read_content(row)

    def test_failed_upload_no_inline_fallback(self):
        self.storage.fail = True
        with self.assertRaises(subject.VoucherStorageError):
            subject.store_content(**self.args)
        self.assertFalse(self.storage.objects)

    def test_lost_response_and_retry_use_same_verified_key(self):
        self.storage.lost_response = True
        first = subject.store_content(**self.args)
        second = subject.store_content(**self.args)
        self.assertEqual(first, second)
        self.assertEqual(len(self.storage.objects), 1)
        self.assertEqual(len(self.storage.reads), 2)

    def test_corrupt_hash_size_and_base64_rejected(self):
        fields = subject.store_content(**self.args)
        key = fields["content_object_key"]
        original = json.loads(gzip.decompress(self.storage.objects[key]))
        for field, bad in [("sha256", "0" * 64), ("byte_size", 1),
                           ("content_base64", "!!!"), ("content_base64", "YWJj")]:
            damaged = dict(original, **{field: bad})
            self.storage.objects[key] = gzip.compress(subject._canonical(damaged), mtime=0)
            with self.subTest(field=field, bad=bad), self.assertRaises(subject.VoucherStorageError):
                subject.read_content(self.voucher(fields))

    def test_path_tenant_and_parent_rejected_before_storage_read(self):
        fields = subject.store_content(**self.args)
        for attr, value in [("tenant_id", 8), ("payment_id", 10), ("idempotency_key", "other")]:
            row = self.voucher(fields)
            setattr(row, attr, value)
            self.storage.reads.clear()
            with self.subTest(attr=attr), self.assertRaises(subject.VoucherStorageError):
                subject.read_content(row)
            self.assertFalse(self.storage.reads)

    def test_key_separates_voucher_parent_types_and_is_deterministic(self):
        key = subject.object_key(7, "payment", 9, "upload-1", self.sha)
        self.assertEqual(key, subject.object_key(7, "payment", 9, "upload-1", self.sha))
        self.assertNotEqual(key, subject.object_key(7, "settlement_revision", 9, "upload-1", self.sha))

    def test_renaming_missing_reference_and_mixed_content_rejected(self):
        self.storage.renamed = True
        with self.assertRaises(subject.VoucherStorageError):
            subject.store_content(**self.args)
        self.storage.renamed = False
        fields = subject.store_content(**self.args)
        for changes in [dict(content_object_key=None), dict(content_storage_alias=None), dict(content=b"bad")]:
            with self.assertRaises(subject.VoucherStorageError):
                subject.read_content(self.voucher(dict(fields, **changes)))

    def test_max_bytes_and_bounded_decompression(self):
        with self.assertRaises(subject.VoucherStorageError):
            subject.store_content(**dict(self.args, body=b"x" * (subject.MAX_BYTES + 1)))
        with patch.object(subject, "MAX_ENVELOPE_BYTES", 20):
            with self.assertRaises(subject.VoucherStorageError):
                subject.decode_content(gzip.compress(b"x" * 100), 1, self.sha)
