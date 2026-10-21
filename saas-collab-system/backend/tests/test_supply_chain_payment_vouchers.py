import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.permissions.models import DataScope
from apps.supply_chain.models import PaymentVoucher, SettlementRevision
from tests.test_supply_chain_v2_costs import pilot, get
from tests.test_supply_chain_v2_foundation import internal_user, supplier_user, world
from tests.test_supply_chain_v2_logistics import BASE, write


def _settlement(api, kind, target):
    target_id = target.pk if hasattr(target, "pk") else target
    context = get(api, kind, target_id)
    payload = {"expected_source_version": context["target"]["version"], "expected_version": 0,
               "recorded_amount": "20", "reference_number": "PAY-VOUCHER-1",
               "date": "2026-10-14", "reason": "凭证附件测试"}
    result = write(api, f"costs/{kind}/{target_id}/settlement/", payload, "voucher-settlement")
    assert result.status_code == 200, result.data
    revision_id = result.data["data"]["settlement_history"][0]["id"]
    return revision_id, payload


def _path(kind, target_id, revision_id):
    return f"{BASE}costs/{kind}/{target_id}/settlements/{revision_id}/vouchers/"


@pytest.mark.parametrize("kind", ["shipment", "batch"])
def test_settlement_vouchers_bind_to_history_and_download_privately(world, kind):
    if kind == "batch":
        from tests.test_supply_chain_v2_costs import received_pilot
        _, api, shipment, batch, _ = received_pilot(world)
        target = batch
    else:
        _, api, target = pilot(world)
    revision_id, _ = _settlement(api, kind, target)
    before = get(api, kind, target)["settlement"]["recorded_amount"]
    content = b"%PDF-1.4\nminimal test\n%%EOF"
    file = SimpleUploadedFile("payment receipt.pdf", content, "application/pdf")
    endpoint = _path(kind, target.pk if hasattr(target, "pk") else target, revision_id)
    response = api.post(endpoint, {"file": file}, format="multipart", HTTP_IDEMPOTENCY_KEY="voucher-1")
    assert response.status_code == 201, response.data
    voucher_id = response.data["data"]["id"]
    replay = api.post(endpoint, {"file": SimpleUploadedFile("payment receipt.pdf", content, "application/pdf")},
                      format="multipart", HTTP_IDEMPOTENCY_KEY="voucher-1")
    assert replay.status_code == 200 and replay.data["data"]["id"] == voucher_id
    assert PaymentVoucher.objects.count() == 1
    assert SettlementRevision.objects.get(pk=revision_id).payment_vouchers.get().sha256 == response.data["data"]["sha256"]
    listed = api.get(endpoint)
    assert listed.status_code == 200 and listed.data["data"][0]["id"] == voucher_id
    assert "content" not in listed.data["data"][0]
    download = api.get(endpoint + f"{voucher_id}/download/")
    assert download.status_code == 200
    assert download["Content-Type"] == "application/pdf"
    assert "attachment" in download["Content-Disposition"]
    assert download["X-Content-Type-Options"] == "nosniff"
    assert download["Cache-Control"] == "private, no-store"
    assert b"".join(download.streaming_content) == content
    assert get(api, kind, target)["settlement"]["recorded_amount"] == before


def test_voucher_rejects_invalid_file_tenant_and_supplier_access(world):
    buyer, api, shipment = pilot(world)
    revision_id, _ = _settlement(api, "shipment", shipment)
    endpoint = _path("shipment", shipment.pk, revision_id)
    invalid = api.post(endpoint, {"file": SimpleUploadedFile("fake.pdf", b"not a pdf", "application/pdf")},
                       format="multipart", HTTP_IDEMPOTENCY_KEY="bad-voucher")
    assert invalid.status_code == 400
    external = supplier_user(world, world["supplier"], "voucher-supplier")
    external_api = APIClient(); external_api.force_authenticate(user=external)
    denied = external_api.get(endpoint)
    assert denied.status_code == 403
    other_scope = internal_user(world, "voucher-other-scope", DataScope.ScopeType.CUSTOM,
                                {"supplier_ids": [world["supplier_b"].pk]})
    scoped_api = APIClient(); scoped_api.force_authenticate(user=other_scope)
    hidden = scoped_api.get(endpoint)
    assert hidden.status_code == 404
    assert PaymentVoucher.objects.count() == 0


def test_voucher_size_and_fake_image_validation():
    from apps.supply_chain.payment_vouchers import _validate_file, MAX_BYTES
    from rest_framework.exceptions import ValidationError
    with pytest.raises(ValidationError):
        _validate_file(SimpleUploadedFile('fake.png',b'not an image','image/png'))
    class TooLarge:
        size=MAX_BYTES+1
        def read(self,*args): raise AssertionError('oversize should be rejected before reading')
    with pytest.raises(ValidationError): _validate_file(TooLarge())


def test_voucher_file_limit_and_other_tenant_download(world, monkeypatch):
    from apps.tenants.models import Tenant
    from apps.accounts.models import CustomUser
    from apps.supply_chain import payment_vouchers
    buyer,api,shipment=pilot(world)
    rev,_=_settlement(api,'shipment',shipment)
    endpoint=_path('shipment',shipment.pk,rev)
    monkeypatch.setattr(payment_vouchers,'MAX_PER_REVISION',1)
    def file(): return SimpleUploadedFile('receipt.pdf',b'%PDF-1.4\n%%EOF','application/pdf')
    saved=api.post(endpoint,{'file':file()},format='multipart',HTTP_IDEMPOTENCY_KEY='a')
    assert saved.status_code==201,saved.data
    refused=api.post(endpoint,{'file':file()},format='multipart',HTTP_IDEMPOTENCY_KEY='b')
    assert refused.status_code==400
    tenant=Tenant.objects.create(name='Other',code='other-voucher')
    other=CustomUser.objects.create_user(username='other-tenant-voucher',tenant=tenant,user_type='internal',is_superuser=True)
    other_api=APIClient();other_api.force_authenticate(user=other)
    assert other_api.get(endpoint+str(saved.data['data']['id'])+'/download/').status_code in (403,404)
