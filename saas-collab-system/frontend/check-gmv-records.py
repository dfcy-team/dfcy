import json
import time
from pathlib import Path
from django.contrib.auth import get_user_model
from django.db import connection

namespace = {'__name__': 'apps.integrations.gmv_max_records_probe', '__package__': 'apps.integrations'}
exec(compile(Path('/tmp/gmv_max_records_candidate.py').read_text(), '<candidate>', 'exec'), namespace)
user = get_user_model().objects.get(username='root', tenant_id=1, is_active=True)
assert user.is_superuser
def readonly(execute, sql, params, many, context):
    assert sql.lstrip().split()[0].upper() in {'SELECT', 'SHOW'}, sql[:50]
    return execute(sql, params, many, context)
with connection.execute_wrapper(readonly):
    for label, params in [('all', {}), ('recent', {'started_from':'2026-11-09','started_to':'2026-11-10'}),
        ('failed', {'status':'failed'}), ('forbidden-store', {'subject_key':'store:2147483647'}),
        ('wrong-platform', {'platform':'shopee'})]:
        start=time.monotonic()
        data=namespace['gmv_max_records'](user, params)
        print(json.dumps({'case':label,'seconds':round(time.monotonic()-start,3),
            'total':data['pagination']['total'],'returned':len(data['results']),
            'sample':[{k:r[k] for k in ['id','subject_name','status','evidence']} for r in data['results'][:1]]},ensure_ascii=False),flush=True)
        if label in ('forbidden-store','wrong-platform'):
            assert data['pagination']['total']==0
