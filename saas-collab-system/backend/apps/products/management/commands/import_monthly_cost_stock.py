"""Reviewed complete third-party snapshot import; preview unless --apply."""
import csv
import hashlib
import json
from datetime import date
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from apps.tenants.models import Tenant
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductSKU
from apps.products.monthly_cost_reconciliation import register_inventory_evidence,seed_opening_balances,_quantity

class Command(BaseCommand):
    help="Preview or import a reviewed complete month-end physical snapshot and optional opening balance"
    def add_arguments(self,parser):
        parser.add_argument("csv_path")
        parser.add_argument("--tenant-id",type=int,required=True)
        parser.add_argument("--warehouse-id",type=int,required=True)
        parser.add_argument("--boundary",required=True,help="YYYY-MM-01 opening date")
        parser.add_argument("--snapshot-at",required=True,help="Aware ISO8601 provider cutoff")
        parser.add_argument("--source-reference",required=True)
        parser.add_argument("--complete",action="store_true",help="Source is reviewed full physical inventory")
        parser.add_argument("--seed-opening",action="store_true")
        parser.add_argument("--apply",action="store_true")
    def handle(self,*args,**options):
        try:
            if not options["complete"]:
                raise ValidationError("--complete is required; incremental inventory is not an opening balance")
            tenant=Tenant.objects.get(pk=options["tenant_id"])
            warehouse=WarehouseMaster.objects.get(tenant=tenant,pk=options["warehouse_id"])
            boundary=date.fromisoformat(options["boundary"])
            stamp=parse_datetime(options["snapshot_at"])
            content=Path(options["csv_path"]).read_bytes()
            reader=csv.DictReader(content.decode("utf-8-sig").splitlines())
            if set(reader.fieldnames or []) not in ({"sku_code","on_hand_qty"},{"sku_code","on_hand_qty","unit_cost"}):
                raise ValidationError("Use sku_code,on_hand_qty[,unit_cost] CSV columns")
            rows=list(reader);codes=[r["sku_code"].strip() for r in rows]
            if len(codes)!=len(set(codes)):
                raise ValidationError("Duplicate SKU rows")
            mapping={r.sku_code:r.pk for r in ProductSKU.objects.filter(tenant=tenant,sku_code__in=codes)}
            if len(mapping)!=len(codes):
                raise ValidationError("Unknown or foreign SKU code")
            quantities={str(mapping[r["sku_code"].strip()]):str(_quantity(r["on_hand_qty"])) for r in rows}
            prices={str(mapping[r["sku_code"].strip()]):str(_quantity(r["unit_cost"])) for r in rows if r.get("unit_cost","").strip()}
            # Validate with the same service inside a rollback transaction for preview.
            with transaction.atomic():
                evidence=register_inventory_evidence(tenant=tenant,warehouse=warehouse,boundary=boundary,
                    source_key="reviewed-file:"+hashlib.sha256(content).hexdigest(),snapshot_at=stamp,quantities=quantities,
                    metadata={"complete":True,"quantity_basis":"on_hand","as_of_boundary":True,
                        "source_reference":options["source_reference"],"reviewed":True,"row_count":len(rows)})
                result=seed_opening_balances(evidence,unit_costs=prices) if options["seed_opening"] else {"rows":len(rows)}
                if not options["apply"]:transaction.set_rollback(True)
            self.stdout.write(json.dumps({"status":"applied" if options["apply"] else "preview",**result},ensure_ascii=False))
        except (OSError,ValueError,ValidationError,Tenant.DoesNotExist,WarehouseMaster.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
