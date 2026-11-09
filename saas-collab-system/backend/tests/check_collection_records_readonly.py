"""Run through manage.py shell against a staged helper; SELECT-only smoke checks."""
from pathlib import Path
from django.contrib.auth import get_user_model

scope = {'__package__': 'apps.integrations'}
exec(compile(Path('/tmp/collection_records_20261109.py').read_text(), 'collection_records.py', 'exec'), scope)
user = get_user_model().objects.get(pk=1, tenant_id=1)
query = scope['collection_records']
for source in ('video', 'creator'):
    params = {'record_source': source, 'page_size': 2}
    data = query(user, params)
    assert len(data['results']) <= 2
    assert all(row['sync_job_id'] is None and row['created_count'] is None for row in data['results'])
    assert query(user, {**params, 'platform': 'shopee'})['pagination']['total'] == 0
    assert query(user, {**params, 'subject_key': 'store:0'})['pagination']['total'] == 0
    assert query(user, {**params, 'sync_job_id': '123'})['pagination']['total'] == 0
    assert query(user, {**params, 'started_from': '2099-01-01'})['pagination']['total'] == 0
    if data['pagination']['total'] > 2:
        other = query(user, {**params, 'page': 2})
        assert not {r['id'] for r in data['results']} & {r['id'] for r in other['results']}
    print(source, 'PASS', 'visible_records=', data['pagination']['total'])
