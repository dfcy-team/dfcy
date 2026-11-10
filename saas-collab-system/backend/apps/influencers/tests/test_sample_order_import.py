import csv
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from io import StringIO
from threading import Event
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import close_old_connections, connection
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.accounts.models import CustomUser
from apps.audit.models import OperationLog
from apps.influencers import sample_import
from apps.influencers.models import (
    BdSampleAttributionSnapshot, ImportBatch, Influencer, InfluencerProfile, SampleFulfillment, SampleItem,
)
from apps.influencers.sample_import_csv import CSV_COLUMNS, MAX_FILE_BYTES, parse_order_csv
from apps.influencers.services import (
    SAMPLE_ORDER_CSV_SOURCE, create_sample_fulfillment, soft_delete_sample_fulfillment, update_sample_fulfillment,
)
from apps.masterdata.models import PlatformMaster, StoreMaster, WarehouseMaster
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.tenants.models import Tenant


ROOT = "/api/internal/influencers/sample-import/"


def _records(code, *, scoped=False, permission=sample_import.PERMISSION):
    tenant = Tenant.objects.create(code=code, name=code)
    actor = CustomUser.objects.create_user(username=f"{code}-bd", full_name="Sample BD", tenant=tenant, user_type="internal")
    role = Role.objects.create(tenant=tenant, code="bd", name="BD")
    UserRole.objects.create(tenant=tenant, user=actor, role=role)
    role.permissions.add(Permission.objects.get_or_create(
        code=permission, defaults={"name": permission, "module": "influencers", "action": "manage"},
    )[0])
    platform = PlatformMaster.objects.create(tenant=tenant, code="tk", name="TikTok", platform_type="tiktok")
    store = StoreMaster.objects.create(
        tenant=tenant, platform=platform, code="tk4ph", name="Example BigSeller",
        platform_store_name="Example Platform Store", country_code="PH", currency="PHP",
    )
    warehouse = WarehouseMaster.objects.create(
        tenant=tenant, code="ph-wms", name="Example Warehouse", legacy_codes=["Example Export Warehouse"],
        country_code="PH", warehouse_type="third_party",
    )
    scope = DataScope.objects.create(
        tenant=tenant, role=role, scope_type="custom" if scoped else "all",
        config={"store_ids": [store.pk], "warehouse_ids": [warehouse.pk]} if scoped else {"all": True},
    )
    client = _client(actor)
    return SimpleNamespace(**locals())


def _client(actor):
    client = APIClient()
    client.force_authenticate(actor)
    return client


def _creator(records, code, name="Creator", market="PH", handle=""):
    influencer = Influencer.objects.create(
        tenant=records.tenant, code=code, name=name, platform="TikTok", handle=handle,
    )
    InfluencerProfile.objects.create(tenant=records.tenant, influencer=influencer, market=market)
    return influencer


def _row(order="6900000000000000001", **fields):
    return {
        "order_no": order, "platform": "TikTok", "big_seller_store": "Example BigSeller",
        "platform_store": "Example Platform Store", "country": "Philippines",
        "external_product_id": "1780000000000000001", "product_sku": "SKU-001", "shop_sku": "SHOP-001",
        "quantity": "1", "warehouse_name": "Example Export Warehouse", "sample_sent_at": "2026-11-09 16:57",
        "shipped_at": "2026-11-10 13:37", "source_status": "已交运", "cancelled_at": "", "is_outbound": "Yes",
        **fields,
    }


def _file(*rows, encoding="utf-8-sig"):
    stream = StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(CSV_COLUMNS)
    writer.writerows([row[key] for key in CSV_COLUMNS.values()] for row in rows)
    return SimpleUploadedFile("orders.csv", stream.getvalue().encode(encoding), content_type="text/csv")


def _preview(client, *rows, encoding="utf-8-sig"):
    response = client.post(ROOT + "preview/", {"file": _file(*rows, encoding=encoding)}, format="multipart")
    assert response.status_code == 200, response.json()
    return response.json()["data"]


def _entry(order, nickname="Creator", **extra):
    return {
        **order, "nickname": nickname, "link_type": "direct", "confirm_recent_duplicate": False,
        "confirmation_reason": "", **extra,
    }


def _payload(orders, key="sample-test", **extra):
    return {
        "orders": orders, "request_key": key, "source_timezone": "Asia/Shanghai",
        "timezone_confirmed": True, **extra,
    }


def _confirm(client, entries, key="sample-test", **extra):
    return client.post(ROOT + "confirm/", _payload(entries, key, **extra), format="json")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "gb18030"])
def test_parse_groups_sku_lines_and_preserves_source_times(encoding):
    groups, count = parse_order_csv(_file(
        _row(quantity="2"),
        _row(quantity="3"),
        _row(product_sku="SKU-002", shop_sku="SHOP-002"),
        _row("6900000000000000002", shipped_at="", source_status="待打单", is_outbound="No"),
        encoding=encoding,
    ))
    assert count == 4
    first, pending = groups
    assert first["order_no"] == "6900000000000000001"
    assert first["row_numbers"] == [2, 3, 4]
    assert [(item["requested_sku"], item["quantity"]) for item in first["items"]] == [("SKU-001", 5), ("SKU-002", 1)]
    assert first["sample_sent_at"] == "2026-11-09T16:57:00+08:00"
    assert first["shipped_at"] == "2026-11-10T13:37:00+08:00"
    assert pending["status"] == "pending" and pending["shipped_at"] is None


@pytest.mark.parametrize("changed", [
    {"big_seller_store": "Other shop"},
    {"external_product_id": "1780000000000000002"},
    {"shipped_at": "", "is_outbound": "No"},
    {"shipped_at": "2026-11-08 13:37"},
    {"sample_sent_at": "2026-11-09T16:57:00Z"},
    {"cancelled_at": "2026-11-10 13:38"},
    {"quantity": "0"},
    {"external_product_id": "1.78e18"},
])
def test_bad_sku_line_invalidates_entire_order(changed):
    groups, _ = parse_order_csv(_file(_row(), _row(**changed)))
    assert len(groups) == 1
    assert groups[0]["errors"][0]["row_number"] == 3


def test_csv_bounds_and_headers():
    with pytest.raises(ValidationError, match="500"):
        parse_order_csv(_file(*[_row()] * 501))
    with pytest.raises(ValidationError, match="2 MiB"):
        parse_order_csv(SimpleUploadedFile("large.csv", b"x" * (MAX_FILE_BYTES + 1)))
    with pytest.raises(ValidationError, match="15"):
        parse_order_csv(SimpleUploadedFile("bad.csv", b"order,sku\n1,2"))


@pytest.mark.django_db
def test_read_only_preview_and_confirm_status_audit_and_idempotency():
    r = _records("csv-status")
    with CaptureQueriesContext(connection) as queries:
        preview = _preview(
            r.client,
            _row(quantity="2"),
            _row(product_sku="SKU-002", shop_sku="SHOP-002"),
            _row("6900000000000000002", shipped_at="", source_status="待打单", is_outbound="No"),
            encoding="gb18030",
        )
    assert not any(query["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for query in queries)
    assert not Influencer.objects.filter(tenant=r.tenant).exists()
    assert not ImportBatch.objects.filter(tenant=r.tenant).exists()
    assert not OperationLog.objects.filter(tenant=r.tenant).exists()
    assert preview["owner"]["id"] == r.actor.pk
    assert preview["source_timezone"] == "Asia/Shanghai"
    assert preview["valid_count"] == 2
    assert preview["orders"][0]["warehouse_id"] == r.warehouse.pk

    orders = [
        _entry(preview["orders"][0], "Creator A", owner=999, calculated_cost=123),
        _entry(preview["orders"][1], "Creator B", link_type="PKDJ"),
    ]
    response = _confirm(r.client, orders)
    assert response.status_code == 200, response.json()
    data = response.json()["data"]
    assert data["mode"] == "partial" and data["created_count"] == 2
    assert [row["fulfillment_status"] for row in data["results"]] == ["shipped", "pending"]
    shipped, pending = [SampleFulfillment.objects.get(pk=row["fulfillment_id"]) for row in data["results"]]
    assert shipped.owner_id == pending.owner_id == r.actor.pk
    assert shipped.store_id == r.store.pk and shipped.outreach_task_id is None
    assert shipped.source == SAMPLE_ORDER_CSV_SOURCE
    assert shipped.sample_sent_at == datetime.fromisoformat("2026-11-09T16:57:00+08:00")
    assert shipped.shipped_at == datetime.fromisoformat("2026-11-10T13:37:00+08:00")
    assert pending.sample_sent_at == shipped.sample_sent_at and pending.shipped_at is None
    assert shipped.calculated_cost is None
    assert list(shipped.items.order_by("requested_sku").values_list("requested_sku", "quantity", "warehouse_id")) == [
        ("SKU-001", 2, r.warehouse.pk), ("SKU-002", 1, r.warehouse.pk),
    ]
    assert shipped.influencer.handle == "" and shipped.influencer.profile.market == "PH"
    assert list(shipped.status_events.values_list("to_status", "reason")) == [
        ("pending", "created"), ("shipped", "sample_order_csv_shipped"),
    ]
    assert BdSampleAttributionSnapshot.objects.get(fulfillment=shipped).shipped_at == shipped.shipped_at
    assert BdSampleAttributionSnapshot.objects.get(fulfillment=pending).sample_status == "pending"
    pending = update_sample_fulfillment(user=r.actor, fulfillment=pending, expected_version=pending.version,
                                        validated_data={"notes": "No shipment yet"})
    assert pending.status == "pending" and pending.shipped_at is None

    replay = _confirm(r.client, orders).json()["data"]
    assert replay["replayed"] is True
    assert replay["results"] == data["results"]
    assert _confirm(r.client, [{**orders[0], "nickname": "Different"}]).status_code == 409
    assert _confirm(r.client, orders, "different-key").json()["data"]["conflict_count"] == 2
    assert SampleFulfillment.objects.filter(tenant=r.tenant).count() == 2
    assert OperationLog.objects.filter(tenant=r.tenant, action="sample_order_import_created").count() == 2


@pytest.mark.django_db
def test_timezone_confirmation_and_signed_facts_cannot_be_forged():
    r = _records("csv-signing")
    order = _preview(r.client, _row())["orders"][0]
    entries = [_entry(order)]
    for bad in ({"timezone_confirmed": False}, {"timezone_confirmed": "true"}, {"source_timezone": "UTC"}):
        assert _confirm(r.client, entries, **bad).status_code == 400
    payload = _payload(entries)
    payload.pop("timezone_confirmed")
    assert r.client.post(ROOT + "confirm/", payload, format="json").status_code == 400
    assert not ImportBatch.objects.filter(tenant=r.tenant).exists()
    response = _confirm(r.client, [_entry(order, shipped_at=None), _entry(order, preview_token="tampered")])
    assert [row["code"] for row in response.json()["data"]["results"]] == ["preview_changed", "preview_required"]
    assert not SampleFulfillment.objects.filter(tenant=r.tenant).exists()
    assert not Influencer.objects.filter(tenant=r.tenant).exists()
    with pytest.raises(ValidationError, match="reserved"):
        create_sample_fulfillment(user=r.actor, request_key="fake-source",
                                  validated_data={"source": SAMPLE_ORDER_CSV_SOURCE}, item_payloads=[])


@pytest.mark.django_db
def test_scopes_and_nickname_resolution_fail_closed():
    r = _records("csv-scoped", scoped=True)
    other = _records("csv-other")
    limited = _records("csv-no-manage", permission="influencers.fulfillment.view")
    outside = StoreMaster.objects.create(
        tenant=r.tenant, platform=r.platform, code="tk5ph", name="Other BigSeller",
        platform_store_name="Other Platform Store", country_code="PH", currency="PHP",
    )
    WarehouseMaster.objects.create(
        tenant=r.tenant, code="outside", name="Other warehouse", country_code="PH", warehouse_type="third_party",
    )
    assert limited.client.post(ROOT + "preview/", {"file": _file(_row())}, format="multipart").status_code == 403
    assert _confirm(limited.client, [{}]).status_code == 403
    preview = _preview(
        r.client, _row(),
        _row("store-outside", big_seller_store=outside.name, platform_store=outside.platform_store_name),
        _row("warehouse-outside", warehouse_name="Other warehouse"),
        _row("shop-conflict", platform_store=outside.platform_store_name),
    )
    assert [row["errors"][0]["code"] for row in preview["orders"][1:]] == [
        "store_unavailable", "warehouse_unavailable", "store_unavailable",
    ]
    order = preview["orders"][0]
    foreign = _creator(other, "foreign")
    outside_creator = _creator(r, "out-of-scope", market="MY")
    visible = _creator(r, "within-scope")
    assert _confirm(other.client, [_entry(order)]).json()["data"]["results"][0]["code"] == "preview_required"
    for key, pk in enumerate((foreign.pk, outside_creator.pk)):
        result = _confirm(r.client, [_entry(order, influencer_id=pk)], f"outside-{key}").json()["data"]["results"][0]
        assert result["code"] == "influencer_unavailable"
    result = _confirm(r.client, [_entry(order)]).json()["data"]["results"][0]
    assert result["status"] == "needs_influencer"
    assert [row["id"] for row in result["candidates"]] == [visible.pk]
    created = _confirm(r.client, [_entry(order, influencer_id=visible.pk)], "chosen").json()["data"]["results"][0]
    assert SampleFulfillment.objects.get(pk=created["fulfillment_id"]).influencer_id == visible.pk
    assert Influencer.objects.filter(tenant=r.tenant).count() == 2


@pytest.mark.django_db
def test_existing_order_conflicts_are_global_generic_and_include_deleted():
    r = _records("csv-global")
    other = _records("csv-global-other")
    order = _preview(r.client, _row())["orders"][0]
    creator = _creator(other, "foreign", name="Foreign private nickname")
    original, _ = create_sample_fulfillment(
        user=other.actor, request_key="legacy", item_payloads=[],
        validated_data={
            "influencer": creator, "store": other.store, "link_type": "direct", "sample_order_no": order["order_no"],
        },
    )
    # Even a soft-deleted prior fulfillment reserves the order number.
    soft_delete_sample_fulfillment(user=other.actor, fulfillment=original, expected_version=original.version)
    conflict = _preview(r.client, _row())["orders"][0]
    assert conflict["preview_token"] is None and conflict["errors"][0]["code"] == "order_conflict"
    response = _confirm(r.client, [_entry(order, confirm_recent_duplicate=True, confirmation_reason="Override")])
    result = response.json()["data"]["results"][0]
    assert result["status"] == "conflict"
    assert "fulfillment_id" not in result and creator.name not in response.content.decode()
    assert not Influencer.objects.filter(tenant=r.tenant).exists()


@pytest.mark.django_db
def test_recent_duplicate_uses_product_across_stores_and_source_chronology():
    r = _records("csv-recent")
    creator = _creator(r, "creator", handle="same.creator")
    alias = _creator(r, "alias", name="Older Creator", handle="same.creator")
    other_store = StoreMaster.objects.create(
        tenant=r.tenant, platform=r.platform, code="tk5ph", name="Other store", country_code="PH", currency="PHP",
    )
    order = _row("cross-store")
    date = datetime.fromisoformat("2026-11-09T16:57:00+08:00")
    older = SampleFulfillment.objects.create(
        tenant=r.tenant, owner=r.actor, influencer=alias, store=other_store,
        fulfillment_no="OLDER", request_key="older", request_hash="x" * 64,
        sample_sent_at=date - timedelta(days=30),
    )
    SampleItem.objects.create(
        tenant=r.tenant, fulfillment=older, site_code="PH", external_product_id=order["external_product_id"],
    )
    token = _preview(r.client, order)["orders"][0]
    missing_reason = _confirm(r.client, [_entry(token, confirm_recent_duplicate=True, confirmation_reason=" ")])
    assert missing_reason.json()["data"]["results"][0]["status"] == "needs_confirmation"
    authorized = _confirm(r.client, [_entry(token, confirm_recent_duplicate=True, confirmation_reason="New campaign")], "approve")
    row = authorized.json()["data"]["results"][0]
    assert row["status"] == "created"
    assert SampleFulfillment.objects.get(pk=row["fulfillment_id"]).influencer_id == creator.pk
    audit = OperationLog.objects.get(tenant=r.tenant, action="sample_order_import_created", object_id=row["fulfillment_id"])
    assert audit.after_data["confirmation_reason"] == "New campaign"

    product = "1780000000000000002"
    preview = _preview(r.client,
        _row("later", external_product_id=product),
        _row("earlier", external_product_id=product, sample_sent_at="2026-11-01 16:57"),
    )["orders"]
    results = _confirm(r.client, [_entry(row) for row in preview], "chronology").json()["data"]["results"]
    assert [(row["order_no"], row["status"]) for row in results] == [
        ("later", "needs_confirmation"), ("earlier", "created"),
    ]


@pytest.mark.django_db
def test_invalid_order_rolls_back_draft_items_and_audit_with_partial_success(monkeypatch):
    r = _records("csv-savepoint")
    good, bad = _preview(r.client, _row("good"), _row("bad"))["orders"]
    create = sample_import.create_sample_fulfillment

    def failing_create(**kwargs):
        fulfillment, created = create(**kwargs)
        if fulfillment.sample_order_no == "bad":
            raise ValidationError({"items": "Synthetic failure after all row writes"})
        return fulfillment, created

    monkeypatch.setattr(sample_import, "create_sample_fulfillment", failing_create)
    response = _confirm(r.client, [_entry(good, "Good"), _entry(bad, "Bad")])
    assert response.status_code == 200, response.json()
    assert [row["status"] for row in response.json()["data"]["results"]] == ["created", "invalid"]
    assert list(Influencer.objects.filter(tenant=r.tenant).values_list("name", flat=True)) == ["Good"]
    assert SampleFulfillment.objects.filter(tenant=r.tenant).count() == 1
    assert SampleItem.objects.filter(tenant=r.tenant).count() == 1
    assert BdSampleAttributionSnapshot.objects.filter(tenant=r.tenant).count() == 1
    assert OperationLog.objects.filter(tenant=r.tenant, action="create_from_fulfillment").count() == 1


@pytest.mark.django_db
def test_maximum_sku_rows_replay_without_receipt_truncation():
    r = _records("csv-full")
    order = _preview(r.client, *[_row()] * 500)["orders"][0]
    entry = _entry(order)
    first = _confirm(r.client, [entry]).json()["data"]
    replay = _confirm(r.client, [entry]).json()["data"]
    assert len(replay["results"][0]["row_numbers"]) == 500
    assert first["results"] == replay["results"]
    assert _confirm(r.client, [entry, entry], "too-many").status_code == 400


@pytest.mark.django_db(transaction=True)
def test_concurrent_sqlite_imports_cannot_create_the_same_order_in_two_tenants(monkeypatch):
    if connection.vendor != "sqlite":
        pytest.skip("Exercises SQLite's cross-connection writer lock.")
    r = _records("csv-concurrency-a")
    other = _records("csv-concurrency-b")
    entry = _entry(_preview(r.client, _row())["orders"][0])
    other_entry = _entry(_preview(other.client, _row())["orders"][0])
    created = Event()
    allow_commit = Event()
    confirm_order = sample_import._confirm_order

    def delayed_confirm(actor, *args):
        result = confirm_order(actor, *args)
        if actor.pk == r.actor.pk:
            created.set()
            assert allow_commit.wait(timeout=15)
        return result

    def submit(actor, row):
        close_old_connections()
        try:
            return _confirm(_client(actor), [row])
        finally:
            close_old_connections()

    monkeypatch.setattr(sample_import, "_confirm_order", delayed_confirm)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(submit, r.actor, entry)
        try:
            assert created.wait(timeout=10)
            second = executor.submit(submit, other.actor, other_entry)
            assert second.result(timeout=10).status_code == 503
        finally:
            allow_commit.set()
        assert first.result(timeout=10).json()["data"]["created_count"] == 1
    assert _confirm(other.client, [other_entry]).json()["data"]["conflict_count"] == 1
    assert SampleFulfillment.objects.filter(sample_order_no=entry["order_no"]).count() == 1
