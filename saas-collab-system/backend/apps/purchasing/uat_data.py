"""SC-SUPPLY-FLOW-UAT-1 local synthetic data tooling.

The UAT fixture is deliberately kept outside the business models.  It creates
only clearly labelled records, uses the existing domain services for every
controlled state transition, and has a fail-closed database/environment gate.
The module is imported by the ``seed_supply_flow_uat`` management command and
is also small enough for local gate tests to exercise directly.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.accounts.models import CustomUser, ExternalUserProfile, MiniAppIdentity
from apps.consolidation.models import (
    ConsolidationBoxAllocation,
    ConsolidationEvent,
    ConsolidationSite,
    LooseCargoConsolidation,
)
from apps.consolidation.services import (
    allocate_consolidation_boxes,
    controlled_release_consolidation_box,
    create_consolidation_site,
    create_loose_cargo_consolidation,
    mark_consolidation_exception,
    ready_consolidation,
    receive_consolidation_box,
    release_consolidation,
    set_consolidation_supplier_capability,
    submit_consolidation_handover,
)
from apps.files.models import (
    AttachmentUploadSession,
    ControlledAttachment,
    ControlledAttachmentEvent,
)
from apps.files.services import (
    AttachmentScanResult,
    FakeAttachmentScanner,
    FakeAttachmentStorage,
    finalize_attachment,
    create_attachment_upload_session,
    record_attachment_scan_result,
    start_attachment_scan,
)
from apps.masterdata.models import SupplierMaster
from apps.packing.models import (
    PackingBatch,
    PackingBatchLineAllocation,
    PackingBatchOrder,
    PackingBox,
    PackingBoxConsumption,
)
from apps.packing.services import (
    add_packing_box,
    cancel_packing_batch,
    complete_packing_batch,
    create_packing_batch,
    set_supplier_packing_capability,
)
from apps.permissions.models import DataScope, Permission, Role, UserRole
from apps.products.models import ProductSKU, ProductSPU
from apps.purchasing.models import (
    SupplyPurchaseOrder,
    SupplyPurchaseOrderEvent,
    SupplyPurchaseOrderLine,
)
from apps.purchasing.supply_serializers import SupplyPurchaseOrderCreateSerializer
from apps.purchasing.supply_services import (
    perform_shipping_route_action,
    perform_supply_order_action,
)
from apps.shipping.models import LooseCargoShipment, ShipmentBoxAllocation
from apps.shipping.services import (
    allocate_shipment_boxes,
    clear_shipment,
    create_shipment,
    customs_declare_shipment,
    dispatch_shipment,
    port_arrival_shipment,
    warehouse_arrival_shipment,
)
from apps.tenants.models import Tenant


DATA_VERSION = "SC-UAT-DATA-V1"
TENANT_CODES = ("SC-UAT-A", "SC-UAT-B")
LOCAL_ENVIRONMENT = "local"
LOCAL_DATABASE_MARKERS = ("uat", "test", "local", "dev")
LOCAL_SETTINGS_MODULES = {
    "config.settings.dev",
    "config.settings.development",
    "config.settings.local",
    "config.settings.test",
    "config.settings.testing",
}
BLOCKED_SETTINGS_MARKERS = ("prod", "production", "pilot", "sandbox")
PNG_1X1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)

ALL_PURCHASE_PERMISSIONS = (
    "supply.purchase_order.view",
    "supply.purchase_order.create",
    "supply.purchase_order.accept",
    "supply.purchase_order.assign_shipping_route",
    "supply.production.start",
    "supply.production.update",
    "supply.production.complete",
)
ALL_PACKING_PERMISSIONS = (
    "supply.packing.view",
    "supply.packing.create",
    "supply.packing.manage",
    "supply.packing.complete",
    "supply.packing.change.review",
)
ALL_CONSOLIDATION_PERMISSIONS = (
    "supply.consolidation_site.view",
    "supply.consolidation_site.manage",
    "supply.consolidation.view",
    "supply.consolidation.create",
    "supply.consolidation.manage",
    "supply.consolidation.allocate",
    "supply.consolidation.release",
    "supply.consolidation.receive",
    "supply.consolidation.exception.manage",
    "supply.consolidation.transfer",
    "supply.consolidation.cancel",
)
ALL_SHIPMENT_PERMISSIONS = (
    "supply.shipment.view",
    "supply.shipment.create",
    "supply.shipment.update",
    "supply.shipment.allocate",
    "supply.shipment.customs.confirm",
    "supply.shipment.dispatch",
    "supply.shipment.port_arrival.confirm",
    "supply.shipment.warehouse_arrival.confirm",
    "supply.shipment.clearance.complete",
    "supply.shipment.exception.manage",
    "supply.shipment.cancel",
)


class UATDataError(RuntimeError):
    """A deterministic, user-facing UAT tooling failure."""


@dataclass(frozen=True)
class UATContext:
    data_version: str
    payload_hash: str
    tenant_codes: tuple[str, ...] = TENANT_CODES


class _LocalRequest:
    """Minimal request metadata consumed by the order domain service."""

    META = {"REMOTE_ADDR": "127.0.0.1", "HTTP_USER_AGENT": "SC-UAT-DATA-V1"}


def _request() -> _LocalRequest:
    return _LocalRequest()


def _hash_payload(value: str) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def make_context(data_version: str = DATA_VERSION, payload: str = "fixture-v1") -> UATContext:
    data_version = str(data_version or "").strip()
    if data_version != DATA_VERSION:
        raise UATDataError(f"Only the frozen UAT data version {DATA_VERSION} is supported.")
    return UATContext(data_version=data_version, payload_hash=_hash_payload(f"{data_version}:{payload}"))


def _database_name() -> str:
    return str(connection.settings_dict.get("NAME") or "").strip()


def validate_local_database(
    *,
    environment: str,
    database_name: str,
    confirm_local: bool,
    allow_inmemory_test: bool = False,
) -> dict[str, Any]:
    """Fail closed unless the caller names this exact local database.

    No settings file is read here.  The already loaded Django connection is
    inspected, and MySQL is accepted only on loopback.  In-memory SQLite is
    accepted only when a test explicitly opts in, never by default.
    """

    if str(environment or "").strip().lower() != LOCAL_ENVIRONMENT:
        raise UATDataError("UAT data tooling requires --environment local.")
    if not confirm_local:
        raise UATDataError("Explicit --confirm-local is required; no data was changed.")
    loaded_settings_module = str(getattr(settings, "SETTINGS_MODULE", "") or "").strip().lower()
    environment_settings_module = str(os.environ.get("DJANGO_SETTINGS_MODULE", "") or "").strip().lower()
    settings_module = loaded_settings_module or environment_settings_module
    if not settings_module:
        raise UATDataError("UAT data tooling requires an explicit DJANGO_SETTINGS_MODULE.")
    if environment_settings_module and loaded_settings_module and environment_settings_module != loaded_settings_module:
        raise UATDataError("Loaded DJANGO_SETTINGS_MODULE does not match the active settings module.")
    for candidate in {settings_module, environment_settings_module} - {""}:
        if any(marker in candidate.split(".") for marker in BLOCKED_SETTINGS_MARKERS):
            raise UATDataError(f"UAT data tooling refuses non-local settings module {candidate!r}.")
        if candidate not in LOCAL_SETTINGS_MODULES:
            raise UATDataError(
                "UAT data tooling requires an explicit local/development/test settings module."
            )
    configured_name = _database_name()
    requested_name = str(database_name or "").strip()
    if not requested_name or requested_name != configured_name:
        raise UATDataError("--database-name must exactly match the loaded local database name.")
    memory_sqlite = configured_name.lower() in {":memory:", "file:memorydb_default?mode=memory&cache=shared"} or configured_name.lower().startswith("file:memory")
    if memory_sqlite:
        if not allow_inmemory_test:
            raise UATDataError("In-memory SQLite is refused unless --allow-inmemory-test is explicit.")
    vendor = connection.vendor
    if vendor not in {"sqlite", "mysql"}:
        raise UATDataError(f"Database vendor {vendor!r} is not permitted for local UAT data.")
    lowered = configured_name.lower()
    if vendor == "sqlite" and not memory_sqlite and (
        lowered.startswith(("file:", "sqlite://"))
        or configured_name.startswith(("\\\\", "//"))
    ):
        raise UATDataError("SQLite database path must be local; UNC/network URI paths are refused.")
    if not settings.DEBUG and not (allow_inmemory_test and vendor == "sqlite" and memory_sqlite):
        raise UATDataError("UAT data tooling is disabled when DEBUG is false.")
    if vendor == "mysql":
        host = str(connection.settings_dict.get("HOST") or "").strip().lower()
        if host not in {"127.0.0.1", "localhost", "::1"}:
            raise UATDataError("UAT MySQL must use a loopback host.")
    if vendor == "sqlite" and not allow_inmemory_test and not any(marker in lowered for marker in LOCAL_DATABASE_MARKERS):
        raise UATDataError("SQLite database name must visibly identify a local/test/UAT database.")
    if vendor == "mysql" and not any(marker in lowered for marker in LOCAL_DATABASE_MARKERS):
        raise UATDataError("MySQL database name must visibly identify a local/test/UAT database.")
    return {"vendor": vendor, "database_name": configured_name, "host": connection.settings_dict.get("HOST") or ""}


def _marker(code: str, context: UATContext) -> str:
    return f"{code} | {context.data_version} | {context.payload_hash}"


def _tenant_label(code: str) -> str:
    return code.rsplit("-", 1)[-1]


def _ensure_tenant(code: str, context: UATContext) -> tuple[Tenant, bool]:
    expected = _marker(code, context)
    tenant = Tenant.objects.filter(code=code).first()
    if tenant is None:
        return Tenant.objects.create(code=code, name=expected), True
    if tenant.name != expected:
        raise UATDataError(f"Tenant {code} exists with a different data version/payload marker.")
    if tenant.status != Tenant.Status.ACTIVE:
        raise UATDataError(f"Tenant {code} is inactive; cleanup has already been applied.")
    return tenant, False


def _ensure_supplier(tenant: Tenant, code: str) -> SupplierMaster:
    supplier = SupplierMaster.objects.filter(tenant=tenant, code=code).first()
    expected_name = f"SC-UAT synthetic supplier {code}"
    if supplier is None:
        return SupplierMaster.objects.create(
            tenant=tenant,
            code=code,
            name=expected_name,
            contact_alias="UAT-only",
            contact_email="",
            contact_phone="",
        )
    if supplier.name != expected_name or supplier.contact_phone or supplier.contact_email:
        raise UATDataError(f"Supplier {code} is not the expected synthetic record.")
    if supplier.tenant_id != tenant.id:
        raise UATDataError(f"Supplier {code} is bound to another tenant.")
    return supplier


def _ensure_user(tenant: Tenant, username: str, user_type: str) -> CustomUser:
    user = CustomUser.objects.filter(username=username).first()
    if user is None:
        user = CustomUser.objects.create(
            username=username,
            email="",
            full_name=f"{username} (UAT)",
            user_type=user_type,
            tenant=tenant,
            is_active=True,
        )
    elif user.tenant_id != tenant.id or user.user_type != user_type:
        raise UATDataError(f"Reserved UAT identity {username} is already bound differently.")
    # UAT tooling never creates a reusable credential or writes one to output.
    user.set_unusable_password()
    if not user.is_active:
        raise UATDataError(f"Reserved UAT identity {username} is disabled; cleanup has already run.")
    user.save(update_fields=["password", "updated_at"])
    return user


def _ensure_external_profile(user: CustomUser, supplier: SupplierMaster) -> None:
    profile, _ = ExternalUserProfile.objects.get_or_create(
        user=user,
        defaults={"tenant": supplier.tenant, "supplier_id": supplier.id, "company_name": supplier.name, "contact_name": "UAT-only"},
    )
    if profile.tenant_id != supplier.tenant_id or profile.supplier_id != supplier.id:
        raise UATDataError(f"Supplier identity {user.username} is bound to the wrong supplier.")
    profile.company_name = supplier.name
    profile.contact_name = "UAT-only"
    profile.save(update_fields=["tenant", "supplier_id", "company_name", "contact_name", "updated_at"])


def _ensure_product(tenant: Tenant) -> ProductSKU:
    spu_code = f"SC-UAT-SPU-{_tenant_label(tenant.code)}"
    sku_code = f"SC-UAT-SKU-{_tenant_label(tenant.code)}"
    spu, _ = ProductSPU.objects.get_or_create(
        tenant=tenant,
        spu_code=spu_code,
        defaults={"product_name": f"SC-UAT synthetic product {tenant.code}"},
    )
    if not spu.product_name.startswith("SC-UAT synthetic product"):
        raise UATDataError(f"Product SPU {spu_code} is not synthetic UAT data.")
    sku, _ = ProductSKU.objects.get_or_create(
        tenant=tenant,
        sku_code=sku_code,
        defaults={"spu": spu, "product_name": spu.product_name},
    )
    if sku.spu_id != spu.id or sku.tenant_id != tenant.id:
        raise UATDataError(f"Product SKU {sku_code} is bound to another SPU/tenant.")
    return sku


def _ensure_order(tenant: Tenant, actor: CustomUser, supplier: SupplierMaster, sku: ProductSKU, order_code: str, route: str, context: UATContext) -> SupplyPurchaseOrder:
    existing = SupplyPurchaseOrder.objects.filter(tenant=tenant, order_no=order_code).first()
    if existing is not None:
        if existing.supplier_id != supplier.id or existing.source_system != context.data_version:
            raise UATDataError(f"Order {order_code} is not the expected version/supplier.")
        lines = list(existing.lines.order_by("line_no"))
        if len(lines) != 2 or any(line.quantity != 10 for line in lines):
            raise UATDataError(f"Order {order_code} was tampered with; expected two quantity-10 lines.")
        return existing
    source_payload = _hash_payload(f"{context.data_version}:{order_code}:{supplier.code}:2x10")
    payload = {
        "order_no": order_code,
        "supplier_id": supplier.id,
        "order_date": date(2026, 1, 15).isoformat(),
        "expected_delivery_date": date(2026, 2, 15).isoformat(),
        "currency": "CNY",
        "notes": f"{context.data_version}; synthetic local UAT only",
        "source_system": context.data_version,
        "source_table": "sc_uat_purchase_orders",
        "source_record_id": order_code,
        "source_payload_hash": source_payload,
        "lines": [
            {"line_no": 1, "sku_id": sku.id, "quantity": 10, "unit_price": "12.5000", "expected_delivery_date": date(2026, 2, 15).isoformat(), "source_record_id": f"{order_code}-L1"},
            {"line_no": 2, "sku_id": sku.id, "quantity": 10, "unit_price": "13.5000", "expected_delivery_date": date(2026, 2, 15).isoformat(), "source_record_id": f"{order_code}-L2"},
        ],
    }
    serializer = SupplyPurchaseOrderCreateSerializer(data=payload, context={"request": SimpleNamespace(user=actor)})
    serializer.is_valid(raise_exception=True)
    with transaction.atomic():
        order = serializer.save(
            creation_idempotency_key=f"{context.data_version}:purchase:create:{order_code}",
            creation_request_hash=_hash_payload(json.dumps(payload, sort_keys=True, default=str)),
        )
    return order


def _order_action(order: SupplyPurchaseOrder, actor: CustomUser, action: str, key: str, context: UATContext, *, completed_quantity=None, note="") -> SupplyPurchaseOrder:
    result, _event, _replayed = perform_supply_order_action(
        order_id=order.id,
        actor=actor,
        action=action,
        idempotency_key=key,
        request=_request(),
        completed_quantity=completed_quantity,
        note=note,
    )
    return result


def _route_action(order: SupplyPurchaseOrder, actor: CustomUser, route: str, key: str) -> SupplyPurchaseOrder:
    event = SupplyPurchaseOrderEvent.objects.filter(order=order, idempotency_key=key).first()
    expected = int((event.payload or {}).get("expected_version", order.version)) if event else int(order.version)
    result, _event, _replayed = perform_shipping_route_action(
        order_id=order.id,
        actor=actor,
        action=SupplyPurchaseOrderEvent.Action.ASSIGN_SHIPPING_ROUTE,
        idempotency_key=key,
        expected_version=expected,
        shipping_route=route,
        reason="SC-UAT initial route decision",
        request=_request(),
    )
    return result


def _ensure_order_lifecycle(order: SupplyPurchaseOrder, actor: CustomUser, route: str, context: UATContext) -> SupplyPurchaseOrder:
    prefix = f"{context.data_version}:purchase:{order.order_no}"
    order = _order_action(order, actor, SupplyPurchaseOrderEvent.Action.ACCEPT, f"{prefix}:accept", context)
    order = _order_action(order, actor, SupplyPurchaseOrderEvent.Action.START_PRODUCTION, f"{prefix}:start", context)
    order = _order_action(order, actor, SupplyPurchaseOrderEvent.Action.UPDATE_PROGRESS, f"{prefix}:progress", context, completed_quantity=20, note=context.data_version)
    order = _order_action(order, actor, SupplyPurchaseOrderEvent.Action.COMPLETE_PRODUCTION, f"{prefix}:complete", context)
    return _route_action(order, actor, route, f"{prefix}:route")


def _ensure_packing(order: SupplyPurchaseOrder, actor: CustomUser, context: UATContext) -> list[PackingBox]:
    boxes: list[PackingBox] = []
    lines = list(order.lines.order_by("line_no"))
    for batch_no in (1, 2):
        prefix = f"{context.data_version}:packing:{order.order_no}:batch:{batch_no}"
        source = {
            "source_system": context.data_version,
            "source_table": "sc_uat_packing_batches",
            "source_record_id": f"{order.order_no}-B{batch_no}",
            "source_payload_hash": _hash_payload(f"{order.order_no}:batch:{batch_no}"),
        }
        batch_ref, _ = create_packing_batch(order_ids=[order.id], actor=actor, idempotency_key=f"{prefix}:create", note=context.data_version, source=source)
        batch = PackingBatch.objects.get(pk=int(batch_ref.id))
        qty = 6 if batch_no == 1 else 4
        box_ref, _event, _replayed = add_packing_box(
            batch_id=batch.id,
            actor=actor,
            idempotency_key=f"{prefix}:box",
            expected_version=1,
            items=[{"order_line_id": line.id, "quantity": qty} for line in lines],
            weight="2.500",
            volume="0.125000",
            note=context.data_version,
        )
        box = PackingBox.objects.get(pk=int(box_ref.id))
        complete_packing_batch(batch_id=batch.id, actor=actor, idempotency_key=f"{prefix}:complete", expected_version=2)
        boxes.append(box)
    return boxes


def _ensure_site(tenant_actor: CustomUser, code: str, region: str, context: UATContext, *, inactive=False) -> ConsolidationSite:
    existing = ConsolidationSite.objects.filter(tenant=tenant_actor.tenant, site_code=code).first()
    if existing is not None:
        if existing.region_code != region:
            raise UATDataError(f"Site {code} has an unexpected region.")
        return existing
    now = timezone.now()
    return create_consolidation_site(
        actor=tenant_actor,
        site_code=code,
        name=f"SC-UAT synthetic site {code}",
        region_code=region,
        country_code="CN",
        province_state="UAT",
        city="Synthetic",
        address_line="SC-UAT local-only address",
        contact_name="UAT-only",
        contact_phone="",
        effective_from=now - timedelta(days=1),
        effective_to=(now - timedelta(hours=1) if inactive else None),
        idempotency_key=f"{context.data_version}:site:{code}:create",
    )[0]


def _ensure_consolidation(actor: CustomUser, site: ConsolidationSite, number: str, context: UATContext) -> LooseCargoConsolidation:
    existing = LooseCargoConsolidation.objects.filter(tenant=actor.tenant, consolidation_no=number).first()
    if existing is not None:
        if existing.site_id != site.id or existing.region_code != site.region_code:
            raise UATDataError(f"Consolidation {number} has an unexpected site/region.")
        return existing
    return create_loose_cargo_consolidation(
        site_id=site.id,
        actor=actor,
        region_code=site.region_code,
        consolidation_no=number,
        collection_cutoff_at=timezone.now() + timedelta(hours=1),
        expected_dispatch_at=timezone.now() + timedelta(hours=8),
        note=f"{context.data_version}; synthetic local UAT only",
        idempotency_key=f"{context.data_version}:consolidation:{number}:create",
    )[0]


def _ensure_consolidation_allocation(actor: CustomUser, consolidation: LooseCargoConsolidation, boxes: list[PackingBox], context: UATContext) -> LooseCargoConsolidation:
    key = f"{context.data_version}:consolidation:{consolidation.consolidation_no}:allocate"
    # Calling the service with the original key intentionally exercises its
    # append-only replay path on subsequent generator runs.
    return allocate_consolidation_boxes(
        consolidation_id=consolidation.id,
        box_ids=[box.id for box in boxes],
        actor=actor,
        expected_version=1,
        idempotency_key=key,
        reason=context.data_version,
    )[0]


def _ensure_consolidation_release(actor: CustomUser, consolidation: LooseCargoConsolidation, context: UATContext) -> LooseCargoConsolidation:
    return release_consolidation(
        consolidation_id=consolidation.id,
        actor=actor,
        expected_version=2,
        idempotency_key=f"{context.data_version}:consolidation:{consolidation.consolidation_no}:release",
        reason=context.data_version,
    )[0]


def _ensure_attachment(actor: CustomUser, allocation: ConsolidationBoxAllocation, context: UATContext, *, state: str) -> ControlledAttachment:
    key_prefix = f"{context.data_version}:attachment:{allocation.id}:{state}"
    # A replay may happen after the allocation has progressed to RECEIVED.
    # Resolve the append-only upload event first so an idempotent generation
    # never attempts a new upload against a closed allocation.
    existing = ControlledAttachment.objects.filter(
        tenant=actor.tenant,
        upload_idempotency_key=f"{key_prefix}:session",
    ).first()
    if existing is not None:
        return existing
    storage = FakeAttachmentStorage()
    scanner = FakeAttachmentScanner(result=AttachmentScanResult(
        passed=state == "accepted",
        quarantined=state == "quarantined",
        engine="uat-fake-scanner",
        version="SC-UAT-1",
        rejection_code="uat_rejected" if state == "rejected" else "uat_quarantine" if state == "quarantined" else "",
    ))
    attachment, _event, _replayed = create_attachment_upload_session(
        actor=actor,
        allocation_id=allocation.id,
        idempotency_key=f"{key_prefix}:session",
        channel="supplier_web" if actor.user_type == CustomUser.UserType.EXTERNAL else "internal",
        storage=storage,
    )
    session = getattr(attachment, "upload_session", None) or AttachmentUploadSession.objects.get(attachment=attachment)
    content = PNG_1X1 if state != "rejected" else b"not-an-image"
    storage.put(attachment.storage_key, content)
    attachment, _event, _replayed = finalize_attachment(
        actor=actor,
        attachment_id=attachment.id,
        idempotency_key=f"{key_prefix}:finish",
        file_name=f"SC-UAT-{state}-{allocation.id}.png",
        claimed_media_type="image/png",
        upload_token=getattr(session, "upload_token", None),
        storage=storage,
    )
    if state == "rejected":
        return attachment
    attachment, _event, _replayed = start_attachment_scan(
        actor=actor,
        attachment_id=attachment.id,
        idempotency_key=f"{key_prefix}:scan-start",
        channel="supplier_web" if actor.user_type == CustomUser.UserType.EXTERNAL else "internal",
    )
    return record_attachment_scan_result(
        actor=actor,
        attachment_id=attachment.id,
        idempotency_key=f"{key_prefix}:scan-result",
        scanner=scanner,
        storage=storage,
        channel="supplier_web" if actor.user_type == CustomUser.UserType.EXTERNAL else "internal",
    )[0]


def _ensure_receive_ready(actor: CustomUser, consolidation: LooseCargoConsolidation, context: UATContext) -> LooseCargoConsolidation:
    allocations = list(consolidation.allocations.order_by("box_id", "id"))
    for allocation in allocations:
        if allocation.state in {
            ConsolidationBoxAllocation.State.RELEASED,
            ConsolidationBoxAllocation.State.RECEIVED,
            ConsolidationBoxAllocation.State.TRANSFERRED,
        }:
            continue
        current = LooseCargoConsolidation.objects.get(pk=consolidation.id)
        receive_consolidation_box(
            consolidation_id=consolidation.id,
            allocation_id=allocation.id,
            actor=actor,
            expected_version=current.version,
            idempotency_key=f"{context.data_version}:consolidation:{consolidation.consolidation_no}:receive:{allocation.id}",
            reason=context.data_version,
        )
    current = LooseCargoConsolidation.objects.get(pk=consolidation.id)
    if current.status in {
        LooseCargoConsolidation.Status.RELEASED,
        LooseCargoConsolidation.Status.RECEIVING,
    }:
        ready_consolidation(
            consolidation_id=current.id,
            actor=actor,
            expected_version=current.version,
            idempotency_key=f"{context.data_version}:consolidation:{consolidation.consolidation_no}:ready",
            reason=context.data_version,
        )
    return LooseCargoConsolidation.objects.get(pk=consolidation.id)


def _ensure_shipment_flow(actor: CustomUser, consolidation: LooseCargoConsolidation, allocations: list[ConsolidationBoxAllocation], site: ConsolidationSite, context: UATContext) -> list[LooseCargoShipment]:
    shipments: list[LooseCargoShipment] = []
    for index, source_allocations in enumerate((allocations[:2], allocations[2:]), start=1):
        number = f"SC-UAT-SHIP-SOUTH-0{index}"
        shipment_ref = create_shipment(
            actor=actor,
            shipment_no=number,
            region_code=consolidation.region_code,
            origin_site_id=site.id,
            origin_site_snapshot={"site_code": site.site_code, "region_code": site.region_code},
            destination_country_code="CN",
            destination_port_code="UAT-PORT",
            destination_warehouse_code="UAT-WH",
            note=f"{context.data_version}; synthetic local UAT only",
            idempotency_key=f"{context.data_version}:shipment:{number}:create",
        )[0]
        shipment = LooseCargoShipment.objects.get(pk=shipment_ref.id)
        allocate_shipment_boxes(
            shipment_id=shipment.id,
            consolidation_id=consolidation.id,
            allocation_ids=[item.id for item in source_allocations],
            actor=actor,
            expected_version=1,
            idempotency_key=f"{context.data_version}:shipment:{number}:allocate",
            reason=context.data_version,
        )
        shipment = LooseCargoShipment.objects.get(pk=shipment.id)
        customs_declare_shipment(
            shipment_id=shipment.id,
            actor=actor,
            expected_version=2,
            idempotency_key=f"{context.data_version}:shipment:{number}:customs",
            customs_reference=f"SC-UAT-CUSTOMS-{index}",
        )
        shipment = LooseCargoShipment.objects.get(pk=shipment.id)
        for dispatch_index, allocation in enumerate(source_allocations, start=1):
            expected = 3 if dispatch_index == 1 else 4
            dispatch_shipment(
                shipment_id=shipment.id,
                actor=actor,
                expected_version=expected,
                allocation_ids=[ShipmentBoxAllocation.objects.get(shipment=shipment, box_id=allocation.box_id).id],
                idempotency_key=f"{context.data_version}:shipment:{number}:dispatch:{dispatch_index}",
                reason=context.data_version,
            )
            shipment = LooseCargoShipment.objects.get(pk=shipment.id)
        port_arrival_shipment(
            shipment_id=shipment.id,
            actor=actor,
            expected_version=5,
            idempotency_key=f"{context.data_version}:shipment:{number}:port",
        )
        warehouse_arrival_shipment(
            shipment_id=shipment.id,
            actor=actor,
            expected_version=6,
            idempotency_key=f"{context.data_version}:shipment:{number}:warehouse",
        )
        clear_shipment(
            shipment_id=shipment.id,
            actor=actor,
            expected_version=7,
            idempotency_key=f"{context.data_version}:shipment:{number}:clear",
        )
        shipments.append(LooseCargoShipment.objects.get(pk=shipment.id))
    return shipments


def _ensure_roles(tenant: Tenant, users: dict[str, CustomUser], *, custom_config: dict[str, list[int]] | None = None, shipment_config: dict[str, list[int]] | None = None) -> None:
    permissions = {item.code: item for item in Permission.objects.filter(code__in=set(ALL_PURCHASE_PERMISSIONS + ALL_PACKING_PERMISSIONS + ALL_CONSOLIDATION_PERMISSIONS + ALL_SHIPMENT_PERMISSIONS))}
    missing = set(ALL_PURCHASE_PERMISSIONS + ALL_PACKING_PERMISSIONS + ALL_CONSOLIDATION_PERMISSIONS + ALL_SHIPMENT_PERMISSIONS) - set(permissions)
    if missing:
        raise UATDataError(f"Required permission migrations are missing: {sorted(missing)}")

    def role_for(slug: str, display: str, codes: tuple[str, ...], scope_type: str, config: dict[str, Any]) -> Role:
        role, _ = Role.objects.get_or_create(tenant=tenant, code=f"sc-uat-{_tenant_label(tenant.code).lower()}-{slug}", defaults={"name": display})
        role.name = display
        role.status = Role.Status.ACTIVE
        role.save(update_fields=["name", "status", "updated_at"])
        role.permissions.set([permissions[code] for code in codes])
        scope, _ = DataScope.objects.get_or_create(tenant=tenant, role=role, scope_type=scope_type, defaults={"config": config})
        if scope.config != config:
            scope.config = config
            scope.save(update_fields=["config"])
        return role

    all_scope = {}
    role_specs = [
        ("procurement", "SC-UAT 采购员", ALL_PURCHASE_PERMISSIONS, DataScope.ScopeType.ALL, all_scope, "procurement"),
        ("packer", "SC-UAT 装箱协调员", ALL_PACKING_PERMISSIONS, DataScope.ScopeType.ALL, all_scope, "packer"),
        ("auditor", "SC-UAT 只读审计员", ("supply.purchase_order.view", "supply.packing.view", "supply.consolidation.view", "supply.consolidation_site.view", "supply.shipment.view"), DataScope.ScopeType.ALL, all_scope, "auditor"),
        ("consolidator", "SC-UAT 集货员-A", ALL_CONSOLIDATION_PERMISSIONS, DataScope.ScopeType.CUSTOM, custom_config or {}, "consolidator"),
        ("shipper", "SC-UAT 发运员", ALL_SHIPMENT_PERMISSIONS, DataScope.ScopeType.CUSTOM, shipment_config or {}, "shipper"),
        ("scope-own", "SC-UAT OWN 负向主体", ("supply.consolidation.view",), DataScope.ScopeType.OWN, {}, "scope_own"),
        ("scope-department", "SC-UAT DEPARTMENT 负向主体", ("supply.consolidation.view",), DataScope.ScopeType.DEPARTMENT, {}, "scope_department"),
        ("scope-incomplete", "SC-UAT 残缺 CUSTOM 主体", ("supply.consolidation.view",), DataScope.ScopeType.CUSTOM, {"supplier_ids": [1]}, "scope_incomplete"),
    ]
    for slug, display, codes, scope_type, config, user_key in role_specs:
        role = role_for(slug, display, codes, scope_type, config)
        user = users.get(user_key)
        if user:
            UserRole.objects.get_or_create(tenant=tenant, user=user, role=role)


def _count_dataset(tenant: Tenant) -> dict[str, int]:
    from apps.audit.models import OperationLog

    return {
        "users": CustomUser.objects.filter(tenant=tenant, username__startswith="SC-UAT-").count(),
        "suppliers": SupplierMaster.objects.filter(tenant=tenant, code__startswith="SC-UAT-").count(),
        "orders": SupplyPurchaseOrder.objects.filter(tenant=tenant, order_no__startswith="SC-UAT-").count(),
        "packing_batches": PackingBatch.objects.filter(tenant=tenant).count(),
        "packing_boxes": PackingBox.objects.filter(tenant=tenant).count(),
        "consolidations": LooseCargoConsolidation.objects.filter(tenant=tenant, consolidation_no__startswith="SC-UAT-").count(),
        "consolidation_allocations": ConsolidationBoxAllocation.objects.filter(tenant=tenant).count(),
        "shipments": LooseCargoShipment.objects.filter(tenant=tenant, shipment_no__startswith="SC-UAT-").count(),
        "shipment_allocations": ShipmentBoxAllocation.objects.filter(tenant=tenant).count(),
        # The attachment service derives opaque ATT-* numbers by design.  The
        # synthetic tenant itself is the scope marker; count all controlled
        # assets under that tenant rather than weakening the service's number
        # generation just for UAT.
        "attachments": ControlledAttachment.objects.filter(tenant=tenant).count(),
        "packing_events": __import__("apps.packing.models", fromlist=["PackingEvent"]).PackingEvent.objects.filter(tenant=tenant).count(),
        "consolidation_events": ConsolidationEvent.objects.filter(tenant=tenant).count(),
        "shipment_events": __import__("apps.shipping.models", fromlist=["ShipmentEvent"]).ShipmentEvent.objects.filter(tenant=tenant).count(),
        "attachment_events": ControlledAttachmentEvent.objects.filter(tenant=tenant).count(),
        "operation_logs": OperationLog.objects.filter(tenant=tenant).count(),
    }


def generate_fixture(context: UATContext) -> dict[str, Any]:
    """Generate or replay the complete synthetic fixture in one transaction."""

    with transaction.atomic():
        tenant_a, created_a = _ensure_tenant("SC-UAT-A", context)
        tenant_b, created_b = _ensure_tenant("SC-UAT-B", context)
        suppliers_a = {code: _ensure_supplier(tenant_a, code) for code in ("SC-UAT-SUP-A", "SC-UAT-SUP-B", "SC-UAT-SUP-C")}
        suppliers_b = {"SC-UAT-SUP-X": _ensure_supplier(tenant_b, "SC-UAT-SUP-X")}
        users_a = {
            "procurement": _ensure_user(tenant_a, "SC-UAT-A-procurement", CustomUser.UserType.INTERNAL),
            "packer": _ensure_user(tenant_a, "SC-UAT-A-packer", CustomUser.UserType.INTERNAL),
            "consolidator": _ensure_user(tenant_a, "SC-UAT-A-consolidator", CustomUser.UserType.INTERNAL),
            "shipper": _ensure_user(tenant_a, "SC-UAT-A-shipper", CustomUser.UserType.INTERNAL),
            "auditor": _ensure_user(tenant_a, "SC-UAT-A-auditor", CustomUser.UserType.INTERNAL),
            "scope_own": _ensure_user(tenant_a, "SC-UAT-A-scope-own", CustomUser.UserType.INTERNAL),
            "scope_department": _ensure_user(tenant_a, "SC-UAT-A-scope-department", CustomUser.UserType.INTERNAL),
            "scope_incomplete": _ensure_user(tenant_a, "SC-UAT-A-scope-incomplete", CustomUser.UserType.INTERNAL),
            "unauthorized": _ensure_user(tenant_a, "SC-UAT-A-unauthorized", CustomUser.UserType.INTERNAL),
            "supplier_a": _ensure_user(tenant_a, "SC-UAT-A-supplier-a", CustomUser.UserType.EXTERNAL),
            "supplier_b": _ensure_user(tenant_a, "SC-UAT-A-supplier-b", CustomUser.UserType.EXTERNAL),
            "supplier_c": _ensure_user(tenant_a, "SC-UAT-A-supplier-c", CustomUser.UserType.EXTERNAL),
        }
        users_b = {
            "procurement": _ensure_user(tenant_b, "SC-UAT-B-procurement", CustomUser.UserType.INTERNAL),
            "packer": _ensure_user(tenant_b, "SC-UAT-B-packer", CustomUser.UserType.INTERNAL),
            "auditor": _ensure_user(tenant_b, "SC-UAT-B-auditor", CustomUser.UserType.INTERNAL),
            "supplier_x": _ensure_user(tenant_b, "SC-UAT-B-supplier-x", CustomUser.UserType.EXTERNAL),
        }
        for user_key, supplier_code in (("supplier_a", "SC-UAT-SUP-A"), ("supplier_b", "SC-UAT-SUP-B"), ("supplier_c", "SC-UAT-SUP-C")):
            _ensure_external_profile(users_a[user_key], suppliers_a[supplier_code])
        _ensure_external_profile(users_b["supplier_x"], suppliers_b["SC-UAT-SUP-X"])
        sku_a = _ensure_product(tenant_a)
        sku_b = _ensure_product(tenant_b)
        _ensure_roles(tenant_a, users_a)
        _ensure_roles(tenant_b, users_b)
        for supplier in suppliers_a.values():
            set_supplier_packing_capability(supplier_id=supplier.id, actor=users_a["packer"], can_self_pack=True, can_mix_order_packing=False)
        set_supplier_packing_capability(supplier_id=suppliers_b["SC-UAT-SUP-X"].id, actor=users_b["packer"], can_self_pack=True, can_mix_order_packing=False)

        order_specs_a = (
            ("SC-UAT-PO-L-001", "SC-UAT-SUP-A", SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO),
            ("SC-UAT-PO-L-002", "SC-UAT-SUP-B", SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO),
            ("SC-UAT-PO-L-003", "SC-UAT-SUP-A", SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO),
            ("SC-UAT-PO-L-004", "SC-UAT-SUP-C", SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO),
            ("SC-UAT-PO-C-001", "SC-UAT-SUP-C", SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO),
        )
        orders_a = {}
        for order_code, supplier_code, route in order_specs_a:
            order = _ensure_order(tenant_a, users_a["procurement"], suppliers_a[supplier_code], sku_a, order_code, route, context)
            orders_a[order_code] = _ensure_order_lifecycle(order, users_a["procurement"], route, context)
        order_b = _ensure_order(tenant_b, users_b["procurement"], suppliers_b["SC-UAT-SUP-X"], sku_b, "SC-UAT-PO-L-001", SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO, context)
        order_b = _ensure_order_lifecycle(order_b, users_b["procurement"], SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO, context)

        boxes_by_order = {}
        for code in ("SC-UAT-PO-L-001", "SC-UAT-PO-L-002", "SC-UAT-PO-L-003", "SC-UAT-PO-L-004"):
            boxes_by_order[code] = _ensure_packing(orders_a[code], users_a["packer"], context)
        _ensure_packing(order_b, users_b["packer"], context)

        south_site = _ensure_site(users_a["consolidator"], "SC-UAT-CN-SOUTH-01", "CN-SOUTH", context)
        south_site_2 = _ensure_site(users_a["consolidator"], "SC-UAT-CN-SOUTH-02", "CN-SOUTH", context)
        east_site = _ensure_site(users_a["consolidator"], "SC-UAT-CN-EAST-01", "CN-EAST", context)
        _ensure_site(users_a["consolidator"], "SC-UAT-CN-EXPIRED-01", "CN-SOUTH", context, inactive=True)
        south = _ensure_consolidation(users_a["consolidator"], south_site, "SC-UAT-LC-SOUTH-01", context)
        south_2 = _ensure_consolidation(users_a["consolidator"], south_site_2, "SC-UAT-LC-SOUTH-02", context)
        east = _ensure_consolidation(users_a["consolidator"], east_site, "SC-UAT-LC-EAST-01", context)
        south = _ensure_consolidation_allocation(users_a["consolidator"], south, boxes_by_order["SC-UAT-PO-L-001"] + boxes_by_order["SC-UAT-PO-L-002"], context)
        south = _ensure_consolidation_release(users_a["consolidator"], south, context)
        south_2 = _ensure_consolidation_allocation(users_a["consolidator"], south_2, boxes_by_order["SC-UAT-PO-L-004"], context)
        south_2 = _ensure_consolidation_release(users_a["consolidator"], south_2, context)
        east = _ensure_consolidation_allocation(users_a["consolidator"], east, boxes_by_order["SC-UAT-PO-L-003"], context)
        east = _ensure_consolidation_release(users_a["consolidator"], east, context)
        set_consolidation_supplier_capability(supplier_id=suppliers_a["SC-UAT-SUP-A"].id, can_submit_handover=True, actor=users_a["consolidator"], idempotency_key=f"{context.data_version}:capability:SC-UAT-SUP-A")
        set_consolidation_supplier_capability(supplier_id=suppliers_a["SC-UAT-SUP-B"].id, can_submit_handover=False, actor=users_a["consolidator"], idempotency_key=f"{context.data_version}:capability:SC-UAT-SUP-B")
        set_consolidation_supplier_capability(supplier_id=suppliers_a["SC-UAT-SUP-C"].id, can_submit_handover=True, actor=users_a["consolidator"], idempotency_key=f"{context.data_version}:capability:SC-UAT-SUP-C")

        south_allocations = list(south.allocations.order_by("box_id", "id"))
        first_south = south_allocations[0]
        accepted = _ensure_attachment(users_a["supplier_a"], first_south, context, state="accepted")
        submit_consolidation_handover(
            consolidation_id=south.id,
            allocation_id=first_south.id,
            actor=users_a["supplier_a"],
            expected_version=3,
            evidence_ids=[accepted.id],
            idempotency_key=f"{context.data_version}:handover:{first_south.id}",
            handover_method="supplier_web",
            handover_reference=f"SC-UAT-HANDOVER-{first_south.id}",
            channel="supplier_web",
        )
        _ensure_receive_ready(users_a["consolidator"], south, context)

        south2_allocations = list(south_2.allocations.order_by("box_id", "id"))
        if south2_allocations:
            _ensure_attachment(users_a["supplier_c"], south2_allocations[0], context, state="quarantined")
            # A separate allocation carries an invalid/rejected sample so the
            # fixture exercises accepted, rejected and quarantined evidence
            # outcomes without changing the quarantined allocation's history.
            if len(south2_allocations) > 1:
                _ensure_attachment(users_a["supplier_c"], south2_allocations[1], context, state="rejected")
            quarantine = mark_consolidation_exception(
                consolidation_id=south_2.id,
                allocation_id=south2_allocations[0].id,
                actor=users_a["consolidator"],
                expected_version=3,
                idempotency_key=f"{context.data_version}:exception:{south2_allocations[0].id}",
                exception_code="UAT_QUARANTINE",
                reason="Synthetic quarantined evidence",
            )[0]
            controlled_release_consolidation_box(
                consolidation_id=south_2.id,
                allocation_id=quarantine.id,
                actor=users_a["consolidator"],
                expected_version=4,
                idempotency_key=f"{context.data_version}:exception-release:{quarantine.id}",
                reason="Synthetic controlled release",
            )
            _ensure_receive_ready(users_a["consolidator"], south_2, context)
        _ensure_receive_ready(users_a["consolidator"], east, context)
        shipments = _ensure_shipment_flow(users_a["shipper"], south, south_allocations, south_site, context)

        _ensure_roles(
            tenant_a,
            users_a,
            custom_config={
                "supplier_ids": sorted(suppliers_a[s].id for s in suppliers_a),
                "supply_purchase_order_ids": sorted(order.id for order in orders_a.values()),
                "packing_batch_ids": sorted(PackingBatchOrder.objects.filter(tenant=tenant_a, order_id__in=[order.id for order in orders_a.values()]).values_list("batch_id", flat=True)),
                "consolidation_site_ids": sorted(ConsolidationSite.objects.filter(tenant=tenant_a, site_code__startswith="SC-UAT-CN-").values_list("id", flat=True)),
                "consolidation_ids": sorted(LooseCargoConsolidation.objects.filter(tenant=tenant_a, consolidation_no__startswith="SC-UAT-").values_list("id", flat=True)),
            },
            shipment_config={
                "supplier_ids": sorted(suppliers_a[s].id for s in suppliers_a),
                "supply_purchase_order_ids": sorted(order.id for order in orders_a.values()),
                "packing_batch_ids": sorted(PackingBatchOrder.objects.filter(tenant=tenant_a).values_list("batch_id", flat=True)),
                "consolidation_site_ids": sorted(ConsolidationSite.objects.filter(tenant=tenant_a, site_code__startswith="SC-UAT-CN-").values_list("id", flat=True)),
                "consolidation_ids": sorted(LooseCargoConsolidation.objects.filter(tenant=tenant_a, consolidation_no__startswith="SC-UAT-").values_list("id", flat=True)),
                "shipment_ids": sorted(shipment.id for shipment in shipments),
            },
        )
        counts = {tenant.code: _count_dataset(tenant) for tenant in (tenant_a, tenant_b)}
    return {"data_version": context.data_version, "payload_hash": context.payload_hash, "tenants": list(TENANT_CODES), "created": {"SC-UAT-A": created_a, "SC-UAT-B": created_b}, "counts": counts}


def _scope_config(role_code: str, scope_type: str) -> dict[str, Any] | None:
    role = Role.objects.filter(code=role_code).first()
    if role is None:
        return None
    scope = DataScope.objects.filter(role=role, scope_type=scope_type).first()
    return scope.config if scope else None


def check_fixture(context: UATContext) -> dict[str, Any]:
    """Validate identifiers, tenant isolation, quantities, scopes and states."""

    tenants = []
    for code in TENANT_CODES:
        tenant = Tenant.objects.filter(code=code).first()
        if tenant is None:
            raise UATDataError(f"Missing UAT tenant {code}.")
        if tenant.name != _marker(code, context):
            raise UATDataError(f"Tenant {code} version/payload marker is inconsistent.")
        tenants.append(tenant)
    tenant_a, tenant_b = tenants
    suppliers_a = list(SupplierMaster.objects.filter(tenant=tenant_a, code__startswith="SC-UAT-").order_by("code"))
    if {item.code for item in suppliers_a} != {"SC-UAT-SUP-A", "SC-UAT-SUP-B", "SC-UAT-SUP-C"}:
        raise UATDataError("Tenant A supplier set is incomplete or was modified.")
    for supplier in suppliers_a:
        if supplier.name != f"SC-UAT synthetic supplier {supplier.code}" or supplier.contact_phone or supplier.contact_email:
            raise UATDataError(f"Supplier {supplier.code} was modified outside the synthetic contract.")
    if SupplierMaster.objects.filter(tenant=tenant_b, code="SC-UAT-SUP-X").count() != 1:
        raise UATDataError("Tenant B supplier fixture is missing.")
    expected_orders = {"SC-UAT-PO-L-001", "SC-UAT-PO-L-002", "SC-UAT-PO-L-003", "SC-UAT-PO-L-004", "SC-UAT-PO-C-001"}
    orders_a = list(SupplyPurchaseOrder.objects.filter(tenant=tenant_a, order_no__startswith="SC-UAT-").prefetch_related("lines"))
    if {order.order_no for order in orders_a} != expected_orders:
        raise UATDataError("Tenant A order set is incomplete or was modified.")
    for order in orders_a:
        lines = list(order.lines.all())
        if len(lines) != 2 or any(line.quantity != 10 for line in lines):
            raise UATDataError(f"Order {order.order_no} violates the two-line quantity-10 contract.")
        if order.status != SupplyPurchaseOrder.Status.PRODUCTION_COMPLETED or order.completed_quantity != 20:
            raise UATDataError(f"Order {order.order_no} is not fully completed through the domain service.")
        expected_route = SupplyPurchaseOrder.ShippingRoute.CONTAINER_CARGO if order.order_no.endswith("PO-C-001") else SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO
        if order.shipping_route != expected_route:
            raise UATDataError(f"Order {order.order_no} has an unexpected shipping route.")
        if order.source_system != context.data_version:
            raise UATDataError(f"Order {order.order_no} is missing the UAT data-version marker.")
    loose_orders = [order for order in orders_a if order.shipping_route == SupplyPurchaseOrder.ShippingRoute.LOOSE_CARGO]
    batches = list(PackingBatch.objects.filter(tenant=tenant_a, batch_orders__order__in=loose_orders).distinct().prefetch_related("batch_orders", "boxes", "line_allocations"))
    if len(batches) != 8 or any(batch.status != PackingBatch.Status.COMPLETED for batch in batches):
        raise UATDataError("Expected eight completed two-batch packing records for four loose orders.")
    if PackingBox.objects.filter(tenant=tenant_a, batch__in=batches).count() != 8:
        raise UATDataError("Expected eight physical UAT packing boxes.")
    for order in loose_orders:
        order_batches = [batch for batch in batches if batch.batch_orders.filter(order=order).exists()]
        if len(order_batches) != 2:
            raise UATDataError(f"Order {order.order_no} does not have two active packing batches.")
        for line in order.lines.all():
            reserved = PackingBatchLineAllocation.objects.filter(batch__in=order_batches, order_line=line, state=PackingBatchLineAllocation.State.FROZEN).aggregate(total=__import__("django.db.models", fromlist=["Sum"]).Sum("quantity"))["total"] or 0
            if int(reserved) != 10:
                raise UATDataError(f"Order line {line.id} does not conserve its 6+4 allocation quantity.")
    consolidations = list(LooseCargoConsolidation.objects.filter(tenant=tenant_a, consolidation_no__startswith="SC-UAT-"))
    if {item.consolidation_no for item in consolidations} != {"SC-UAT-LC-SOUTH-01", "SC-UAT-LC-SOUTH-02", "SC-UAT-LC-EAST-01"}:
        raise UATDataError("Consolidation master set is incomplete.")
    south = next(item for item in consolidations if item.consolidation_no.endswith("SOUTH-01"))
    if south.status != LooseCargoConsolidation.Status.TRANSFERRED:
        raise UATDataError("South consolidation was not transferred through the domain service.")
    if ConsolidationBoxAllocation.objects.filter(tenant=tenant_a).count() < 8:
        raise UATDataError("Expected all eight physical boxes to have a consolidation history.")
    shipments = list(LooseCargoShipment.objects.filter(tenant=tenant_a, shipment_no__startswith="SC-UAT-"))
    if len(shipments) != 2 or any(item.status != LooseCargoShipment.Status.WAREHOUSE_CLEARED for item in shipments):
        raise UATDataError("Expected two warehouse-cleared UAT shipments.")
    if ShipmentBoxAllocation.objects.filter(tenant=tenant_a).count() != 4:
        raise UATDataError("Expected four transferred shipment allocations from the shared consolidation.")
    active_consumers = PackingBoxConsumption.objects.filter(tenant=tenant_a, active_guard=True).count()
    # South-02's quarantined box is intentionally controlled-released, so it
    # has no active downstream consumer.  The other seven physical boxes must
    # each have exactly one active consolidation/shipment consumer.
    if active_consumers != 7:
        raise UATDataError(f"Expected 7 active box consumers (one controlled release), found {active_consumers}.")
    attachment_states = set(ControlledAttachment.objects.filter(tenant=tenant_a).values_list("state", flat=True))
    if not {ControlledAttachment.State.ACCEPTED, ControlledAttachment.State.REJECTED, ControlledAttachment.State.QUARANTINED} <= attachment_states:
        raise UATDataError("Accepted, rejected and quarantined attachment samples are required.")
    con_role = Role.objects.filter(tenant=tenant_a, code="sc-uat-a-consolidator").first()
    ship_role = Role.objects.filter(tenant=tenant_a, code="sc-uat-a-shipper").first()
    if not con_role or not ship_role:
        raise UATDataError("UAT role matrix is incomplete.")
    con_scope = DataScope.objects.filter(role=con_role, scope_type=DataScope.ScopeType.CUSTOM).first()
    ship_scope = DataScope.objects.filter(role=ship_role, scope_type=DataScope.ScopeType.CUSTOM).first()
    if not con_scope or set(con_scope.config) != {"supplier_ids", "supply_purchase_order_ids", "packing_batch_ids", "consolidation_site_ids", "consolidation_ids"}:
        raise UATDataError("Consolidation CUSTOM scope is not complete.")
    if not ship_scope or set(ship_scope.config) != {"supplier_ids", "supply_purchase_order_ids", "packing_batch_ids", "consolidation_site_ids", "consolidation_ids", "shipment_ids"}:
        raise UATDataError("Shipment CUSTOM scope is not complete.")
    for item in list(SupplyPurchaseOrder.objects.filter(tenant=tenant_a)) + list(PackingBatch.objects.filter(tenant=tenant_a)) + list(LooseCargoConsolidation.objects.filter(tenant=tenant_a)) + list(LooseCargoShipment.objects.filter(tenant=tenant_a)):
        if getattr(item, "tenant_id", None) != tenant_a.id:
            raise UATDataError("A generated object crossed the tenant boundary.")
    return {"data_version": context.data_version, "payload_hash": context.payload_hash, "status": "PASS", "counts": {tenant.code: _count_dataset(tenant) for tenant in tenants}}


def cleanup_fixture(context: UATContext, tenant_codes: tuple[str, ...] = TENANT_CODES) -> dict[str, Any]:
    """Deactivate only the exact synthetic tenants; retain audit graphs.

    Domain events, attachment ledgers and records protected by those events are
    intentionally not physically deleted.  This is the safe outcome mandated
    by the UAT contract when append-only foreign keys prevent deletion.
    """

    selected = tuple(tenant_codes)
    if not selected or any(code not in TENANT_CODES for code in selected):
        raise UATDataError("Cleanup accepts only the exact SC-UAT-A/SC-UAT-B tenant codes.")
    result = []
    with transaction.atomic():
        for code in selected:
            tenant = Tenant.objects.filter(code=code).first()
            if tenant is None:
                continue
            expected = _marker(code, context)
            if tenant.name != expected:
                raise UATDataError(f"Refusing cleanup for {code}: data-version marker mismatch.")
            before = _count_dataset(tenant)
            users_qs = CustomUser.objects.filter(tenant=tenant, username__startswith="SC-UAT-")
            users_qs.update(is_active=False)
            MiniAppIdentity.objects.filter(user__tenant=tenant).update(status=MiniAppIdentity.Status.DISABLED)
            tenant.status = Tenant.Status.INACTIVE
            tenant.save(update_fields=["status", "updated_at"])
            after = _count_dataset(tenant)
            result.append({"tenant": code, "before": before, "after": after, "disabled_users": users_qs.count(), "retained_audit_graph": True})
    return {"data_version": context.data_version, "status": "DEACTIVATED_WITH_AUDIT_RETENTION", "tenants": result}
