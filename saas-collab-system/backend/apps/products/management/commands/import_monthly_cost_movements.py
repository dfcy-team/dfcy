"""Import reviewed non-sale stock facts without inventing warehouse events."""
import csv,json
from datetime import date
from decimal import Decimal
from pathlib import Path
from django.core.management.base import BaseCommand,CommandError
from django.core.exceptions import ValidationError
from django.db import transaction
from apps.products.monthly_cost_models import MonthlyCostMovement
from apps.products.models import ProductSKU
from apps.masterdata.models import WarehouseMaster

class Command(BaseCommand):
    help="Preview non-sale movement CSV; --apply writes immutable reviewed facts"
    def add_arguments(self,parser):
        parser.add_argument("csv_path")
        parser.add_argument("--tenant-id",type=int,required=True)
        parser.add_argument("--apply",action="store_true")
    def handle(self,*args,**options):
        try:
            reader=csv.DictReader(Path(options["csv_path"]).read_text(encoding="utf-8-sig").splitlines())
            required={"warehouse_id","sku_code","month","kind","quantity","amount","source_key","source_reference"}
            if set(reader.fieldnames or [])!=required:raise ValidationError("Unexpected movement CSV columns")
            count=skipped=0
            with transaction.atomic():
                for raw in reader:
                    warehouse=WarehouseMaster.objects.get(tenant_id=options["tenant_id"],pk=int(raw["warehouse_id"]))
                    sku=ProductSKU.objects.get(tenant_id=options["tenant_id"],sku_code=raw["sku_code"].strip())
                    if not raw["source_reference"].strip():raise ValidationError("Source document reference is required")
                    values=dict(sku=sku,warehouse=warehouse,month=date.fromisoformat(raw["month"]+"-01"),
                        kind=raw["kind"],quantity=Decimal(raw["quantity"]),
                        amount=Decimal(raw["amount"]) if raw["amount"].strip() else None,
                        evidence={"reviewed":True,"source_reference":raw["source_reference"],"import":"monthly_movement_csv"})
                    existing=MonthlyCostMovement.objects.filter(tenant_id=options["tenant_id"],source_key=raw["source_key"]).first()
                    if existing:
                        if any(getattr(existing,key)!=value for key,value in values.items()):raise ValidationError("Movement source key changed")
                        skipped+=1;continue
                    MonthlyCostMovement.objects.create(tenant_id=options["tenant_id"],source_key=raw["source_key"],**values)
                    count+=1
                if not options["apply"]:transaction.set_rollback(True)
            self.stdout.write(json.dumps({"status":"applied" if options["apply"] else "preview","rows":count,"skipped":skipped}))
        except (OSError,ValueError,ArithmeticError,ValidationError,WarehouseMaster.DoesNotExist,ProductSKU.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
