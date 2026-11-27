"""Read-only database summaries; stored rows and files are disposable query caches."""
import calendar
from contextlib import contextmanager
from datetime import date, timedelta
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import uuid

from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from .summary_models import FinanceSummaryDataset, FinanceSummaryState
from .summary_service import private_root, require_access


class SourceReadTimeout(ValidationError):
    default_detail = '来源读取超出安全时限，请缩小店铺或账期后重试。'


def write_document(path, template, source):
    from .summary_database_document import render, packed
    values = []
    prefix = '__finance_json_' + uuid.uuid4().hex + '_'
    def encode(value):
        values.append(value)
        return prefix + str(len(values)-1) + '__'
    html = render(template, source, encode=encode)
    def chunks(value):
        if isinstance(value, dict):
            yield '{'
            for index, (key, item) in enumerate(value.items()):
                if index:yield ','
                yield packed({key: None})[1:-5]
                yield from chunks(item)
            yield '}'
        elif isinstance(value, list) and len(value) > 500:
            yield '['
            for offset in range(0, len(value), 500):
                if offset:yield ','
                yield packed(value[offset:offset+500])[1:-1]
            yield ']'
        else:
            yield packed(value)
    digest = hashlib.sha256()
    with path.open('wb') as file, gzip.GzipFile(filename='', fileobj=file, mode='wb', mtime=0) as compressed:
        def write(text):
            raw = text.encode('utf-8')
            digest.update(raw)
            compressed.write(raw)
        offset = 0
        for match in re.finditer(re.escape(prefix) + r'(\d+)__', html):
            write(html[offset:match.start()])
            for chunk in chunks(values[int(match[1])]):write(chunk)
            offset = match.end()
        write(html[offset:])
    return digest.hexdigest()


@contextmanager
def source_budget():
    from django.db import connection, DatabaseError
    if connection.vendor != 'mysql':
        yield
        return
    with connection.cursor() as cursor:
        cursor.execute('SELECT @@SESSION.MAX_EXECUTION_TIME')
        previous = int(cursor.fetchone()[0])
        cursor.execute('SET SESSION MAX_EXECUTION_TIME=%s', [min(previous, 15000) if previous else 15000])
    try:
        yield
    except DatabaseError as error:
        if error.args and error.args[0] == 3024:
            raise SourceReadTimeout() from None
        raise
    finally:
        with connection.cursor() as cursor:
            cursor.execute('SET SESSION MAX_EXECUTION_TIME=%s', [previous])


def settings_version(tenant_id):
    row = FinanceSummaryDataset.objects.filter(tenant_id=tenant_id, active=True).select_related('accounting_state').order_by('-pk').first()
    return [row.pk, row.accounting_state.revision] if row else None


def seed_for(user):
    from .summary_initialization import template_bytes
    raw, manifest = template_bytes()
    raw += b'\n<!-- SaaS read query template v1 -->'
    digest = hashlib.sha256(raw).hexdigest()
    root = private_root()
    root.mkdir(parents=True, exist_ok=True)
    path = root / (digest + '.html.gz')
    if not path.exists():
        temporary = root / (digest + '.' + uuid.uuid4().hex + '.tmp')
        temporary.write_bytes(gzip.compress(raw))
        os.replace(temporary, path)
    with transaction.atomic():
        row, _ = FinanceSummaryDataset.objects.get_or_create(tenant=user.tenant, source_hash=digest,
            defaults={'active': False, 'label': '只读查询模板（非业务批次）', 'document_file': path.name,
                      'created_by': user, 'metadata': {'query_template': True, 'template_version': manifest['version']}})
        FinanceSummaryState.objects.get_or_create(dataset=row, defaults={'updated_by': user})
    return row


def query_scope(user, filters):
    from .summary_scopes import store_ids
    from apps.masterdata.models import StoreMaster
    visible = store_ids(user)
    requested = filters.get('store')
    if requested and requested not in set(map(str, visible)):
        raise PermissionDenied('店铺不在当前授权范围内。')
    stores = StoreMaster.objects.filter(tenant=user.tenant, pk__in=visible)
    if requested:
        stores = stores.filter(pk=int(requested))
    if filters.get('country'):
        stores = stores.filter(country_code=filters['country'])
    if filters.get('platform'):
        stores = stores.filter(platform__platform_type=filters['platform'])
    ids = list(stores.order_by('pk').values_list('pk', flat=True))
    try:
        month = filters.get('month', '')
        if not month:
            return {'from': '1900-01-01', 'to': '9999-12-31', 'stores': ids}
        start = date.fromisoformat(month + '-01')
        if start.strftime('%Y-%m') != month:
            raise ValueError()
        end = start.replace(day=calendar.monthrange(start.year, start.month)[1])
        if filters.get('period_type') == 'week' and filters.get('period') != 'undated':
            first = date.fromisoformat(filters['period'])
            last = first + timedelta(days=6)
            start = first.replace(day=1)
            end = last.replace(day=calendar.monthrange(last.year, last.month)[1])
    except (ValueError, KeyError):
        raise ValidationError('请选择统计月份；按整月读取分摊依据，周／半月再按所选区间查询。')
    return {'from': start.isoformat(), 'to': end.isoformat(), 'stores': ids}


def accounting_source_scope(scope, state):
    """Read every frozen original period before comparing it with current facts.

    Filters still select the requested display period; this widens only the
    authorized source dates, never the set of stores.
    """
    from .summary_service import unpack_values
    try:
        books = json.loads(unpack_values(state.values).get('html2-profit-closed-periods-v1', '{}'))
        if not isinstance(books, dict):
            raise ValueError()
        lower, upper = date.fromisoformat(scope['from']), date.fromisoformat(scope['to'])
        for key, book in books.items():
            if not isinstance(book, dict) or not isinstance(book.get('rows'), list):
                raise ValueError()
            month = book.get('month') or str(key)[-7:]
            if not isinstance(month, str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', month):
                raise ValueError()
            adjustment = book.get('adjustmentMonth')
            if not isinstance(adjustment, str) or not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', adjustment) or adjustment <= month:
                raise ValueError()
            first = date.fromisoformat(month + '-01')
            last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
            lower, upper = min(lower, first), max(upper, last)
    except (ValueError, TypeError, KeyError):
        raise ValidationError('已关账期间依据不完整，请核对账务设置后重试。') from None
    return {**scope, 'from': lower.isoformat(), 'to': upper.isoformat()}


def query_accounting_state(user, version, fallback=None):
    if not version:
        return fallback
    try:
        return FinanceSummaryState.objects.get(dataset_id=version[0], revision=version[1],
            dataset__tenant_id=user.tenant_id)
    except FinanceSummaryState.DoesNotExist:
        raise ValidationError('账务设置已变化，请刷新后重新查询。') from None


def request_query(user, payload, *, refresh=False, context=None):
    from .summary_jobs import request_calculation, current_dataset
    from .summary_models import FinanceSummaryCalculation
    from .summary_scopes import check_job_scope
    require_access(user)
    scope = query_scope(user, payload['filters'])
    version = settings_version(user.tenant_id)
    state = query_accounting_state(user, version)
    if state is not None:
        scope = accounting_source_scope(scope, state)
    spec = {'scope': scope, 'settings': version, 'accounting_history_version': 1,
            'generation': int(timezone.now().timestamp()) // (60 if refresh else 300), 'refresh': bool(refresh)}
    if context and not refresh:
        parent = FinanceSummaryCalculation.objects.filter(pk=context, tenant=user.tenant, kind='query',
            status='ready', finished_at__gte=timezone.now()-timedelta(minutes=5)).first()
        if parent:
            check_job_scope(parent, user)
            previous = parent.request.get('_database_query') or {}
            if previous.get('accounting_history_version') == 1 and previous.get('scope') == scope and current_dataset(parent):
                spec = previous
    payload = {**payload, 'filters': {**payload['filters'], '_stores': list(map(str, scope['stores']))},
               '_database_query': spec}
    return request_calculation(seed_for(user), user, payload)


def materialize_source(user, dataset, spec, path, token):
    from .summary_database import collect
    from .summary_service import document_path
    proof = path.with_suffix('.json')
    started = timezone.now()
    with source_budget():
        source = collect(user, spec['scope'], allow_legacy_zero=False, native=True)
    # Encode repeated fee evidence once; the native engine restores the exact objects.
    pool, indexes = [], {}
    for fact in source.get('facts', []):
        if not isinstance(fact.get('sp6th_components'), list):continue
        refs = []
        for part in fact['sp6th_components']:
            key = (part['field'], part['label'], part['amount'])
            if key not in indexes:
                indexes[key] = len(pool)
                pool.append(part)
            refs.append(indexes[key])
        fact['sp6th_components'] = refs
    source['native_components'] = pool
    temporary = path.with_suffix('.tmp-' + token)
    try:
        digest = write_document(temporary, gzip.decompress(document_path(dataset).read_bytes()).decode('utf-8'), source)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    info = {'sha256': digest, 'read_at': source['read_at'],
            'source_rows_read': source.get('source_counts', {}).get('platform_finance'),
            'read_ms': round((timezone.now()-started).total_seconds()*1000, 2)}
    temporary = proof.with_suffix('.tmp-' + token)
    temporary.write_text(json.dumps(info), encoding='utf-8')
    os.replace(temporary, proof)


def launch_source_worker(request):
    try:
        result = subprocess.run([sys.executable, '-m', 'apps.finance.summary_source_worker'],
            input=json.dumps(request), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding='utf-8', timeout=600, cwd=str(Path(__file__).resolve().parents[2]))
        reply = json.loads(result.stdout) if result.returncode == 0 else {}
    except subprocess.TimeoutExpired:
        raise SourceReadTimeout() from None
    except (OSError, ValueError):
        raise ValidationError('来源读取未完成，请重试；未更改账务数据。') from None
    if not isinstance(reply, dict):
        reply = {}
    if reply.get('code') == 'SOURCE_READ_TIMEOUT':
        raise SourceReadTimeout()
    if reply.get('ok') is not True:
        raise ValidationError('来源读取未完成，请重试；未更改账务数据。')


def execute(dataset, user, payload):
    from .summary_native import query, CalculationBusy, materialization_guard
    from .summary_jobs import calculation_key
    spec = payload['_database_query']
    if spec.get('accounting_history_version') != 1:
        raise ValidationError('查询版本已更新，请重新发起查询。')
    state = query_accounting_state(user, spec['settings'], dataset.accounting_state)
    if accounting_source_scope(spec['scope'], state) != spec['scope']:
        raise ValidationError('本次查询缺少已关账期间依据，请重新发起查询。')
    key = calculation_key(dataset, 'query', {'_database_query': spec})
    path = private_root() / ('read-query-' + key + '.html.gz')
    proof = path.with_suffix('.json')
    if not path.exists() or not proof.exists():
        lock_key = 'finance-read-query:' + key
        token = uuid.uuid4().hex
        if not cache.add(lock_key, token, 900):
            raise CalculationBusy()
        try:
            if not path.exists() or not proof.exists():
                with materialization_guard():
                    launch_source_worker({'user': user.pk, 'tenant': user.tenant_id,
                        'document_file': dataset.document_file, 'scope': spec['scope'],
                        'filename': path.name, 'token': token})
                if not path.is_file() or not proof.is_file():
                    raise ValidationError('来源读取未完成，请重试；未更改账务数据。')
        finally:
            if cache.get(lock_key) == token:
                cache.delete(lock_key)
    info = json.loads(proof.read_text(encoding='utf-8'))
    derived = SimpleNamespace(tenant_id=dataset.tenant_id, pk=dataset.pk, source_hash=info['sha256'],
        document_file=path.name, metadata={'database_scope': spec['scope'], 'direct_query': True}, accounting_state=state)
    result = query(derived, {k: v for k, v in payload.items() if k != '_database_query'})
    result.update(direct_query=True, source_read_at=info['read_at'], source_read_ms=info['read_ms'],
                  source_rows_read=info.get('source_rows_read'))
    return result
