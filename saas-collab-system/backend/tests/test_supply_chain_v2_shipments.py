from decimal import Decimal
from io import BytesIO
import hashlib
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from openpyxl import Workbook
from apps.accounts.external_auth import issue_supplier_web_tokens
from apps.accounts.models import CustomUser
from apps.files.models import AttachmentFile
from apps.permissions.models import DataScope
from apps.supply_chain import services
from apps.supply_chain.models import BoxFileContent, BusinessEvent, ShipmentLine, SupplierContactAccount, SupplierShipment
from tests.test_supply_chain_v2_foundation import world, internal_user, supplier_user, confirmed_order, po_payload, freight

INTERNAL = "/api/internal/supply-chain/v2/"
EXTERNAL = "/api/external/supplier/supply-chain/v2/"
PASSWORD = "TestP3SampleContact!2026"


def buyer_client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def supplier_client(user):
    api = APIClient()
    api.credentials(HTTP_AUTHORIZATION="Bearer " + issue_supplier_web_tokens(user)["access"])
    return api


def write(api, path, data, key, method="post"):
    return getattr(api, method)(path, data, format="json", HTTP_IDEMPOTENCY_KEY=key)


def payload(world, order, quantity=4):
    return {"order_id": order.pk, "notes": "所有箱号见附件", "lines": [{"sku_id": world["sku"].pk, "quantity": quantity}]}


def draft(api, base, world, order, quantity=4, key="draft"):
    response = write(api, base + ("shipments/" if base == EXTERNAL else "supplier-shipments/"), payload(world, order, quantity), key)
    assert response.status_code == 201, response.data
    return response.data["data"]


def upload(api, path, obj, key="box", body=b"box_no,sku,quantity\n1,SC2-SKU,4\n", name="all-boxes.csv"):
    response = api.post(path + f"{obj['id']}/attachments/", {"file": SimpleUploadedFile(name, body), "expected_version": obj["version"]}, HTTP_IDEMPOTENCY_KEY=key)
    assert response.status_code == 200, response.data
    return response.data["data"]


def test_supplier_real_tokens_scoped_orders_and_channels(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    supplier = supplier_user(world, world["supplier"], "contact-a")
    supplier.set_password(PASSWORD); supplier.save()
    api = APIClient()
    login = api.post("/api/external/auth/login/", {"username": supplier.username, "password": PASSWORD})
    assert login.status_code == 200
    api.credentials(HTTP_AUTHORIZATION="Bearer " + login.data["access"])
    assert api.get(EXTERNAL + "me/").data["data"]["supplier_id"] == world["supplier"].pk
    assert api.get(INTERNAL + "purchase-orders/").status_code == 401
    assert APIClient().post("/api/internal/auth/login/", {"username": supplier.username, "password": PASSWORD}).status_code == 400
    data = api.get(EXTERNAL + f"purchase-orders/{order.pk}/").data["data"]
    assert "product_reference_price" not in data["lines"][0]
    assert "supplier_reference_price" not in data["lines"][0]
    other = supplier_user(world, world["supplier_b"], "contact-b")
    assert supplier_client(other).get(EXTERNAL + f"purchase-orders/{order.pk}/").status_code == 404
    assert buyer_client(buyer).get(EXTERNAL + "me/").status_code == 401
    supplier.is_active = False; supplier.save()
    assert api.get(EXTERNAL + "me/").status_code == 401


def test_shared_draft_preserves_buyer_price_and_history(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = supplier_client(supplier_user(world, world["supplier"], "contact-a"))
    root = EXTERNAL + "shipments/"
    obj = draft(api, EXTERNAL, world, order)
    assert obj["entry_mode"] == "supplier" and "unit_price" not in obj["lines"][0]
    assert write(api, root, payload(world, order), "draft").data["data"]["id"] == obj["id"]
    assert write(api, root, payload(world, order, 5), "draft").status_code == 422
    buyer_api = buyer_client(buyer)
    changed = write(buyer_api, INTERNAL + f"supplier-shipments/{obj['id']}/prices/",
        {"expected_version": obj["version"], "lines": [{"id": obj["lines"][0]["id"], "unit_price": "3.75"}]}, "adjust", "patch")
    assert changed.status_code == 200, changed.data
    obj = api.get(root + f"{obj['id']}/").data["data"]
    edited = write(api, root + f"{obj['id']}/", {"expected_version": obj["version"], "lines": [{**obj["lines"][0], "quantity": 12}]}, "edit", "patch")
    assert edited.status_code == 200, edited.data
    obj = edited.data["data"]
    assert ShipmentLine.objects.filter(shipment_id=obj["id"]).count() == 2
    assert ShipmentLine.objects.get(shipment_id=obj["id"], is_active=True).unit_price == Decimal("3.75")
    assert obj["lines"][0]["exception_type"] == "excess" and obj["lines"][0]["excess_quantity"] == 2
    assert write(api, root + f"{obj['id']}/submit/", {"expected_version": obj["version"]}, "early").status_code == 422
    obj = upload(api, root, obj)
    submitted = write(api, root + f"{obj['id']}/submit/", {"expected_version": obj["version"]}, "submit")
    assert submitted.data["data"]["status"] == "submitted"
    assert write(api, root + f"{obj['id']}/submit/", {"expected_version": obj["version"]}, "submit").status_code == 200
    assert write(api, root + f"{obj['id']}/", {"expected_version": obj["version"], "lines": obj["lines"]}, "late", "patch").status_code == 422


def test_extra_sku_split_shipments_and_duplicate_source_cumulative(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = supplier_client(supplier_user(world, world["supplier"], "supplier"))
    root = EXTERNAL + "shipments/"
    first = upload(api, root, draft(api, EXTERNAL, world, order, 8))
    assert write(api, root + f"{first['id']}/submit/", {"expected_version": first["version"]}, "first-submit").status_code == 200
    rows = [{"sku_id": world["sku"].pk, "quantity": 3}, {"sku_id": world["sku"].pk, "quantity": 4}, {"sku_id": world["sku_b"].pk, "quantity": 2}]
    created = write(api, root, {"order_id": order.pk, "lines": rows}, "second")
    assert created.status_code == 201, created.data
    second = upload(api, root, created.data["data"], key="second-box")
    submitted = write(api, root + f"{second['id']}/submit/", {"expected_version": second["version"]}, "second-submit").data["data"]
    assert [l["excess_quantity"] for l in submitted["lines"]] == [1, 4, 0]
    assert submitted["lines"][2]["exception_type"] == "additional"
    assert ShipmentLine.objects.get(pk=submitted["lines"][2]["id"]).unit_price is None


@pytest.mark.parametrize("forbidden", ["unit_price", "purchase_price_snapshot", "supplier_reference_price", "product_reference_price"])
def test_supplier_price_injection_and_atomic_rollback(world, forbidden):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = supplier_client(supplier_user(world, world["supplier"], "supplier"))
    data = payload(world, order)
    data["lines"][0][forbidden] = "1"
    assert write(api, EXTERNAL + "shipments/", data, "invalid").status_code == 403
    assert not SupplierShipment.objects.exists()


def test_private_attachment_own_acl_hash_removal_and_retention(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    user = supplier_user(world, world["supplier"], "supplier")
    api = supplier_client(user)
    root = EXTERNAL + "shipments/"
    obj = upload(api, root, draft(api, EXTERNAL, world, order))
    attachment = obj["attachments"][0]
    url = root + f"{obj['id']}/attachments/{attachment['id']}/download/"
    response = api.get(url)
    body = b"".join(response.streaming_content)
    assert hashlib.sha256(body).hexdigest() == attachment["sha256"]
    assert response["Cache-Control"] == "private, no-store" and "file_path" not in str(obj)
    assert APIClient().get(url).status_code == 401
    other = supplier_client(supplier_user(world, world["supplier_b"], "other"))
    assert other.get(url).status_code == 404
    own_only = buyer_client(internal_user(world, "own-buyer", scope=DataScope.ScopeType.OWN))
    assert own_only.get(INTERNAL + f"supplier-shipments/{obj['id']}/attachments/{attachment['id']}/download/").status_code == 404
    removed = write(api, root + f"{obj['id']}/attachments/{attachment['id']}/remove/", {"expected_version": obj["version"]}, "remove")
    assert removed.data["data"]["attachments"] == [] and BoxFileContent.objects.count() == 1
    assert api.get(url).status_code == 200
    assert AttachmentFile.objects.get().file_path.startswith("sc2-private:")


@pytest.mark.parametrize("name,body", [("boxes.exe", b"MZ"), ("boxes.pdf", b"notpdf"), ("boxes.xlsx", b"PKfake"), ("boxes.png", b"notpng"), ("boxes.csv", b"\x00")])
def test_box_file_format_validation_leaves_no_metadata(world, name, body):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = buyer_client(buyer)
    obj = draft(api, INTERNAL, world, order)
    r = api.post(INTERNAL + f"supplier-shipments/{obj['id']}/attachments/", {"file": SimpleUploadedFile(name, body), "expected_version": obj["version"]}, HTTP_IDEMPOTENCY_KEY="badfile")
    assert r.status_code == 422, r.data
    assert not AttachmentFile.objects.exists()


def test_valid_workbook_file_and_upload_retry_stale_version(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = buyer_client(buyer)
    root = INTERNAL + "supplier-shipments/"
    obj = draft(api, INTERNAL, world, order)
    book = Workbook(); book.active.append(["箱号", "SKU", "数量"])
    output = BytesIO(); book.save(output)
    changed = upload(api, root, obj, body=output.getvalue(), name="所有箱号.xlsx")
    repeat = upload(api, root, obj, body=output.getvalue(), name="所有箱号.xlsx")
    assert repeat["version"] == changed["version"] and BoxFileContent.objects.count() == 1
    stale = api.post(root + f"{obj['id']}/attachments/", {"file": SimpleUploadedFile("other.csv", b"1,2\n"), "expected_version": obj["version"]}, HTTP_IDEMPOTENCY_KEY="stale")
    assert stale.status_code == 422 and BoxFileContent.objects.count() == 1


def test_procurement_proxy_arrival_and_downstream_preserves_active_lines_only(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = buyer_client(buyer)
    root = INTERNAL + "supplier-shipments/"
    obj = draft(api, INTERNAL, world, order)
    changed = write(api, root + f"{obj['id']}/", {"expected_version": obj["version"], "lines": [{"sku_id": world["sku"].pk, "quantity": 6}]}, "edit", "patch").data["data"]
    changed = upload(api, root, changed)
    obj = write(api, root + f"{obj['id']}/submit/", {"expected_version": changed["version"]}, "submit").data["data"]
    assert obj["entry_mode"] == "procurement"
    arrival = write(api, root + f"{obj['id']}/arrival/", {"expected_version": obj["version"]}, "arrived")
    assert arrival.data["data"]["collection_arrived"] is True
    assert write(api, root + f"{obj['id']}/arrival/", {"expected_version": obj["version"]}, "arrived").status_code == 200
    batch = services.create_dispatch_batch(buyer, {"number":"B1", "shipment_ids":[obj["id"]], "freight_company_id":freight(world).pk,"freight_number":"F1"}, idempotency_key="batch")
    price = write(api, root + f"{obj['id']}/prices/", {"expected_version": arrival.data["data"]["version"], "lines": [{"id": obj["lines"][0]["id"], "unit_price":"5"}]}, "price", "patch")
    assert price.status_code == 422


def test_procurement_accounts_multiple_contacts_disable_login_and_safe_audit(world):
    buyer = internal_user(world)
    api = buyer_client(buyer)
    root = INTERNAL + f"suppliers/{world['supplier'].pk}/contacts/"
    data = {"username":"supplier-contact-1", "full_name":"张三", "password":PASSWORD}
    first = write(api, root, data, "account")
    assert first.status_code == 201, first.data
    obj = first.data["data"]
    assert "password" not in obj
    assert write(api, root, data, "account").data["data"]["id"] == obj["id"]
    assert write(api, root, {**data,"username":"supplier-contact-2"}, "account2").status_code == 201
    assert api.get(root).data["count"] == 2
    login = APIClient().post("/api/external/auth/login/", {"username":data["username"], "password":PASSWORD})
    assert login.status_code == 200
    supplier_api = APIClient();supplier_api.credentials(HTTP_AUTHORIZATION="Bearer " + login.data["access"])
    disabled = write(api, root + f"{obj['id']}/", {"expected_version":1,"full_name":"张三","is_active":False}, "disable", "patch")
    assert disabled.status_code == 200
    assert supplier_api.get(EXTERNAL + "me/").status_code == 401
    assert PASSWORD not in str(list(BusinessEvent.objects.filter(aggregate_type="suppliercontactaccount").values("payload")))
    assert SupplierContactAccount.objects.count() == 2
    user = CustomUser.objects.get(username=data["username"])
    assert not user.is_staff and not user.is_superuser and not user.groups.exists()


def test_account_scope_and_read_only_reject_writes(world):
    restricted = internal_user(world, "limited", scope=DataScope.ScopeType.CUSTOM, config={"supplier_ids":[world["supplier_b"].pk]})
    root = INTERNAL + f"suppliers/{world['supplier'].pk}/contacts/"
    assert buyer_client(restricted).get(root).status_code == 404
    assert write(buyer_client(restricted), root, {"username":"bad-contact","password":PASSWORD}, "bad").status_code == 404
    readonly = internal_user(world, "readonly", codes=("supply.v2.view",))
    assert write(buyer_client(readonly), root, {"username":"read-contact","password":PASSWORD}, "readonly").status_code == 403
    assert not SupplierContactAccount.objects.exists()


def test_partial_shipment_update_preserves_date_notes_and_lines(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    api = buyer_client(buyer)
    root = INTERNAL + "supplier-shipments/"
    r = write(api, root, {**payload(world, order), "shipment_date":"2026-10-01", "notes":"保留备注"}, "draft")
    obj = r.data["data"]
    update = write(api, root + f"{obj['id']}/", {"expected_version":1,"lines":[{"sku_id":world["sku"].pk,"quantity":7}]}, "lines-only", "patch")
    obj = update.data["data"]
    assert obj["shipment_date"] == "2026-10-01" and obj["notes"] == "保留备注"
    update = write(api, root + f"{obj['id']}/", {"expected_version":2,"notes":"更改备注"}, "notes-only", "patch")
    assert update.data["data"]["lines"][0]["quantity"] == 7


def test_reset_disabled_account_preserves_name_and_disabled_status(world):
    api = buyer_client(internal_user(world))
    root = INTERNAL + f"suppliers/{world['supplier'].pk}/contacts/"
    created = write(api, root, {"username":"disabled-contact","full_name":"保留姓名","password":PASSWORD,"is_active":False}, "contact").data["data"]
    changed = write(api, root + f"{created['id']}/", {"expected_version":1,"password":"NewP3Sample!2026"}, "password-only", "patch")
    assert changed.status_code == 200, changed.data
    obj = changed.data["data"]
    assert obj["full_name"] == "保留姓名" and obj["is_active"] is False
    assert APIClient().post("/api/external/auth/login/", {"username":obj["username"],"password":"NewP3Sample!2026"}).status_code == 401


@pytest.mark.parametrize("data", [[], {"lines":[{"sku_id":[],"quantity":1}]}, {"order_id":"bad","lines":[]}, {"lines":[None]}])
def test_malformed_shipment_payload_is_rejected_without_server_error(world, data):
    api = buyer_client(internal_user(world))
    response = write(api, INTERNAL + "supplier-shipments/", data, "malformed")
    assert response.status_code in (400, 422) and not SupplierShipment.objects.exists()


def test_shipment_notes_search_filters_before_pagination_for_both_portals(world):
    buyer = internal_user(world)
    order = confirmed_order(world, buyer)
    internal = buyer_client(buyer)
    first = draft(internal, INTERNAL, world, order, key="search-first")
    second = draft(internal, INTERNAL, world, order, key="search-second")
    assert write(internal, INTERNAL + f"supplier-shipments/{first['id']}/", {"expected_version": first["version"], "notes": "急件 ABC 装柜优先"}, "search-note-first", "patch").status_code == 200
    assert write(internal, INTERNAL + f"supplier-shipments/{second['id']}/", {"expected_version": second["version"], "notes": "普通发货"}, "search-note-second", "patch").status_code == 200
    external = supplier_client(supplier_user(world, world["supplier"], "notes-search"))
    for api, path in [(internal, INTERNAL + "supplier-shipments/"), (external, EXTERNAL + "shipments/")]:
        response = api.get(path, {"search": "  abc  ", "limit": 1})
        assert response.status_code == 200, response.data
        assert response.data["count"] == 1
        assert response.data["data"][0]["id"] == first["id"]
        assert api.get(path, {"search": "不存在的备注"}).data["count"] == 0
        assert api.get(path, {"search": "   "}).data["count"] == 2
        assert api.get(path, {"search": "装柜", "status": "submitted"}).data["count"] == 0
