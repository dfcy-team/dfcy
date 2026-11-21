"""Project actual warehouse shipments from the latest package snapshot."""
import hashlib
import json
from collections import Counter
from datetime import timezone
from zoneinfo import ZoneInfo

from django.utils.dateparse import parse_datetime

from .warehouse_order_models import WarehouseOutboundLine

MAX_SIGNED_BIGINT = 2**63 - 1
COUNTRY_ZONES = {"PH": "Asia/Manila", "TH": "Asia/Bangkok", "MY": "Asia/Kuala_Lumpur"}


def shipment_projection(packages, *, site_code):
    """Return valid lines and deterministic counts for whole-document quarantine."""
    diagnostics = Counter()
    packages = packages or []
    normalized_site = str(site_code or "").strip().upper()
    if normalized_site not in COUNTRY_ZONES:
        return [], {"unsupported_snapshot_site_code": len(packages)}
    identities = Counter(str(package.get("warehouse_order_no") or "").strip() for package in packages)
    valid = []
    for package in packages:
        document = str(package.get("warehouse_order_no") or "").strip()
        reason = None
        if not document or identities[document] != 1:
            reason = "duplicate_or_missing_document"
        elif str(package.get("status", "")).upper() not in {"7", "SHIPPED", "DELIVERED"}:
            continue
        elif len(document) > 191:
            reason = "document_too_long"
        if reason is None:
            try:
                shipped_at = parse_datetime(str(package.get("shipped_at_utc") or ""))
            except (ValueError, OverflowError):
                shipped_at = None
            if shipped_at is None or shipped_at.utcoffset() is None:
                reason = "invalid_shipped_at"
            else:
                try:
                    shipped_at = shipped_at.astimezone(timezone.utc)
                    local = shipped_at.astimezone(ZoneInfo(COUNTRY_ZONES[normalized_site]))
                    valid_range = 1000 <= shipped_at.year <= 9998 and 1000 <= local.year <= 9998
                except (ValueError, OverflowError):
                    valid_range = False
                if not valid_range:
                    reason = "shipped_at_out_of_range"
        quantities = Counter()
        if reason is None:
            for item in package.get("items") or []:
                warehouse_sku = str(item.get("warehouse_sku") or "").strip()
                source_sku = str(item.get("sku") or "").strip()
                raw_quantity = item.get("quantity")
                quantity = "" if raw_quantity is None else str(raw_quantity).strip()
                if not (warehouse_sku or source_sku):
                    continue
                if not quantity.isascii() or not quantity.isdecimal() or len(quantity) > 18:
                    reason = "invalid_quantity"
                    break
                quantities[warehouse_sku, source_sku] += int(quantity)
            if reason:
                pass
            elif any(len(warehouse_sku) > 191 or len(source_sku) > 191 for warehouse_sku, source_sku in quantities):
                reason = "sku_too_long"
            elif any(qty > MAX_SIGNED_BIGINT for qty in quantities.values()):
                reason = "quantity_overflow"
        if reason:
            diagnostics[reason] += 1
            continue
        for (warehouse_sku, source_sku), quantity in sorted(quantities.items()):
            if quantity:
                valid.append((document, shipped_at, warehouse_sku, source_sku, quantity))
    return valid, dict(diagnostics)


def shipment_lines(packages, *, site_code=None):
    """Compatibility iterator; no site means no trusted projection eligibility."""
    if not site_code:
        return iter(())
    return iter(shipment_projection(packages, site_code=site_code)[0])


def replace_shipment_lines(lookup_id, tenant_id, warehouse_id, packages, *, site_code):
    """Replace projection under caller's lookup lock, isolating unsafe documents."""
    normalized_site = str(site_code or "").strip().upper()
    if not normalized_site:
        lines, diagnostics = [], {"missing_snapshot_site_code": 1}
    else:
        lines, diagnostics = shipment_projection(packages, site_code=normalized_site)
    rows = []
    for document, shipped_at, warehouse_sku, source_sku, quantity in lines:
        doc_key = hashlib.sha256(document.encode("utf-8")).hexdigest()
        identity = json.dumps([document, warehouse_sku, source_sku], ensure_ascii=False, separators=(",", ":"))
        identity_key = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        rows.append(WarehouseOutboundLine(lookup_id=lookup_id, tenant_id=tenant_id, warehouse_id=warehouse_id,
            site_code=normalized_site, document=document, document_key=doc_key, identity_key=identity_key,
            shipped_at=shipped_at, warehouse_sku=warehouse_sku, source_sku=source_sku, quantity=quantity))
    WarehouseOutboundLine.objects.filter(lookup_id=lookup_id).delete()
    WarehouseOutboundLine.objects.bulk_create(rows)
    return diagnostics
