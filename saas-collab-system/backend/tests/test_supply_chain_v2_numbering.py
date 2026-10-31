from datetime import date, datetime, timezone

import pytest
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from apps.permissions.models import DataScope
from apps.supply_chain import services
from apps.supply_chain.dates import business_date
from apps.supply_chain.models import DocumentNumberCounter, DocumentNumberRule, PurchaseOrder, SupplierShipment, domain_write
from apps.supply_chain.numbering import number_for, period_key, preview
from apps.supply_chain import shipments
from apps.masterdata.models import WarehouseMaster
from apps.sales_management import operating
from apps.sales_management.operating_models import OperatingOrderLine
from tests.test_supply_chain_v2_foundation import confirmed_order, freight, internal_user, po_payload, shipment_payload, supplier_user, world


BASE = "/api/internal/supply-chain/v2/"


def client(user):
    api = APIClient()
    api.force_authenticate(user=user)
    return api


def config(world, actor, kind="purchase_order", **overrides):
    values = {"enabled": True, "include_country": True, "country_prefixes": {},
        "prefix": "PO", "date_format": "YYYYMMDD", "separator": "-",
        "sequence_width": 4, "reset_period": "day", **overrides}
    with domain_write():
        return DocumentNumberRule.objects.create(tenant=world["tenant"], created_by=actor, kind=kind, **values)


def test_country_streams_default_prefix_overrides_and_preview_is_read_only(world):
    actor = internal_user(world)
    rule = config(world, actor, country_prefixes={"CA": "CAN"})
    today = business_date()
    ca = preview("purchase_order", {f: getattr(rule, f) for f in (
        "enabled", "include_country", "country_prefixes", "prefix", "date_format", "separator", "sequence_width", "reset_period")},
        world["tenant"].pk, day=today, country_code="CA")
    us = preview("purchase_order", {f: getattr(rule, f) for f in (
        "enabled", "include_country", "country_prefixes", "prefix", "date_format", "separator", "sequence_width", "reset_period")},
        world["tenant"].pk, day=today, country_code="US")
    assert ca["example"] == f"CAN-PO-{today:%Y%m%d}-0001"
    assert us["example"] == f"US-PO-{today:%Y%m%d}-0001"
    assert not DocumentNumberCounter.objects.exists()
    with transaction.atomic(), domain_write():
        assert number_for(actor, "purchase_order", "legacy", "CA") == ca["example"]
    with transaction.atomic(), domain_write():
        assert number_for(actor, "purchase_order", "legacy", "US") == us["example"]
    assert DocumentNumberCounter.objects.filter(country_code="CA").get().value == 1
    assert DocumentNumberCounter.objects.filter(country_code="US").get().value == 1


def test_custom_preview_uses_no_separator_by_default_and_keeps_optional_separator(world):
    actor = internal_user(world)
    today = business_date()
    no_separator = {"enabled": True, "include_country": True, "country_prefixes": {}, "prefix": "PO",
        "date_format": "YYYYMMDD", "separator": "none", "sequence_width": 3, "reset_period": "day"}
    assert preview("purchase_order", no_separator, world["tenant"].pk, day=today,
        country_code="US")["example"] == f"USPO{today:%Y%m%d}001"
    no_separator["separator"] = "-"
    assert preview("purchase_order", no_separator, world["tenant"].pk, day=today,
        country_code="US")["example"] == f"US-PO-{today:%Y%m%d}-001"


def test_rules_validate_date_granularity_country_ownership_and_unique_prefixes(world):
    actor = internal_user(world)
    data = {"enabled": True, "include_country": True, "country_prefixes": {"US": "SAME", "CA": "SAME"},
        "prefix": "PO", "date_format": "YYYYMM", "separator": "-", "sequence_width": 3,
        "reset_period": "day", "tenant_id": world["tenant"].pk}
    with pytest.raises(DjangoValidationError, match="日期格式"):
        from apps.supply_chain.numbering import validate_rule
        validate_rule(data)
    data["date_format"] = "YYYYMMDD"
    with pytest.raises(DjangoValidationError, match="同时用于"):
        validate_rule(data)
    data["country_prefixes"] = {"ZZ": "ZZ"}
    with pytest.raises(DjangoValidationError, match="不属于当前租户"):
        validate_rule(data)
    data.update(country_prefixes={}, reset_period="never", date_format="none")
    assert validate_rule(data)["date_format"] == "none"


def test_creation_rollback_and_replay_do_not_consume_numbers(world):
    actor = internal_user(world)
    config(world, actor, include_country=False)
    bad = po_payload(world, number=None, lines=[{"sku_id": 999999, "quantity": 1, "unit_price": "1"}])
    with pytest.raises(DjangoValidationError):
        services.create_purchase_order(actor, bad, idempotency_key="bad-create")
    assert not DocumentNumberCounter.objects.exists()
    payload = po_payload(world, number=None)
    first = services.create_purchase_order(actor, payload, idempotency_key="numbered-create")
    replay = services.create_purchase_order(actor, payload, idempotency_key="numbered-create")
    assert first.pk == replay.pk
    assert first.number.endswith("-0001")
    assert DocumentNumberCounter.objects.get(kind="purchase_order").value == 1


def test_internal_shipment_service_allocates_when_trusted_number_is_absent(world):
    actor = internal_user(world)
    order = confirmed_order(world, actor)
    config(world, actor, kind="supplier_shipment", prefix="SH", country_prefixes={"CA": "CAN"})
    payload = shipment_payload(world, order, "auto-shipment")
    payload.pop("number")
    shipment = services.create_supplier_shipment(actor, payload, idempotency_key="auto-shipment")
    assert shipment.number.startswith("US-SH-")
    assert SupplierShipment.objects.filter(tenant=world["tenant"], number=shipment.number).count() == 1


def test_collision_skip_and_period_keys(world):
    actor = internal_user(world)
    today = business_date()
    collision = f"US-PO-{today:%Y%m%d}-0001"
    services.create_purchase_order(actor, po_payload(world, number=collision), idempotency_key="legacy-collision")
    config(world, actor)
    with transaction.atomic(), domain_write():
        allocated = number_for(actor, "purchase_order", "legacy", "US")
    assert allocated.endswith("-0002")
    assert period_key("day", date(2026, 10, 15)) == "day:20261015"
    assert period_key("month", date(2026, 10, 15)) == "month:202610"
    assert period_key("year", date(2026, 10, 15)) == "year:2026"
    assert period_key("never", date(2026, 10, 15)) == "never"


def test_overflow_stops_and_resets_use_business_day(world, monkeypatch):
    actor = internal_user(world)
    config(world, actor, include_country=False, sequence_width=3)
    with domain_write():
        DocumentNumberCounter.objects.create(tenant=world["tenant"], created_by=actor, kind="purchase_order",
            country_code="", period_key=period_key("day", date(2026, 10, 15)), value=999)
    import apps.supply_chain.numbering as numbering
    monkeypatch.setattr(numbering, "business_date", lambda: date(2026, 10, 15))
    with pytest.raises(DjangoValidationError, match="位数已用尽"):
        with transaction.atomic(), domain_write():
            number_for(actor, "purchase_order", "legacy")
    # A fresh business day starts a new day-scoped counter even if the document date differs.
    monkeypatch.setattr(numbering, "business_date", lambda: date(2026, 10, 16))
    with transaction.atomic(), domain_write():
        next_day = number_for(actor, "purchase_order", "legacy")
    assert next_day.endswith("20261016-001")


def test_rule_api_preview_save_version_audit_and_scope(world):
    manager = internal_user(world, "number-manager")
    api = client(manager)
    path = BASE + "settings/number-rules/"
    listed = api.get(path)
    assert listed.status_code == 200, listed.data
    assert listed.data["data"]["can_manage"] is True
    kinds = {row["kind"] for row in listed.data["data"]["rules"]}
    assert len(kinds) == 7
    assert {"corporate_contract", "personal_contract"} <= kinds
    values = {"enabled": True, "include_country": True, "country_prefixes": {"CA": "CAN"},
        "prefix": "OPS", "date_format": "YYYYMMDD", "separator": "-",
        "sequence_width": 4, "reset_period": "day"}
    preview_response = api.post(path + "purchase_order/preview/", {**values, "country_code": "CA"}, format="json")
    assert preview_response.status_code == 200, preview_response.data
    assert preview_response.data["data"]["example"].startswith("CAN-OPS-")
    assert not DocumentNumberRule.objects.exists() and not DocumentNumberCounter.objects.exists()
    saved = api.patch(path + "purchase_order/", {**values, "expected_version": 0, "reason": "初始规则"}, format="json", HTTP_IDEMPOTENCY_KEY="save-1")
    assert saved.status_code == 200, saved.data
    assert saved.data["data"]["version"] == 1 and saved.data["data"]["history"][0]["reason"] == "初始规则"
    replay = api.patch(path + "purchase_order/", {**values, "expected_version": 0, "reason": "初始规则"}, format="json", HTTP_IDEMPOTENCY_KEY="save-1")
    assert replay.status_code == 200 and replay.data["data"]["version"] == 1
    stale = api.patch(path + "purchase_order/", {**values, "expected_version": 0, "reason": "过期更新"}, format="json", HTTP_IDEMPOTENCY_KEY="save-2")
    assert stale.status_code == 400
    assert DocumentNumberCounter.objects.count() == 0
    own = internal_user(world, "number-own", scope=DataScope.ScopeType.OWN)
    denied = client(own).patch(path + "purchase_order/", {**values, "expected_version": 1, "reason": "无权更新"}, format="json", HTTP_IDEMPOTENCY_KEY="own")
    assert denied.status_code == 403
    view_only = internal_user(world, "number-view", codes=("supply.v2.view",))
    assert client(view_only).get(path).data["data"]["can_manage"] is False
    denied = client(view_only).patch(path + "purchase_order/", {**values, "expected_version": 1, "reason": "只读"}, format="json", HTTP_IDEMPOTENCY_KEY="view")
    assert denied.status_code == 403


def test_configured_numbers_flow_through_all_five_real_creation_paths(world, monkeypatch):
    actor = internal_user(world, "all-number-flows", codes=("supply.v2.view", "supply.v2.manage", operating.VIEW, operating.MANAGE))
    import apps.supply_chain.numbering as numbering
    monkeypatch.setattr(numbering, "business_date", lambda: date(2026, 10, 15))
    for kind, prefix in (("operating_order", "OP"), ("purchase_order", "PO"),
                         ("supplier_shipment", "SH"), ("dispatch_batch", "DB"), ("inbound_order", "IN")):
        config(world, actor, kind=kind, prefix=prefix, separator="none")

    demand_payload = {"country_id": world["country"].pk, "source_kind": "new_goods", "order_date": date(2026, 10, 15),
        "notes": "", "lines": [{"sku_id": world["sku"].pk, "quantity": 3}]}
    demand = operating.save_order(actor, demand_payload, "demand-key")
    assert demand.number.startswith("USOP20261015") and "-" not in demand.number
    assert operating.save_order(actor, demand_payload, "demand-key").number == demand.number
    demand = operating.action(actor, demand.pk, {"expected_version": demand.version}, "submit-demand", "submitted")

    op_line = OperatingOrderLine.objects.get(order=demand)
    _, purchase = operating.split(actor, demand.pk, {"expected_version": demand.version,
        "supplier_id": world["supplier"].pk, "reference_number": "", "notes": "",
        "lines": [{"operating_line_id": op_line.pk, "quantity": 3, "unit_price": "1.00"}]}, "split-demand")
    assert purchase.number.startswith("USPO20261015") and "-" not in purchase.number
    purchase = services.confirm_purchase_order(actor, purchase.pk, expected_version=purchase.version, idempotency_key="confirm-numbered-po")

    shipment_payload_auto = shipment_payload(world, purchase, "shipment-key")
    shipment_payload_auto.pop("number")
    shipment = shipments.create_draft(actor, shipment_payload_auto, "shipment-key")
    assert shipment.number.startswith("USSH20261015") and "-" not in shipment.number
    assert shipments.create_draft(actor, shipment_payload_auto, "shipment-key").number == shipment.number
    shipments.upload_box(actor, shipment.pk, SimpleUploadedFile("boxes.csv", b"box_no,sku,quantity\n1,SC2-SKU,3\n"), shipment.version, "box-upload")
    shipment.refresh_from_db()
    shipment = shipments.action(actor, shipment.pk, {"expected_version": shipment.version}, "shipment-submit", "submitted")

    carrier = freight(world)
    batch = services.create_dispatch_batch(actor, {"shipment_ids": [shipment.pk], "freight_company_id": carrier.pk,
        "freight_number": "F-1", "notes": ""}, idempotency_key="dispatch-create")
    assert batch.number.startswith("USDB20261015") and "-" not in batch.number
    for index, stage in enumerate(("departed", "arrived_port", "arrived_warehouse"), 1):
        batch = services.mark_logistics_stage(actor, batch.pk, stage=stage,
            occurred_at=datetime(2026, 10, 15, index, tzinfo=timezone.utc), expected_version=batch.version,
            idempotency_key=f"stage-{stage}")
    warehouse = WarehouseMaster.objects.create(tenant=world["tenant"], code="numbered-warehouse", name="WH", country_code="US")
    inbound_expected_version = batch.version
    inbound = services.generate_inbound_draft(actor, batch.pk, warehouse_id=warehouse.pk,
        expected_version=inbound_expected_version, idempotency_key="inbound-generate")
    assert inbound.number.startswith("USIN20261015") and "-" not in inbound.number
    assert services.generate_inbound_draft(actor, batch.pk, warehouse_id=warehouse.pk,
        expected_version=inbound_expected_version, idempotency_key="inbound-generate").pk == inbound.pk


def test_external_settings_denied_cross_tenant_and_rule_edits_keep_counter(world):
    actor = internal_user(world, "tenant-number-owner")
    rule = config(world, actor, include_country=False, country_prefixes={})
    with transaction.atomic(), domain_write():
        first = number_for(actor, "purchase_order", "legacy")
    rule.prefix = "NEW"
    rule.sequence_width = 5
    rule.version += 1
    with domain_write():
        rule.save()
    with transaction.atomic(), domain_write():
        second = number_for(actor, "purchase_order", "legacy")
    assert first.endswith("-0001") and second.startswith("NEW-") and second.endswith("-00002")

    from apps.tenants.models import Tenant
    from apps.masterdata.models import CountrySiteMaster
    other_tenant = Tenant.objects.create(name="Number isolation", code="number-isolation")
    CountrySiteMaster.objects.create(tenant=other_tenant, code="us", name="USA", country_code="US")
    other_world = {**world, "tenant": other_tenant}
    other_actor = internal_user(other_world, "other-number-owner")
    config(other_world, other_actor, include_country=False)
    with transaction.atomic(), domain_write():
        other_number = number_for(other_actor, "purchase_order", "legacy")
    assert first.endswith("-0001") and other_number.endswith("-0001")
    assert DocumentNumberCounter.objects.filter(tenant=world["tenant"], kind="purchase_order").get().value == 2
    assert DocumentNumberCounter.objects.filter(tenant=other_tenant, kind="purchase_order").get().value == 1

    external = supplier_user(world, world["supplier"], "external-number-settings")
    api = client(external)
    path = BASE + "settings/number-rules/"
    assert api.get(path).status_code == 403
    denied = api.patch(path + "purchase_order/", {"expected_version": 0}, format="json", HTTP_IDEMPOTENCY_KEY="external")
    assert denied.status_code == 403
