"""Read-only aggregate migration preflight. Never guesses countries or prices."""
import json

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.models import Exists, F, OuterRef

from apps.masterdata.models import SupplierMaster
from apps.products.models import ProductSKU
from apps.purchasing.models import PurchaseOrder as LegacyPurchase, SupplyPurchaseOrder
from apps.suppliers.models import SupplierShipment as LegacyShipment
from apps.supply_chain.models import (
    DispatchMembership, InboundLine, InboundOrder, PurchaseLine, PurchaseOrder,
    ShipmentLine, SupplierShipment,
)


class Command(BaseCommand):
    help = "Read-only legacy/new supply-chain counts and relationship preflight (JSON aggregates only)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-id", required=True, type=int)

    def handle(self, *args, **options):
        tenant_id = options["tenant_id"]
        if tenant_id <= 0:
            raise CommandError("Use a positive tenant ID.")
        sources = {"legacy_purchase": LegacyPurchase, "supply_f1_purchase": SupplyPurchaseOrder, "legacy_supplier_shipment": LegacyShipment}
        targets = {"purchase": PurchaseOrder, "shipment": SupplierShipment}
        required = {model._meta.db_table for model in (*sources.values(), *targets.values(), PurchaseLine, ShipmentLine, DispatchMembership, InboundOrder, InboundLine)}
        missing = sorted(required - set(connection.introspection.table_names()))
        result = {
            "status": "blocked" if missing else "preflight_complete",
            "source_rows": None, "target_rows": None, "schema_diff_count": len(missing),
            "constraint_violations": {}, "mismatched_chunks": [], "sample_artifact": None,
            "migration_executed": False,
            "recommended_action": "Apply reviewed schema in an isolated database first." if missing else "Review explicit country/source mappings before historical import; row totals alone do not prove equivalence.",
        }
        if missing:
            result["missing_tables"] = missing
        else:
            source_counts = {name: model.objects.filter(tenant_id=tenant_id).count() for name, model in sources.items()}
            target_counts = {name: model.objects.filter(tenant_id=tenant_id).count() for name, model in targets.items()}
            result.update(source_counts=source_counts, target_counts=target_counts, source_rows=sum(source_counts.values()), target_rows=sum(target_counts.values()))
            supplier = SupplierMaster.objects.filter(tenant_id=OuterRef("tenant_id"), pk=OuterRef("supplier_id"))
            sku = ProductSKU.objects.filter(tenant_id=OuterRef("tenant_id"), sku_code=OuterRef("sku_code"))
            legacy = LegacyPurchase.objects.filter(tenant_id=tenant_id)
            violations = {
                "legacy_unresolved_supplier": legacy.annotate(resolved=Exists(supplier)).filter(resolved=False).count(),
                "legacy_unresolved_sku": legacy.annotate(resolved=Exists(sku)).filter(resolved=False).count(),
                "purchase_tenant_mismatch": PurchaseOrder.objects.filter(tenant_id=tenant_id).exclude(supplier__tenant_id=F("tenant_id"), country__tenant_id=F("tenant_id")).count(),
                "purchase_line_tenant_mismatch": PurchaseLine.objects.filter(tenant_id=tenant_id).exclude(order__tenant_id=F("tenant_id"), sku__tenant_id=F("tenant_id")).count(),
                "shipment_order_tenant_mismatch": SupplierShipment.objects.filter(tenant_id=tenant_id).exclude(order__tenant_id=F("tenant_id")).count(),
                "shipment_line_source_mismatch": ShipmentLine.objects.filter(tenant_id=tenant_id, purchase_line__isnull=False).exclude(purchase_line__order_id=F("shipment__order_id"), purchase_line__sku_id=F("sku_id")).count(),
                "shipment_line_tenant_mismatch": ShipmentLine.objects.filter(tenant_id=tenant_id).exclude(shipment__tenant_id=F("tenant_id"), sku__tenant_id=F("tenant_id")).count(),
                "dispatch_country_mismatch": DispatchMembership.objects.filter(tenant_id=tenant_id, active_guard=True).exclude(batch__country_code_snapshot=F("shipment__order__country_code_snapshot")).count(),
                "dispatch_tenant_mismatch": DispatchMembership.objects.filter(tenant_id=tenant_id).exclude(batch__tenant_id=F("tenant_id"), shipment__tenant_id=F("tenant_id")).count(),
                "inbound_source_tenant_mismatch": InboundLine.objects.filter(tenant_id=tenant_id).exclude(inbound__tenant_id=F("tenant_id"), shipment_line__tenant_id=F("tenant_id")).count(),
            }
            result["constraint_violations"] = violations
            if any(violations.values()):
                result["status"] = "blocked"
                result["recommended_action"] = "Resolve failed reference/tenant checks before mapping or importing history. No records changed."
            elif result["source_rows"]:
                result["status"] = "mapping_required"
            result["mapping_requirements"] = ["explicit_country", "canonical_supplier_and_sku", "purchase_to_shipment_source", "legacy_status_review", "private_box_file_binding"]
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
