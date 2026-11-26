import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from apps.supply_chain.models import PaymentVoucher
from apps.supply_chain import payment_voucher_storage as store
from tests.test_supply_chain_v2_foundation import world
from tests.test_supply_chain_v2_costs import pilot
from tests.test_supply_chain_payment_vouchers import _settlement, _path
from tests.test_payment_voucher_storage import MemoryStorage


@pytest.mark.django_db
def test_external_voucher_real_db_roundtrip_replay_and_failure(world, monkeypatch, settings):
    settings.PAYMENT_VOUCHER_STORAGE_ALIAS = "raw_oss"
    settings.RAW_PAYLOAD_STORAGE_NAMESPACE = "unit-test"
    memory = MemoryStorage()
    monkeypatch.setattr(store, "storages", {"raw_oss": memory})
    _, api, shipment = pilot(world)
    revision_id, _ = _settlement(api, "shipment", shipment)
    endpoint = _path("shipment", shipment.pk, revision_id)
    body = b"%PDF-1.4\nOSS receipt\n%%EOF"

    def upload(key):
        return api.post(endpoint, {"file": SimpleUploadedFile("receipt.pdf", body, "application/pdf")},
                        format="multipart", HTTP_IDEMPOTENCY_KEY=key)

    memory.fail = True
    failed = upload("failed-write")
    assert failed.status_code == 503, failed.data
    assert PaymentVoucher.objects.count() == 0
    memory.fail = False
    memory.lost_response = True
    result = upload("oss-upload")
    assert result.status_code == 201, result.data
    row = PaymentVoucher.objects.get(pk=result.data["data"]["id"])
    assert bytes(row.content) == b""
    assert row.content_storage_alias == "raw_oss" and row.content_object_key
    assert row.read_content() == body
    assert upload("oss-upload").status_code == 200
    assert PaymentVoucher.objects.count() == 1
    download = endpoint + f"{row.pk}/download/"
    response = api.get(download)
    assert response.status_code == 200
    assert b"".join(response.streaming_content) == body
    memory.objects[row.content_object_key] = b"damaged gzip"
    assert api.get(download).status_code == 503


@pytest.mark.django_db
def test_original_inline_api_suite_still_saves_inline(world, settings):
    settings.PAYMENT_VOUCHER_STORAGE_ALIAS = ""
    from tests.test_supply_chain_payment_vouchers import test_payment_transaction_voucher_upload_list_and_download
    test_payment_transaction_voucher_upload_list_and_download(world)
    row = PaymentVoucher.objects.get()
    assert row.content and not row.content_object_key and not row.content_storage_alias


@pytest.mark.django_db
def test_payment_record_external_real_db_roundtrip_and_replay(world, monkeypatch, settings):
    settings.PAYMENT_VOUCHER_STORAGE_ALIAS = "raw_oss"
    settings.RAW_PAYLOAD_STORAGE_NAMESPACE = "unit-test"
    memory = MemoryStorage()
    monkeypatch.setattr(store, "storages", {"raw_oss": memory})
    from tests.test_supply_chain_payment_vouchers import test_payment_transaction_voucher_upload_list_and_download
    test_payment_transaction_voucher_upload_list_and_download(world)
    row = PaymentVoucher.objects.get()
    assert bytes(row.content) == b"" and row.content_storage_alias == "raw_oss"
    assert row.read_content() == b"%PDF-1.4\ntransaction proof\n%%EOF"
    assert len(memory.objects) == 1
