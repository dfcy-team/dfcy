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
from django.db import connection
from django.test.utils import CaptureQueriesContext
from apps.common.responses import paginated_data
from apps.tenants.models import Tenant
from apps.accounts.models import CustomUser
from apps.workflows import views
from apps.workflows.models import ApprovalRequest, BusinessException, CollaborationEvent
from tests.test_workflow_read_efficiency import _rows
from tests.test_ui_p4_workflow_collaboration import client_for, grant

assert connection.vendor == "mysql" and connection.settings_dict["NAME"] == "read_audit"
baseline = types.ModuleType("apps.workflows._synthetic_historical_serializers")
source = subprocess.check_output(["git", "show", "2141d8069ab210d4f5874dd8441622064ed4d423:saas-collab-system/backend/apps/workflows/serializers.py"],text=True)
exec(compile(source, "historical-workflow-serializers", "exec"), baseline.__dict__)
optimized_page = views._page
def historical_page(request, queryset, serializer, query):
    return paginated_data(request, queryset, getattr(baseline, serializer.__name__), page=query["page"], page_size=query["page_size"])

metrics=[]
for model, permission, path in [
    (ApprovalRequest,"workflow.approvals.view","/api/internal/workflow/approvals/"),
    (BusinessException,"workflow.exceptions.view","/api/internal/workflow/exceptions/"),
    (CollaborationEvent,"workflow.collaboration.view","/api/internal/workflow/collaboration-events/")]:
    for size in (2,20):
        code=f"synthetic-wf-{model.__name__[:4]}-{size}"
        tenant,created=Tenant.objects.get_or_create(code=code,defaults={"name":"Synthetic only"})
        if created:
            user=CustomUser.objects.create_user(username=code,tenant=tenant,user_type="internal")
            grant(user,permission)
            _rows(model,tenant,user,size)
        else:
            user=CustomUser.objects.get(username=code)
        measurements={}
        responses={}
        for name,fn in [("before",historical_page),("after",optimized_page)]:
            views._page=fn
            samples=[]
            for _ in range(3):
                connection.queries_log.clear()
                start=time.perf_counter()
                with CaptureQueriesContext(connection) as queries:
                    response=client_for(user).get(path,{"page_size":20})
                assert response.status_code==200,response.content[:200]
                samples.append({"query_count":len(queries),"elapsed_ms":round((time.perf_counter()-start)*1000,3)})
            responses[name]=response.content
            measurements[name]={"samples":samples,"response_bytes":len(response.content),"response_sha256":hashlib.sha256(response.content).hexdigest()}
        assert responses["before"]==responses["after"],"Workflow response changed"
        metrics.append({"endpoint":path,"rows":size,"json_equal":True,**measurements})
views._page=optimized_page
with connection.cursor() as cursor:
    cursor.execute("SELECT VERSION(), @@version_comment")
    version=cursor.fetchone()
target=Path("../docs/05_test/data_read_audit_20261003/workflow-mysql-evidence.json")
target.write_text(json.dumps({"database":version,"synthetic":True,"baseline_sha":"2141d8069ab210d4f5874dd8441622064ed4d423","method":"same API and synthetic fixture; swap historical pagination/serializers in local process only","metrics":metrics},indent=2),encoding="utf-8")
print(json.dumps({"metrics":[{"endpoint":m["endpoint"],"rows":m["rows"],"before":m["before"]["samples"],"after":m["after"]["samples"],"equal":m["json_equal"]}for m in metrics]}))
