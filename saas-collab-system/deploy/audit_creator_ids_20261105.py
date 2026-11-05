"""Full ID inventory, SQL read-only. Format checks are not API verification."""
from collections import Counter, defaultdict
import json
from pathlib import Path
from django.contrib.auth import get_user_model
from django.db import connection, transaction
from apps.influencers.models import Influencer
from apps.influencers.scopes import filter_queryset, require_scope

root = Path('/tmp/creator-id-inventory-20261105')
root.mkdir(mode=0o700, exist_ok=False)
counts = defaultdict(Counter)
numeric_owners = defaultdict(list)
issues = []
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
    actor = get_user_model().objects.get(pk=1, tenant_id=1, is_active=True)
    require_scope(actor, 'influencers.manage')
    rows = filter_queryset(actor, Influencer.objects.filter(tenant_id=1), 'influencers.manage').values(
        'id', 'code', 'platform', 'handle', 'status', 'profile__external_influencer_id')
    for row in rows.iterator(chunk_size=1000):
        platform = str(row['platform']).strip().lower()
        value = str(row['profile__external_influencer_id'] or '').strip()
        state = 'missing' if not value else 'numeric_format_valid' if value.isascii() and value.isdecimal() and len(value) <= 20 and int(value) > 0 else 'not_numeric_format'
        counts[platform]['total'] += 1
        counts[platform][state] += 1
        if not str(row['handle'] or '').strip():
            counts[platform]['username_missing'] += 1
        if value:
            numeric_owners[(platform, value)].append(row['id'])
        if state != 'numeric_format_valid':
            issues.append({**row, 'id_state':state})
duplicates = [{'platform':k[0], 'external_id':k[1], 'archive_ids':v} for k,v in numeric_owners.items() if len(v)>1]
summary = {'platforms':dict(counts), 'duplicate_id_groups':len(duplicates),
           'duplicate_id_archives':sum(len(x['archive_ids']) for x in duplicates),
           'provider_calls':0, 'business_writes':0, 'note':'Numeric format is not verified identity; duplicates require group review.'}
(root/'issues.json').write_text(json.dumps(issues))
(root/'duplicates.json').write_text(json.dumps(duplicates))
(root/'summary.json').write_text(json.dumps(summary))
print(json.dumps({'receipt':str(root),**summary}))
