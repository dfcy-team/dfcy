"""Synthetic MySQL benchmark; refuses any non-local, non-benchmark database."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter
import types
from datetime import timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")
import django
django.setup()

from django.conf import settings
from django.apps import apps
from django.db import connection
from django.db.models import QuerySet
from django.http import QueryDict
from django.test.utils import CaptureQueriesContext
from apps.commerce.models import InventorySnapshot
from apps.masterdata.models import WarehouseMaster
from apps.products.models import ProductSKU, ProductSPU
from apps.sales_management import views
from tests.test_sales_management import NOW, create_scope, create_run, user_for


def digest(payload):
    copied = dict(payload)
    copied.pop("freshness", None)
    return hashlib.sha256(json.dumps(copied, sort_keys=True, default=str).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=325744)
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--baseline", default="v2.44.192-deployed")
    parser.add_argument("--prepare-schema", action="store_true")
    args = parser.parse_args()
    db = settings.DATABASES["default"]
    if db["ENGINE"] != "django.db.backends.mysql" or db["HOST"] not in {"127.0.0.1", "localhost"} or db["NAME"] != "inventory_perf_local":
        raise SystemExit("Only the isolated local inventory_perf_local MySQL database is allowed.")
    if args.prepare_schema:
        # Create only an isolated benchmark schema; historical MySQL migrations
        # in unrelated modules need not run for this synthetic measurement.
        with connection.cursor() as cursor:
            cursor.execute("SET FOREIGN_KEY_CHECKS=0")
        try:
            existing = set(connection.introspection.table_names())
            for name in (
                "tenants.Tenant", "accounts.CustomUser", "masterdata.PlatformMaster",
                "masterdata.StoreMaster", "masterdata.WarehouseMaster", "products.ProductSPU",
                "products.ProductSKU", "integrations.PlatformIntegrationConfig", "integrations.SyncJob",
                "integrations.SyncRun", "permissions.Permission", "permissions.Role",
                "permissions.UserRole", "permissions.DataScope", "commerce.InventorySnapshot",
            ):
                model = apps.get_model(name)
                if model._meta.db_table not in existing:
                    with connection.schema_editor(atomic=False) as editor:
                        editor.create_model(model)
                    existing.add(model._meta.db_table)
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")
    if args.rows <= 0 or args.samples <= 0 or InventorySnapshot.objects.exists():
        raise SystemExit("Positive counts and an empty synthetic inventory table are required.")
    tenant, _, _, warehouse = create_scope("inventory-perf-local")
    run = create_run(tenant, "inventory_snapshot", "inventory-perf-local", platform="jifeng_wms")
    user = user_for(tenant, "inventory-perf-viewer")
    user.is_superuser = True
    user.save(update_fields=["is_superuser"])
    warehouses = [warehouse] + [WarehouseMaster.objects.create(
        tenant=tenant, code=f"BENCH-{i}", name=f"Synthetic warehouse {i}",
        country_code="PH", warehouse_type="third_party",
    ) for i in range(1, 4)]
    spu = ProductSPU.objects.create(tenant=tenant, spu_code="BENCH", product_name="Synthetic benchmark")
    physical = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="BENCH-P", inventory_type="physical")
    virtual = ProductSKU.objects.create(tenant=tenant, spu=spu, sku_code="BENCH-V", inventory_type="virtual")
    for start in range(0, args.rows, 2000):
        batch = []
        for index in range(start, min(args.rows, start + 2000)):
            identity = index % 20000
            quantity = identity % 12
            batch.append(InventorySnapshot(
                tenant=tenant, warehouse=warehouses[identity % 4], source_run=run,
                site_code="PH", source_sku=f"SYNTH-{identity:06}",
                internal_sku=virtual if identity % 10 == 0 else physical if identity % 3 == 0 else None,
                snapshot_at_utc=NOW + timedelta(days=index // 20000),
                on_hand_qty=quantity + 2, available_qty=quantity, reserved_qty=identity % 8,
                payload_hash="f" * 64,
            ))
        # Synthetic fixture only: avoid the production manager's per-row
        # validation queries when constructing a known deterministic dataset.
        QuerySet(model=InventorySnapshot, using=connection.alias).bulk_create(batch, batch_size=2000)
    raw = subprocess.check_output(["git", "show", f"{args.baseline}:saas-collab-system/backend/apps/sales_management/views.py"], text=True, encoding="utf-8")
    baseline = types.ModuleType("apps.sales_management.benchmark_baseline")
    baseline.__package__ = "apps.sales_management"
    exec(compile(raw, "benchmark_baseline.py", "exec"), baseline.__dict__)
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION MAX_EXECUTION_TIME=15000")
        cursor.execute("ANALYZE TABLE inventory_snapshot")
    report = {"rows": args.rows, "identities": 20000, "baseline": args.baseline, "runs": []}
    for label, module in (("baseline", baseline), ("optimized", views)):
        for page, func, permission in (
            ("workbench", module.inventory_workbench_payload, "sales_management.view"),
            ("analysis", module.commerce_inventory_payload, "analytics.view"),
        ):
            request = types.SimpleNamespace(
                user=user, query_params=QueryDict("include_virtual=false&perspective=operations&page=1&page_size=20"),
                build_absolute_uri=lambda path: "http://benchmark.invalid/" + path,
                path="/inventory/",
            )
            for sample in range(args.samples):
                started = perf_counter()
                try:
                    with CaptureQueriesContext(connection) as queries:
                        payload = func(request, permission)
                    entry = {"variant": label, "page": page, "sample": sample + 1,
                             "elapsed_ms": round((perf_counter() - started) * 1000, 1),
                             "queries": len(queries), "digest": digest(payload),
                             "status": "PASS", "count": payload.get("count", payload.get("totals", {}).get("sku_count"))}
                except Exception as exc:
                    entry = {"variant": label, "page": page, "status": "FAILED",
                             "error_type": type(exc).__name__, "elapsed_ms": round((perf_counter() - started) * 1000, 1)}
                report["runs"].append(entry)
                print(json.dumps(entry), flush=True)
                if entry["status"] != "PASS":
                    break
    for page in ("workbench", "analysis"):
        passed = [item for item in report["runs"] if item["page"] == page and item["status"] == "PASS"]
        hashes = {item["digest"] for item in passed}
        variants = {item["variant"] for item in passed}
        report[f"{page}_equivalent"] = len(hashes) == 1 and variants == {"baseline", "optimized"}
    print(json.dumps(report), flush=True)
    if any(item["status"] != "PASS" for item in report["runs"]) or not all(
        report[f"{page}_equivalent"] for page in ("workbench", "analysis")
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
