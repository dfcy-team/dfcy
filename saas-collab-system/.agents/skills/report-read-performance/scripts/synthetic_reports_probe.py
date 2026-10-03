import hashlib
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path.cwd()))
import django
django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.accounts.models import CustomUser
from apps.reports.models import SavedReportView
from apps.tenants.models import Tenant
from tests.test_sales_management import client_for, grant

assert connection.vendor == "mysql" and connection.settings_dict["NAME"] == "read_audit"
config = {"dataset": "sales", "dimensions": ["currency"], "metrics": ["order_count"], "filters": {}}
dashboard = {"kind": "dashboard", "version": 1, "module": "销售管理", "filters": {}, "widgets": [
    {"id": f"w-{i}", "title": f"widget-{i}", "type": "table", "width": 6, "height": 300, "config": config}
    for i in range(8)
]}
metrics = []
for size in (2, 20):
    tenant, _ = Tenant.objects.get_or_create(code=f"synthetic-read-audit-views-{size}", defaults={"name": "Synthetic only"})
    viewer, created = CustomUser.objects.get_or_create(username=f"synthetic-read-audit-views-{size}", defaults={"tenant": tenant, "user_type": "internal"})
    if created:
        grant(viewer, "reports.view")
        grant(viewer, "sales_management.view")
    for i in range(size):
        SavedReportView.objects.get_or_create(tenant=tenant, owner=viewer, name=f"synthetic-{i}", defaults={"config": dashboard if i % 2 else config})
    client = client_for(viewer)
    for path in ("/api/report/views/", "/api/report/datasets/"):
        samples = []
        for i in range(3):
            connection.queries_log.clear()
            start = time.perf_counter()
            with CaptureQueriesContext(connection) as queries:
                response = client.get(path)
            assert response.status_code == 200, response.content[:200]
            samples.append({"elapsed_ms": round((time.perf_counter() - start) * 1000, 3), "query_count": len(queries)})
        metrics.append({"path": path, "saved_views": size, "dashboard_widgets": 8, "samples": samples,
            "response_bytes": len(response.content), "response_sha256": hashlib.sha256(response.content).hexdigest()})
with connection.cursor() as cursor:
    cursor.execute("SELECT VERSION(), @@version_comment")
    version = cursor.fetchone()
Path(sys.argv[1]).write_text(json.dumps({"database": version, "synthetic": True, "baseline_sha": "2141d8069ab210d4f5874dd8441622064ed4d423", "metrics": metrics}, indent=2), encoding="utf-8")
print(json.dumps({"database": version, "metrics": [{k: v for k, v in m.items() if k != "response_sha256"} for m in metrics]}))
