"""Audited preview corrections. Source workbooks and registered facts stay immutable."""
import json
import re
from collections import Counter, defaultdict
from copy import deepcopy
from decimal import Decimal, InvalidOperation

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.commerce.models import SalesOrder
from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster
from .models import FinanceAuditLog
from .warehouse_fee_models import WarehouseBillUpload, WarehouseFee
from .warehouse_fee_services import FeeInput, hash_value
from .warehouse_bill_matching import LocalOrderLookup, apply_match, manual_source

EDIT_KEY = '_row_edits'
EDIT_FIELDS = {'store_id', 'warehouse_id', 'external_order_id', 'fee_item', 'amount', 'currency', 'occurred_on', 'note'}
REASON_FIELDS = {'store_id', 'warehouse_id', 'external_order_id', 'amount', 'currency'}
IDENTITY_FIELDS = ['kind', 'country', 'warehouse_id', 'store_id', 'bill_number', 'bill_month', 'external_order_id', 'fee_item', 'reference']


def plain(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def source_key(source, data):
    return hash_value([source.get('sheet'), source.get('row'), source.get('source_rows'), data['kind'], data['reference']])


def signature(source):
    return hash_value({k: source.get(k) for k in ['sha256', 'sheet', 'row', 'source_rows', 'raw_store', 'raw_stores', 'raw_warehouse', 'raw_warehouses', 'raw_platform', 'raw_amount']})


def provenance_conflicts(user, job, rows):
    def origin(source):
        return hash_value([source.get(k) for k in ['sha256', 'sheet', 'row', 'source_rows']])
    known = defaultdict(set)
    fees = WarehouseFee.objects.filter(tenant=user.tenant, source__sha256=job.file_hash)
    if len(rows) <= 500:
        fees = fees.filter(source__row__in=list({r.source.get('row') for r in rows}))
    for key, source in fees.values_list('business_key', 'source').iterator(chunk_size=500):
        known[origin(source)].add(key)
    return {row.number for row in rows if known[origin(row.source)]
            and known[origin(row.source)] != {hash_value([row.data.get(k) for k in IDENTITY_FIELDS])}}


def audit_id(job, row):
    return f'{job.pk}:{source_key(row.source, row.data)[:32]}'


def order_lookup(user, rows):
    orders = defaultdict(list)
    ids = sorted({r.data.get('external_order_id') for r in rows if r.data.get('external_order_id')})
    for offset in range(0, len(ids), 500):
        for external, store, pk in SalesOrder.objects.filter(tenant=user.tenant,
                external_order_id__in=ids[offset:offset + 500]).values_list('external_order_id', 'store_id', 'pk'):
            orders[external].append((store, pk))
    return orders


def match_status(data, orders):
    if data['kind'] == 'other':
        return 'not_applicable'
    matches = [pk for store, pk in orders.get(data.get('external_order_id'), []) if store == data.get('store_id')]
    return 'matched' if len(matches) == 1 else 'ambiguous' if matches else 'unmatched'


def corrected_issues(row, changed):
    issues = []
    for issue in row.source.get('parser_issues', []):
        if row.source.get('settlement_policy') and issue.startswith((
                '订单明细与账单汇总差额', '其他费用明细与账单汇总差额', '原账单订单计费重复',
                '额外结算项目需确认分类及是否与明细重复')):
            continue
        if issue.startswith('订单明细与账单汇总差额'):
            continue  # Recomputed from effective values, never from the edited display total.
        if 'amount' in changed and issue == '金额缺失、公式无缓存或非正数':
            continue
        if 'currency' in changed and issue == '账单未注明结算币种，请补充确认':
            continue
        if 'external_order_id' in changed and issue == '平台订单号格式异常或已使用科学计数法':
            continue
        if (issue == '平台订单号格式异常或已使用科学计数法' and manual_source(row.source)
                and row.source.get('correction', {}).get('reason') and row.data.get('store_id')
                and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', row.data.get('external_order_id', ''))
                and not re.search(r'\d[Ee][+-]\d', row.data['external_order_id'])):
            continue
        if 'fee_item' in changed and issue == '费用项目为空，需核对原账单':
            continue
        issues.append(issue)
    return issues


def refresh_preview(user, job, rows):
    """Validate the whole effective preview, using bounded queries, no fee writes."""
    stores = {x.pk: x for x in StoreMaster.objects.filter(tenant=user.tenant).select_related('platform')}
    warehouses = {x.pk: x for x in WarehouseMaster.objects.filter(tenant=user.tenant)}
    countries = set(CountrySiteMaster.objects.filter(tenant=user.tenant).values_list('country_code', flat=True))
    edits = job.overrides.get(EDIT_KEY, {})
    conflicts, seen = [], set()
    for row in rows:
        key = source_key(row.source, row.data)
        row.data = deepcopy(row.source['original_data'])
        correction = edits.get(key)
        row.source.pop('correction', None)
        row.source.pop('correction_conflict', None)
        if correction:
            seen.add(key)
            if correction['signature'] != signature(row.source):
                conflicts.append(row.number)
                row.source['correction_conflict'] = True
            else:
                row.data.update(correction['changes'])
                row.source['correction'] = correction
    lookup = LocalOrderLookup(user, [(row.data, row.source) for row in rows])
    for row in rows:
        apply_match(lookup, row.data, row.source)
    orders = order_lookup(user, rows)
    imported_sources = provenance_conflicts(user, job, rows)
    keys = [hash_value([r.data.get(k) for k in IDENTITY_FIELDS]) for r in rows]
    duplicates = Counter(keys)
    existing = {}
    unique_keys = list(set(keys))
    for offset in range(0, len(unique_keys), 500):
        existing.update({x.business_key: x for x in WarehouseFee.objects.filter(tenant=user.tenant,
            business_key__in=unique_keys[offset:offset + 500]).only('business_key', 'content_hash', 'status')})
    totals, order_totals, other_totals, original_other = [defaultdict(Decimal) for _ in range(4)]
    counts, unresolved = Counter(), {'stores': Counter(), 'warehouses': Counter()}
    for row in rows:
        try:
            amount = Decimal(row.data.get('amount') or '0')
            if amount.is_finite() and row.data.get('currency'):
                totals[row.data['currency']] += amount
                if row.data['kind'] == 'order':
                    order_totals[row.data['currency']] += amount
                else:
                    other_totals[row.data['currency']] += amount
            original = row.source['original_data']
            if original['kind'] == 'other' and original.get('amount') and original.get('currency'):
                original_other[original['currency']] += Decimal(original['amount'])
        except InvalidOperation:
            pass
    invoice_currency = job.summary.get('currency') or (next(iter(order_totals)) if len(order_totals) == 1 else '')
    expected = job.summary.get('order_bill_total')
    difference = order_totals.get(invoice_currency, Decimal(0)) - Decimal(expected) if expected is not None else None
    for row, key in zip(rows, keys):
        data, source = row.data, row.source
        changed = source.get('correction', {}).get('changes', {})
        errors = corrected_issues(row, changed)
        match_error = apply_match(lookup, data, source)
        if match_error:
            errors.append(match_error)
        if row.number in conflicts:
            errors.append('原始行内容已变化，人工修正未套用，请恢复原始值后重新核对')
        if data['country'] not in countries:
            errors.append('当前租户缺少对应国家站点档案')
        serializer = FeeInput(data=data)
        if not serializer.is_valid():
            errors.append(str(serializer.errors))
        invoice = job.summary.get('settlement') or {}
        if invoice.get('valid') and data.get('currency') != invoice['currency']:
            errors.append('明细登记币种与业务结算清单不一致，原币金额仅作明细依据')
        warehouse = warehouses.get(data.get('warehouse_id'))
        store = stores.get(data.get('store_id'))
        if not warehouse or warehouse.country_code != data['country']:
            errors.append('仓库不存在或国家不一致，请选择本账单系统仓库')
            unresolved['warehouses'][source.get('raw_warehouse') or ''] += 1
        if data['kind'] == 'order':
            if not store or store.country_code != data['country']:
                errors.append('店铺不存在或国家不一致，请选择本账单系统店铺')
                unresolved['stores'][source.get('raw_store') or ''] += 1
            else:
                platform = next((x for x in ['shopee', 'tiktok', 'lazada'] if x in source.get('raw_platform', '').lower()), '')
                if platform and store.platform.platform_type != platform:
                    errors.append('系统店铺平台与原账单平台不一致')
                effective_platform = platform or store.platform.platform_type
                local_stores = {s for s, _ in orders.get(data.get('external_order_id'), [])
                                if s in stores and stores[s].country_code == data['country']
                                and stores[s].platform.platform_type == effective_platform}
                if local_stores and store.pk not in local_stores:
                    errors.append('平台订单号与所选店铺归属矛盾，请核对订单')
            if not job.summary.get('settlement') and difference is not None and (abs(difference) > Decimal('0.000001') or len(order_totals) != 1 or data.get('currency') != invoice_currency):
                errors.append(f'修正后订单明细与账单汇总差额{difference:.6f} {invoice_currency}，或结算币种不一致')
        elif not job.summary.get('settlement') and original_other and other_totals != original_other:
            errors.append('修正后其他费用分币种合计与原账单明细不一致，请核对金额和币种')
        if duplicates[key] > 1:
            errors.append('修正后同一费用重复，不能重复导入')
        if row.number in imported_sources:
            errors.append('原账单该行已有导入记录，不能通过修改归属或费用项目重复新增')
        if key in existing:
            fee = existing[key]
            if not serializer.is_valid() or fee.status == 'void' or fee.content_hash != hash_value(serializer.validated_data):
                errors.append('该费用已登记但内容不同或已作废，请核对原记录，不重复新增')
        row.error = '；'.join(dict.fromkeys(errors))
        row.status = 'error' if errors else 'valid'
        counts[row.status] += 1
        counts[data['kind']] += 1
    job.summary.update(corrected_totals=[{'currency': k, 'amount': f'{v:.6f}'} for k, v in sorted(totals.items())],
        corrected_order_difference=f'{difference:.6f}' if difference is not None else None,
        counts=dict(counts), unresolved={group: [{'name': name, 'count': count} for name, count in values.most_common(200)] for group, values in unresolved.items()})
    invoice = job.summary.get('settlement') or {}
    if invoice.get('valid'):
        job.summary['corrected_other_difference'] = f"{Decimal(invoice['other_total']) - other_totals[invoice['currency']]:.6f}"
    missing = set(edits) - seen
    job.summary['correction_warning'] = '部分人工修正无法对应原始行，请核对后再导入。' if missing or conflicts else ''


def ensure_originals(job, rows):
    """Older previews have no baseline metadata. Recover it from the retained file."""
    if all('original_data' in row.source for row in rows):
        return
    from .warehouse_bill_parser import parse_bill
    from .warehouse_bill_uploads import source_path
    import hashlib
    with source_path(job).open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != job.file_hash:
            raise ValidationError('原账单文件校验失败，不能编辑。')
    facts, _ = parse_bill(source_path(job), job.file_name, job.overrides)
    by_source = {(x['sheet'], x['row'], x['reference'], x['kind']): x for x in facts}
    for row in rows:
        if 'original_data' in row.source:
            continue
        fact = by_source.get((row.source['sheet'], row.source['row'], row.data['reference'], row.data['kind']))
        if not fact:
            raise ValidationError('原始行无法对应，请重新解析后再编辑。')
        row.source.update(original_data=deepcopy(row.data), parser_issues=fact['issues'])


@transaction.atomic
def edit_rows(user, pk, payload):
    from .warehouse_bill_uploads import owned_job
    owned_job(user, pk)  # Ownership, tenant and full import scope are mandatory for edits too.
    if set(payload) - {'operation', 'version', 'rows', 'reason'}:
        raise ValidationError('包含不支持的编辑字段。')
    job = WarehouseBillUpload.objects.select_for_update().get(pk=pk)
    if type(payload.get('version')) is not int or job.version != payload['version'] or job.status != 'ready':
        raise ValidationError('预览已变化或当前状态不可编辑，请刷新后核对。')
    if job.rows.filter(status__in=['created', 'existing']).exists():
        raise ValidationError('此账单已有导入结果，请在处理费草稿中处理，不修改原账单预览。')
    entries, reason = payload.get('rows'), payload.get('reason', '')
    if not isinstance(entries, list) or not 1 <= len(entries) <= 100:
        raise ValidationError('请明确选择1至100条记录。')
    if not isinstance(reason, str) or len(reason) > 500:
        raise ValidationError('修改原因须为不超过500字的文本。')
    restore = payload['operation'] == 'restore'
    fields, numbers = {}, set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) - {'number', 'changes'} or type(entry.get('number')) is not int or entry['number'] in numbers:
            raise ValidationError('编辑行号无效或重复。')
        numbers.add(entry['number'])
        changes = entry.get('changes', {})
        if not isinstance(changes, dict) or set(changes) - EDIT_FIELDS or (not changes and not restore) or (restore and changes):
            raise ValidationError('只允许修改店铺、仓库、订单号、费用项目、金额、币种、日期和备注。')
        if len(entries) > 1 and set(changes) - {'store_id', 'warehouse_id', 'fee_item'}:
            raise ValidationError('批量修正只支持系统店铺、系统仓库和费用项目。')
        if (restore or len(entries) > 1 or set(changes) & REASON_FIELDS) and not reason.strip():
            raise ValidationError('修改金额、币种或归属，以及恢复原始值时，请填写修改原因。')
        checked = {}
        for name, value in changes.items():
            if name == 'external_order_id' and (not isinstance(value, str) or re.search(r'\d[Ee][+-]\d', value)):
                raise ValidationError('平台订单号必须填写完整文本，不能使用科学计数法。')
            if name == 'occurred_on' and value is not None and (not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value)):
                raise ValidationError('发生日期须按YYYY-MM-DD填写。')
            field = serializers.DateField(input_formats=['%Y-%m-%d'], allow_null=True) if name == 'occurred_on' else FeeInput().fields[name]
            checked[name] = plain(field.run_validation(value))
        fields[entry['number']] = checked
    rows = list(job.rows.order_by('number'))
    before_rows = {row.pk: (row.data, dict(row.source), row.status, row.error) for row in rows}
    if numbers - {r.number for r in rows}:
        raise ValidationError('所选记录不存在于当前账单。')
    ensure_originals(job, rows)
    edits = deepcopy(job.overrides.get(EDIT_KEY, {}))
    events = []
    now = timezone.now().isoformat()
    for row in rows:
        if row.number not in numbers:
            continue
        changes = fields[row.number]
        for name, model in [('store_id', StoreMaster), ('warehouse_id', WarehouseMaster)]:
            if name in changes and changes[name] is not None and not model.objects.filter(
                    tenant=user.tenant, pk=changes[name], country_code=row.data['country']).exists():
                raise ValidationError('系统店铺或仓库不存在、不属于当前租户或国家不一致。')
        if row.data['kind'] == 'other' and (changes.get('store_id') or changes.get('external_order_id')):
            raise ValidationError('仓库其他处理费归属国家，不能填写店铺或平台订单号。')
        key = source_key(row.source, row.data)
        before = deepcopy(row.data)
        if restore:
            edits.pop(key, None)
        else:
            after = {**row.data, **changes}
            delta = {name: after[name] for name in EDIT_FIELDS if after.get(name) != row.source['original_data'].get(name)}
            if delta:
                edits[key] = {'changes': delta, 'signature': signature(row.source), 'actor': user.pk, 'at': now, 'reason': reason.strip()}
            else:
                edits.pop(key, None)
        events.append((row, before))
    job.overrides = {**job.overrides, EDIT_KEY: edits}
    refresh_preview(user, job, rows)
    modified = [row for row in rows if before_rows[row.pk] != (row.data, row.source, row.status, row.error)]
    type(rows[0]).objects.bulk_update(modified, ['data', 'source', 'status', 'error'], batch_size=500)
    for row, before in events:
        FinanceAuditLog.objects.create(tenant=user.tenant, actor=user, object_type='warehouse_bill_row',
            object_id=audit_id(job, row), action='restore' if restore else 'edit',
            masked_detail={'number': row.number, 'source': {'sheet': row.source['sheet'], 'row': row.source['row']},
                           'before': before, 'after': row.data, 'reason': reason.strip()})
    job.version += 1
    job.save(update_fields=['overrides', 'summary', 'version', 'updated_at'])
    return job
