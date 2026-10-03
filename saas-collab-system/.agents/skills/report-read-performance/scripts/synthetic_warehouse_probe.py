"""Bounded local MySQL fixture/probe; refuses any non-synthetic database."""
import hashlib
import json
import sys
import time
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
import django
django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from apps.accounts.models import CustomUser
from apps.commerce.models import InventorySnapshot
from apps.integrations.models import WarehouseAuthorization
from apps.masterdata.models import PlatformMaster, WarehouseMaster
from apps.tenants.models import Tenant
from tests.test_sales_management import client_for, grant, create_run

assert connection.vendor == "mysql" and connection.settings_dict["NAME"] == "read_audit"
metrics = []
for size in (2, 20):
    code = f"synthetic-read-audit-wh-{size}"
    tenant, created = Tenant.objects.get_or_create(code=code, defaults={"name": "Synthetic only"})
    if created:
        viewer = CustomUser.objects.create_user(username=code, tenant=tenant, user_type="internal")
        grant(viewer, "masterdata.view")
        grant(viewer, "integrations.warehouse.view")
        platform = PlatformMaster.objects.create(tenant=tenant, code="myjf", name="马来极风", platform_type="warehouse_third_party")
        run = create_run(tenant, "inventory_snapshot", code, platform="jifeng_wms")
        now = timezone.now()
        for i in range(size):
            warehouse = WarehouseMaster.objects.create(tenant=tenant, service_platform=platform, code=f"wh-{i:03}", name=f"Synthetic {i}", country_code="MY", warehouse_type="third_party")
            WarehouseAuthorization.objects.create(tenant=tenant, integration_config=run.sync_job.integration_config,
                warehouse=warehouse, provider="jifeng_wms", credential_id="synthetic", status="active",
                validation_status="verified", last_verified_at=now, email="synthetic@example.test", created_by=viewer, updated_by=viewer)
            InventorySnapshot.objects.bulk_create([InventorySnapshot(tenant=tenant, warehouse=warehouse, source_run=run,
                site_code="MY", source_sku=f"synthetic-{j}", snapshot_at_utc=now-timedelta(seconds=2000-j), payload_hash="a"*64)
                for j in range(2000)], batch_size=500)
    else:
        viewer = CustomUser.objects.get(username=code)
    samples = []
    client = client_for(viewer)
    for i in range(3):
        connection.queries_log.clear()
        start = time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            response = client.get(f"/api/internal/master-data/warehouses/?page_size={size}")
        assert response.status_code == 200, response.content[:200]
        samples.append({"elapsed_ms": round((time.perf_counter()-start)*1000, 3), "query_count": len(queries)})
    plans = []
    for query in queries:
        sql = query["sql"]
        if "inventory_snapshot" in sql and sql.startswith("SELECT"):
            with connection.cursor() as cursor:
                cursor.execute("EXPLAIN FORMAT=JSON " + sql)
                plan = json.loads(cursor.fetchone()[0])
            plans.append({"sql":sql, "plan":plan})
            if len(plans) >= 2:
                break
    metrics.append({"page_size":size, "snapshot_rows_per_warehouse":2000, "samples":samples,
        "response_bytes":len(response.content), "response_sha256":hashlib.sha256(response.content).hexdigest(), "plans":plans})
with connection.cursor() as cursor:
    cursor.execute("SELECT VERSION(), @@version_comment")
    version = cursor.fetchone()
Path(sys.argv[1]).write_text(json.dumps({"synthetic":True, "database":version, "metrics":metrics}, indent=2),encoding="utf-8")
print(json.dumps({"metrics":[{k:v for k,v in row.items() if k != "plans"} for row in metrics]}))
