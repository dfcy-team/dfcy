import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from apps.tenants.models import Tenant
from apps.supply_chain.models import (PurchaseContract, PurchaseContractSignature,
    PurchaseContractSignatureAttachment, domain_write)
from tests.test_supply_chain_purchase_contracts import submitted_shipment
from tests.test_supply_chain_v2_shipments import INTERNAL, buyer_client, draft, upload, write
from tests.test_supply_chain_v2_foundation import world, internal_user, confirmed_order, po_payload


def pdf(name="signed.pdf", payload=b"%PDF-1.4\ncopy\n%%EOF"):
    return SimpleUploadedFile(name, payload, content_type="application/pdf")


@pytest.mark.django_db
def test_issued_contract_signature_upload_status_idempotency_and_download(submitted_shipment, world):
    user, api, shipment = submitted_shipment
    with domain_write():
        contract = PurchaseContract.objects.create(tenant=user.tenant, created_by=user,
            shipment_id=shipment["id"], nature="corporate", status="issued", number="CC-TEST",
            payload={"buyer": {"name": "Buyer"}, "seller": {"name": "Seller"}, "lines": [{"unit_price": "1", "tax_rate": "0"}], "contract_date": "2026-10-30"},
            source_version=shipment["version"])
    base = INTERNAL + f"supplier-shipments/{shipment['id']}/purchase-contract/signatures/"
    empty = api.get(base)
    assert empty.status_code == 200 and empty.data["data"]["version"] == 1
    assert empty.data["data"]["attachments"] == [] and empty.data["data"]["status"] == "pending"
    bad = api.post(base, {"file": SimpleUploadedFile("bad.pdf", b"bad")}, format="multipart",
                   HTTP_IDEMPOTENCY_KEY="sig-bad")
    assert bad.status_code == 400
    first = api.post(base, {"file": pdf()}, format="multipart", HTTP_IDEMPOTENCY_KEY="sig-1")
    assert first.status_code == 201 and first.data["data"]["version"] == 2
    replay = api.post(base, {"file": pdf()}, format="multipart", HTTP_IDEMPOTENCY_KEY="sig-1")
    assert replay.status_code == 200 and replay.data["data"]["version"] == 2
    conflict = api.post(base, {"file": pdf(payload=b"%PDF-1.4\nother\n%%EOF")}, format="multipart",
                        HTTP_IDEMPOTENCY_KEY="sig-1")
    assert conflict.status_code == 409
    status_url = base + "status/"
    signed = api.post(status_url, {"expected_version": 2, "status": "signed", "signed_date": "2026-10-30", "reason": "双方已盖章"},
                      format="json", HTTP_IDEMPOTENCY_KEY="sig-status-1")
    assert signed.status_code == 200 and signed.data["data"]["status"] == "signed"
    assert signed.data["data"]["version"] == 3 and len(signed.data["data"]["history"]) == 1
    status_replay = api.post(status_url, {"expected_version": 2, "status": "signed", "signed_date": "2026-10-30", "reason": "双方已盖章"},
                             format="json", HTTP_IDEMPOTENCY_KEY="sig-status-1")
    assert status_replay.status_code == 200 and status_replay.data["data"]["version"] == 3
    status_key_conflict = api.post(status_url, {"expected_version": 2, "status": "signed", "signed_date": "2026-10-30", "reason": "不同原因"},
                                   format="json", HTTP_IDEMPOTENCY_KEY="sig-status-1")
    assert status_key_conflict.status_code == 409
    stale = api.post(status_url, {"expected_version": 2, "status": "pending", "signed_date": None, "reason": "撤回"},
                     format="json", HTTP_IDEMPOTENCY_KEY="sig-status-stale")
    assert stale.status_code == 409
    attachment = signed.data["data"]["attachments"][0]
    downloaded = api.get(attachment["download_url"])
    assert downloaded.status_code == 200
    assert downloaded["Cache-Control"] == "private, no-store" and downloaded["X-Content-Type-Options"] == "nosniff"
    added = api.post(base, {"file": pdf("new.pdf", b"%PDF-1.4\nnew\n%%EOF")}, format="multipart", HTTP_IDEMPOTENCY_KEY="sig-2")
    assert added.status_code == 201 and added.data["data"]["status"] == "pending"
    assert added.data["data"]["version"] == 4 and added.data["data"]["history"][0]["status"] == "pending"
    viewer = internal_user(world, "signature-issued-viewer", codes=("supply.v2.view",))
    readonly = buyer_client(viewer)
    assert readonly.get(base).status_code == 200
    assert readonly.post(base, {"file": pdf()}, format="multipart", HTTP_IDEMPOTENCY_KEY="viewer-upload").status_code in {401, 403}


@pytest.mark.django_db
def test_signature_requires_issued_contract_and_manage_permission(submitted_shipment, world):
    user, api, shipment = submitted_shipment
    with domain_write():
        PurchaseContract.objects.create(tenant=user.tenant, created_by=user, shipment_id=shipment["id"],
            nature="corporate", status="draft", number=None, payload={"buyer": {"name": "Buyer"}},
            source_version=shipment["version"])
    base = INTERNAL + f"supplier-shipments/{shipment['id']}/purchase-contract/signatures/"
    assert api.get(base).status_code == 404
    assert api.post(base, {"file": pdf()}, format="multipart", HTTP_IDEMPOTENCY_KEY="draft-file").status_code == 404
    viewer = internal_user(world, "signature-viewer", codes=("supply.v2.view",))
    view_api = buyer_client(viewer)
    assert view_api.get(base).status_code == 404  # Draft contracts are not exposed as signed records.


@pytest.mark.django_db
def test_signature_download_is_tenant_scoped_and_upload_limits_apply(submitted_shipment, world):
    user, api, shipment = submitted_shipment
    with domain_write():
        contract = PurchaseContract.objects.create(tenant=user.tenant, created_by=user, shipment_id=shipment["id"],
            nature="corporate", status="issued", number="CC-LIMIT", payload={"buyer": {"name": "Buyer"}},
            source_version=shipment["version"])
        signature = PurchaseContractSignature.objects.create(tenant=user.tenant, created_by=user, contract=contract)
        for i in range(20):
            PurchaseContractSignatureAttachment.objects.create(tenant=user.tenant, signature=signature, created_by=user,
                file_name=f"{i}.pdf", media_type="application/pdf", byte_size=15, sha256="0"*64,
                idempotency_key=f"seed-{i}", content=b"%PDF-1.4\n%%EOF")
    base = INTERNAL + f"supplier-shipments/{shipment['id']}/purchase-contract/signatures/"
    over_limit = pdf(payload=b"%PDF-1.4\n" + b"x"*(10*1024*1024) + b"\n%%EOF")
    assert api.post(base, {"file": over_limit}, format="multipart", HTTP_IDEMPOTENCY_KEY="too-large").status_code == 400
    at_limit = api.post(base, {"file": pdf("twenty-one.pdf")}, format="multipart", HTTP_IDEMPOTENCY_KEY="too-many")
    assert at_limit.status_code == 400
    other = {"tenant": Tenant.objects.create(name="Signature outsider", code="signature-outsider")}
    outsider = internal_user(other, "signature-outsider-user", codes=("supply.v2.view",))
    outsider_api = buyer_client(outsider)
    attachment_url = base + f"{signature.attachments.first().pk}/download/"
    assert outsider_api.get(attachment_url).status_code == 404
    second_order = confirmed_order(world, user, key="sig-cross-shipment",
                                   payload=po_payload(world, "sig-cross-shipment", number="PO-SIG-CROSS"))
    second_shipment = draft(api, INTERNAL, world, second_order, key="signature-other-shipment")
    second_shipment = upload(api, INTERNAL + "supplier-shipments/", second_shipment, key="signature-other-box")
    submitted = write(api, INTERNAL + f"supplier-shipments/{second_shipment['id']}/submit/",
                      {"expected_version": second_shipment["version"]}, "signature-other-submit")
    assert submitted.status_code == 200
    cross_shipment_url = INTERNAL + f"supplier-shipments/{second_shipment['id']}/purchase-contract/signatures/{signature.attachments.first().pk}/download/"
    assert api.get(cross_shipment_url).status_code == 404
