"""Exercise both authorized API paths without requiring unrelated migration state."""
from contextlib import ExitStack, nullcontext
import hashlib
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, override_settings
from rest_framework.exceptions import NotFound
from apps.supply_chain import payment_vouchers as views
from apps.supply_chain.models import PaymentVoucher
from apps.supply_chain.payment_voucher_storage import VoucherStorageError


class VoucherApiTests(SimpleTestCase):
    def setUp(self):
        self.body = b"%PDF-1.4\nreceipt\n%%EOF"
        self.digest = hashlib.sha256(self.body).hexdigest()
        self.request = SimpleNamespace(user=SimpleNamespace(tenant_id=7, tenant=object()), FILES={})
        self.parent = SimpleNamespace(pk=9)
        self.voucher = SimpleNamespace(pk=11, file_name="receipt.pdf", media_type="application/pdf",
                                      sha256=self.digest, read_content=MagicMock(return_value=self.body))

    def upload_context(self, stack, replay=False):
        stack.enter_context(patch.object(views, "_revision", return_value=(self.parent, self.parent)))
        stack.enter_context(patch.object(views.PaymentRecordVouchers, "_record", return_value=(self.parent, self.parent)))
        stack.enter_context(patch.object(views, "key", return_value="upload-1"))
        stack.enter_context(patch.object(views, "_validate_file", return_value=("receipt.pdf", "application/pdf", self.body, self.digest)))
        stack.enter_context(patch.object(views.transaction, "atomic", side_effect=lambda: nullcontext()))
        stack.enter_context(patch.object(views, "domain_write", side_effect=lambda: nullcontext()))
        stack.enter_context(patch.object(views.services, "_tenant_lock"))
        event = stack.enter_context(patch.object(views.services, "_event"))
        stack.enter_context(patch.object(views.services, "_prior_event",
            return_value=SimpleNamespace(payload={"payment_voucher_id": 11}) if replay else None))
        stack.enter_context(patch.object(views, "_metadata", return_value={"id": 11}))
        manager = MagicMock()
        manager.filter.return_value.count.return_value = 0
        manager.filter.return_value.defer.return_value.first.return_value = None
        manager.filter.return_value.select_related.return_value.defer.return_value.first.return_value = self.voucher
        manager.create.return_value = self.voucher
        stack.enter_context(patch.object(views.PaymentVoucher, "objects", manager))
        return manager, event

    def paths(self):
        return [(views.PaymentVouchers(), ("shipment", 3, 9), "settlement_revision"),
                (views.PaymentRecordVouchers(), ("shipment", 3, 9), "payment")]

    def test_both_upload_paths_save_only_verified_reference_and_audit(self):
        for view, args, kind in self.paths():
            with self.subTest(kind=kind), ExitStack() as stack:
                manager, event = self.upload_context(stack)
                fields = dict(content=b"", content_storage_alias="raw_oss", content_object_key="verified-key")
                storage = stack.enter_context(patch.object(views, "store_content", return_value=fields))
                result = view.post(self.request, *args)
                self.assertEqual(result.status_code, 201)
                self.assertEqual(storage.call_args.kwargs["parent_kind"], kind)
                self.assertEqual(storage.call_args.kwargs["tenant_id"], 7)
                for key, value in fields.items():
                    self.assertEqual(manager.create.call_args.kwargs[key], value)
                event.assert_called_once()

    def test_storage_failure_cannot_create_db_row_or_audit_for_either_path(self):
        for view, args, kind in self.paths():
            with self.subTest(kind=kind), ExitStack() as stack:
                manager, event = self.upload_context(stack)
                stack.enter_context(patch.object(views, "store_content", side_effect=VoucherStorageError("failed")))
                with self.assertRaises(views.VoucherContentUnavailable) as raised:
                    view.post(self.request, *args)
                self.assertEqual(raised.exception.status_code, 503)
                manager.create.assert_not_called()
                event.assert_not_called()

    def test_idempotent_replay_does_not_touch_storage_or_duplicate_db(self):
        for view, args, kind in self.paths():
            with self.subTest(kind=kind), ExitStack() as stack:
                manager, event = self.upload_context(stack, replay=True)
                storage = stack.enter_context(patch.object(views, "store_content"))
                self.assertEqual(view.post(self.request, *args).status_code, 200)
                storage.assert_not_called()
                manager.create.assert_not_called()
                event.assert_not_called()

    def test_download_checks_parent_permission_before_any_file_read(self):
        for view, permission in [(views.PaymentVoucherDownload(), "_revision"),
                                 (views.PaymentRecordVoucherDownload(), "_record")]:
            target = views if permission == "_revision" else views.PaymentRecordVouchers
            with self.subTest(view=type(view).__name__), patch.object(target, permission, side_effect=NotFound()):
                with patch.object(views.PaymentVoucher, "objects") as manager:
                    with self.assertRaises(NotFound):
                        view.get(self.request, "shipment", 3, 9, 11)
                    manager.filter.assert_not_called()
                    self.voucher.read_content.assert_not_called()

    def test_both_downloads_return_original_bytes_and_map_storage_errors(self):
        for view in [views.PaymentVoucherDownload(), views.PaymentRecordVoucherDownload()]:
            with self.subTest(view=type(view).__name__), ExitStack() as stack:
                stack.enter_context(patch.object(views, "_revision", return_value=(self.parent, self.parent)))
                stack.enter_context(patch.object(views.PaymentRecordVouchers, "_record"))
                manager = stack.enter_context(patch.object(views.PaymentVoucher, "objects"))
                manager.filter.return_value.first.return_value = self.voucher
                self.voucher.read_content.side_effect = None
                response = view.get(self.request, "shipment", 3, 9, 11)
                self.assertEqual(b"".join(response.streaming_content), self.body)
                self.assertEqual(response["Cache-Control"], "private, no-store")
                self.assertEqual(response["X-File-SHA256"], self.digest)
                self.assertEqual(manager.filter.call_args.kwargs["tenant_id"], 7)
                self.voucher.read_content.side_effect = VoucherStorageError("bad content")
                with self.assertRaises(views.VoucherContentUnavailable):
                    view.get(self.request, "shipment", 3, 9, 11)

    @override_settings(RAW_PAYLOAD_STORAGE_NAMESPACE="unit-test")
    def test_model_reads_legacy_and_external_content(self):
        from apps.supply_chain import payment_voucher_storage as store
        row = PaymentVoucher(tenant_id=7, payment_id=9, idempotency_key="upload-1",
            content=self.body, byte_size=len(self.body), sha256=self.digest)
        self.assertEqual(row.read_content(), self.body)
        with patch.object(store, "_read", return_value=self.body) as read:
            row.content = b""
            row.content_storage_alias = "raw_oss"
            row.content_object_key = store.object_key(7, "payment", 9, "upload-1", self.digest)
            with patch.object(store, "storages", {"raw_oss": object()}):
                self.assertEqual(row.read_content(), self.body)
            read.assert_called_once()
