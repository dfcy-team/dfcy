"""Paired local probe; refuses non-synthetic MySQL and never touches cloud."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import types

sys.path.insert(0, str(Path.cwd()))
import django
django.setup()
from django.conf import settings
settings.ALLOWED_HOSTS = [*settings.ALLOWED_HOSTS, "testserver"]
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.accounts.models import CustomUser
from apps.products import urls, views
from apps.tenants.models import Tenant
from tests.test_product_detail_read_efficiency import _fixture, _client

assert connection.vendor == "mysql" and connection.settings_dict["NAME"] == "read_audit"
baseline = types.ModuleType("apps.products._historical_read_views")
source = subprocess.check_output(["git", "show", "2141d8069ab210d4f5874dd8441622064ed4d423:saas-collab-system/backend/apps/products/views.py"], text=True, encoding="utf-8")
exec(compile(source, "historical-product-views", "exec"), baseline.__dict__)
patterns = {pattern.name:pattern for pattern in urls.urlpatterns if pattern.name in {"product-detail-collection", "product-detail-export"}}
original = {name:pattern.callback for name,pattern in patterns.items()}
metrics=[]
for size in (100,1000):
    code=f"synthetic-detail-audit-{size}"
    tenant=Tenant.objects.filter(code=code).first()
    if tenant is None:
        tenant,user,_,_=_fixture(code,size)
    else:
        user=CustomUser.objects.get(username=f"detail-collection-{code}")
    measurements={}
    responses={}
    for name,module in [("before",baseline),("after",views)]:
        patterns["product-detail-collection"].callback=module.product_detail_collection
        patterns["product-detail-export"].callback=module.product_detail_export
        cache.clear()
        samples=[]
        for label,page in [("cold_page_1",1),("warm_page_1",1),("next_page",2)]:
            connection.queries_log.clear()
            start=time.perf_counter()
            with CaptureQueriesContext(connection) as queries:
                response=_client(user).get("/api/internal/products/details/",{"page":page,"page_size":20})
            assert response.status_code==200,response.content[:200]
            responses[(name,label)]=response.content
            sample={"label":label,"query_count":len(queries),"elapsed_ms":round((time.perf_counter()-start)*1000,3),
                "response_bytes":len(response.content),"response_sha256":hashlib.sha256(response.content).hexdigest()}
            if name=="after" and label=="cold_page_1":
                plans=[]
                for query in queries:
                    sql=query["sql"]
                    if "UNION ALL" in sql or ("SELECT COUNT" in sql and "products_productsku" in sql):
                        with connection.cursor() as cursor:
                            cursor.execute("EXPLAIN FORMAT=JSON "+sql)
                            plans.append({"sql":sql,"plan":json.loads(cursor.fetchone()[0])})
                sample["plans"]=plans
            samples.append(sample)
        connection.queries_log.clear()
        start=time.perf_counter()
        with CaptureQueriesContext(connection) as queries:
            exported=_client(user).get("/api/internal/products/details/export/")
        assert exported.status_code==200,exported.content[:200]
        responses[(name,"export")]=exported.content
        measurements[name]={"samples":samples,"export":{"query_count":len(queries),"elapsed_ms":round((time.perf_counter()-start)*1000,3),
            "response_bytes":len(exported.content),"response_sha256":hashlib.sha256(exported.content).hexdigest(),"streaming":exported.streaming}}
    for label in ("cold_page_1","warm_page_1","next_page","export"):
        assert responses[("before",label)]==responses[("after",label)],f"Response changed: {label}"
    metrics.append({"legacy_rows":size,"sku_rows":size,"distinct_result_rows":size*2-1,"page_size":20,"all_bytes_equal":True,**measurements})
for name,callback in original.items():
    patterns[name].callback=callback
with connection.cursor() as cursor:
    cursor.execute("SELECT VERSION(), @@version_comment")
    version=cursor.fetchone()
target=Path("../docs/05_test/data_read_audit_20261003/product-detail-mysql-evidence.json")
target.write_text(json.dumps({"database":version,"synthetic":True,"baseline_sha":"2141d8069ab210d4f5874dd8441622064ed4d423","method":"same API/fixtures; historical views swapped in local process only; page cache reset between before/after","metrics":metrics},indent=2),encoding="utf-8")
print(json.dumps({"metrics":[{"rows":m["distinct_result_rows"],"before":[{k:v for k,v in s.items() if k!="plans"}for s in m["before"]["samples"]],"after":[{k:v for k,v in s.items() if k!="plans"}for s in m["after"]["samples"]],"export_before":m["before"]["export"],"export_after":m["after"]["export"],"equal":m["all_bytes_equal"]}for m in metrics]}))
