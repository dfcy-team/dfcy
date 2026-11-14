"""Private upload lifecycle and matching for original warehouse bills."""
import hashlib
import logging
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import NamedTemporaryFile
from time import monotonic

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import serializers
from rest_framework.exceptions import APIException, NotFound, PermissionDenied, ValidationError

from apps.masterdata.models import CountrySiteMaster, StoreMaster, WarehouseMaster
from .warehouse_bill_parser import CNY_ORIGINAL, parse_bill, text
from .warehouse_bill_contract import POLICY as FILE_POLICY
from .warehouse_fee_models import WarehouseBillRow, WarehouseBillUpload
from .warehouse_fee_services import CURRENCIES, FeeInput, create_fee, scope_configs
from .warehouse_bill_matching import LocalOrderLookup, apply_match

logger = logging.getLogger(__name__)
MAX_UPLOAD = 128 * 1024**2


def require_original(user):
    # An unclassified source bill may contain every store in a country. Never
    # disclose its raw rows to a partially scoped importer before classification.
    if scope_configs(user, 'import') is not None:
        raise PermissionDenied('原始账单包含未分类的多店铺数据，需要全部数据范围的处理费导入权限；受限账号仍可使用标准模板。')


class ParseOptions(serializers.Serializer):
    registration_mode = serializers.ChoiceField(choices=[CNY_ORIGINAL, FILE_POLICY], required=False)
    format_rule_id = serializers.IntegerField(min_value=1, required=False)
    warehouse_id = serializers.IntegerField(min_value=1, required=False)
    format_config = serializers.JSONField(required=False)
    country = serializers.ChoiceField(choices=['PH', 'TH', 'MY'], required=False)
    bill_month = serializers.RegexField(r'^20\d{2}-(0[1-9]|1[0-2])$', required=False)
    currency = serializers.ChoiceField(choices=CURRENCIES, required=False)
    warehouses = serializers.DictField(child=serializers.IntegerField(min_value=1), required=False, default=dict)
    stores = serializers.DictField(child=serializers.IntegerField(min_value=1), required=False, default=dict)

    def validate(self, value):
        if value.get("format_rule_id") and value.get("format_config"):
            raise ValidationError("只能选择已有规则或本批格式配置之一。")
        if "format_config" in value:
            from .warehouse_bill_formats import clean_config
            value["format_config"] = clean_config(value["format_config"])
        if value.get('registration_mode') in {CNY_ORIGINAL, FILE_POLICY} and value.get('currency', 'CNY') != 'CNY':
            raise ValidationError('原文件自动登记统一使用CNY，不进行换汇。')
        for field in ['warehouses', 'stores']:
            if len(value[field]) > 200 or any(len(k) > 191 for k in value[field]):
                raise ValidationError('每类映射最多200项，原名称最多191字。')
        return value


def options(value):
    if not isinstance(value, dict) or set(value) - set(ParseOptions().fields):
        raise ValidationError('解析选项包含不支持的字段。')
    serializer = ParseOptions(data=value)
    serializer.is_valid(raise_exception=True)
    return dict(serializer.validated_data)


def private_root():
    # Outside MEDIA_ROOT: billing workbooks must never be served as public media.
    return Path(settings.BASE_DIR) / 'var' / 'warehouse_bills'


def source_path(job):
    return private_root() / f'{job.pk}.xlsx'


def enqueue(job, operation):
    from .tasks import process_warehouse_bill
    try:
        process_warehouse_bill.apply_async(args=[str(job.pk), job.version, operation], queue='warehouse-fees', retry=False)
    except Exception:
        WarehouseBillUpload.objects.filter(pk=job.pk, version=job.version).update(
            status='failed', error='后台解析队列不可用，请启动warehouse-fees工作队列后重试。', updated_at=timezone.now())


def upload_bill(user, uploaded, supplied=None):
    require_original(user)
    parsed_options = options(supplied or {})
    if not uploaded or not uploaded.name.lower().endswith('.xlsx'):
        raise ValidationError('请选择原始xlsx仓库账单。')
    if uploaded.size > MAX_UPLOAD:
        raise ValidationError('原始账单不能超过128MB。')
    file_name = Path(uploaded.name.replace('\\', '/')).name[:191]
    root = private_root()
    root.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with NamedTemporaryFile(dir=root, suffix='.upload', delete=False) as stream:
            temporary = Path(stream.name)
            digest, size = hashlib.sha256(), 0
            for chunk in uploaded.chunks():
                size += len(chunk)
                if size > MAX_UPLOAD:
                    raise ValidationError('原始账单不能超过128MB。')
                digest.update(chunk)
                stream.write(chunk)
        with transaction.atomic():
            job, created = WarehouseBillUpload.objects.get_or_create(tenant=user.tenant, uploaded_by=user,
                file_hash=digest.hexdigest(), defaults={'file_name': file_name, 'overrides': parsed_options})
            if created:
                temporary.replace(source_path(job))
                transaction.on_commit(lambda: enqueue(job, 'parse'))
            else:
                job = WarehouseBillUpload.objects.select_for_update().get(pk=job.pk)
                if job.summary.get('settlement_active') and job.file_name != file_name:
                    raise ValidationError('此结算清单已登记，不能通过重命名作为新账单再次登记。')
                # Re-uploading a renamed source must not retain a failed preview.
                # Empty upload options do not erase previously confirmed mappings.
                updated_options = {**job.overrides, **{key: parsed_options[key] for key in (supplied or {})}}
                # A re-upload cannot silently reinterpret an existing bill's currency policy.
                if 'registration_mode' in job.overrides:
                    updated_options['registration_mode'] = job.overrides['registration_mode']
                else:
                    updated_options.pop('registration_mode', None)
                changed = job.file_name != file_name or job.overrides != updated_options
                if (job.status in {'ready', 'failed'} and (changed or job.status == 'failed')
                        and not job.rows.filter(status__in=['created', 'existing']).exists()):
                    job.file_name, job.overrides = file_name, updated_options
                    retained = {k: v for k, v in job.summary.items() if k in {
                        'settlement_active', 'settlement', 'settlement_result', 'settlement_warehouse_id'}}
                    job.status, job.error, job.summary, job.processed = 'queued', '', retained, 0
                    job.version += 1
                    job.save()
                    transaction.on_commit(lambda: enqueue(job, 'parse'))
        return job
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def owned_job(user, pk):
    require_original(user)
    job = WarehouseBillUpload.objects.filter(pk=pk, tenant=user.tenant, uploaded_by=user).first()
    if not job:
        raise NotFound('原始账单不存在或不属于当前账号。')
    # A dead worker must not leave a permanent spinner. Old deliveries are fenced
    # by the version and status check when a user explicitly retries.
    limit = 3 if job.status in {'queued', 'import_queued'} else 35
    if job.status in {'queued', 'parsing', 'import_queued', 'importing'} and job.updated_at < timezone.now() - timedelta(minutes=limit):
        WarehouseBillUpload.objects.filter(pk=pk, status=job.status, version=job.version).update(
            status='failed', error='后台任务未完成，请确认warehouse-fees工作队列后重试；已导入草稿不会重复新增。', updated_at=timezone.now())
        job.refresh_from_db()
    return job


def describe(job):
    from copy import deepcopy
    from .warehouse_bill_contract import refresh_processing_difference
    summary = deepcopy(job.summary)
    refresh_processing_difference(summary)
    if summary.get("validation"):
        summary["validation"] = {**summary["validation"], "items": summary["validation"].get("items", [])[:100]}
    return {'id': str(job.pk), 'file_name': job.file_name, 'sha256': job.file_hash, 'status': job.status,
            'version': job.version, 'summary': summary, 'error': job.error, 'processed': job.processed,
            'overrides': {k: v for k, v in job.overrides.items() if k != '_row_edits'},
            'created_at': job.created_at, 'updated_at': job.updated_at}


def request_operation(user, pk, data):
    if data.get('operation') in {'edit', 'restore'}:
        from .warehouse_bill_edits import edit_rows
        return edit_rows(user, pk, data)
    job = owned_job(user, pk)
    if data.get('operation') in {'register', 'save_drafts'} and job.overrides.get('registration_mode') == FILE_POLICY:
        allowed = {'operation', 'version', 'rows'}
        if data['operation'] == 'register': allowed |= {'coverage_confirmed', 'difference_confirmed'}
        if set(data) - allowed:
            raise ValidationError('包含不支持的登记字段。')
        from .warehouse_file_registration import confirm_rows
        return confirm_rows(user, job, data, register=data['operation'] == 'register')
    if set(data) - {'operation', 'version', 'options', 'valid_only'}:
        raise ValidationError('包含不支持的操作字段。')
    operation = data.get('operation')
    if operation not in {'parse', 'import', 'settle'} or type(data.get('version')) is not int:
        raise ValidationError('请提供有效操作和预览版本。')
    with transaction.atomic():
        from apps.tenants.models import Tenant
        if operation == 'settle':
            if job.overrides.get('registration_mode') == FILE_POLICY:
                raise ValidationError('新原文件使用固定净差额，请在工作台选择行并确认登记。')
            Tenant.objects.select_for_update().get(pk=user.tenant_id)
        job = WarehouseBillUpload.objects.select_for_update().get(pk=job.pk)
        if job.version != data['version'] or job.status not in {'ready', 'failed', 'completed'}:
            raise ValidationError('预览已变化或任务正在运行，请刷新后重试。')
        if operation == 'settle':
            from .warehouse_bill_settlement import reconcile
            reconcile(user, job.pk, activate=True)
            job.refresh_from_db()
            job.version += 1
            job.save(update_fields=['version', 'updated_at'])
            return job
        if operation == 'parse':
            if job.rows.filter(status__in=['created', 'existing']).exists():
                raise ValidationError('此账单已有导入结果，不能更改归属后再次导入。')
            corrections = job.overrides.get('_row_edits')
            mode = job.overrides.get('registration_mode')
            job.overrides = options(data.get('options', {}))
            job.overrides.pop('registration_mode', None)
            if mode:
                job.overrides['registration_mode'] = mode
            if corrections:
                job.overrides['_row_edits'] = corrections
            job.summary = {k: v for k, v in job.summary.items() if k in {
                'settlement_active', 'settlement', 'settlement_result', 'settlement_warehouse_id'}}
            job.processed = 0
        else:
            if not job.rows.exists() or not job.summary:
                raise ValidationError('请先完成解析预览。')
            if job.summary.get('correction_warning'):
                raise ValidationError('人工修正无法对应原始行，请先核对修正冲突。')
            if job.rows.filter(status='error').exists() and data.get('valid_only') is not True:
                raise ValidationError('存在待核对行，需明确选择仅导入有效记录。')
            if not job.rows.filter(status='valid').exists():
                raise ValidationError('没有待导入的有效记录。')
            job.processed = 0
        job.status = 'queued' if operation == 'parse' else 'import_queued'
        job.error = ''
        job.version += 1
        job.save()
        transaction.on_commit(lambda: enqueue(job, operation))
    return job


def normalize_rows(user, facts, overrides, file_name, file_hash, settlement=None):
    cny_original = overrides.get('registration_mode') in {CNY_ORIGINAL, FILE_POLICY}
    file_policy = overrides.get('registration_mode') == FILE_POLICY
    countries = set(CountrySiteMaster.objects.filter(tenant=user.tenant).values_list('country_code', flat=True))
    stores = list(StoreMaster.objects.filter(tenant=user.tenant).select_related('platform'))
    warehouses = list(WarehouseMaster.objects.filter(tenant=user.tenant))
    store_by_id = {s.pk: s for s in stores}
    warehouse_by_id = {w.pk: w for w in warehouses}
    store_aliases, warehouse_aliases = defaultdict(set), defaultdict(set)
    for store in stores:
        for alias in {store.code, store.name, store.platform_store_name} - {''}:
            store_aliases[store.country_code, text(alias)].add(store.pk)
    for warehouse in warehouses:
        for alias in {warehouse.code, warehouse.name, *(warehouse.legacy_codes or [])} - {''}:
            warehouse_aliases[warehouse.country_code, text(alias)].add(warehouse.pk)
    lookup = LocalOrderLookup(user, [(f, {**f, 'original_order_id': f['external_order_id'], 'lookup_numbers': cny_original}) for f in facts])
    unresolved = {'stores': Counter(), 'warehouses': Counter()}
    seen = set()

    def resolve(group, names, country, *, local=None, platform=''):
        archives = store_by_id if group == 'stores' else warehouse_by_id
        aliases = store_aliases if group == 'stores' else warehouse_aliases
        found, missing = set(), False
        for name in set(names):
            ids = set(aliases[country, name])
            if name in overrides.get(group, {}):
                ids = {overrides[group][name]}
            ids = {pk for pk in ids if pk in archives and archives[pk].country_code == country and (not platform or archives[pk].platform.platform_type == platform)}
            if not ids and not name and local and len(local) == 1:
                ids = local
            elif len(ids) > 1 and local and len(ids & local) == 1:
                ids &= local
            if len(ids) != 1:
                unresolved[group][name] += 1
                missing = True
            found.update(ids)
        if missing or len(found) != 1:
            return None
        return archives[next(iter(found))]

    for number, fact in enumerate(facts, 1):
        errors = list(fact['issues'])
        invoice_controlled = bool(settlement and settlement.get('valid') and not file_policy)
        duplicate = any('原账单订单计费重复' in issue for issue in errors)
        if invoice_controlled:
            errors = [issue for issue in errors if not issue.startswith((
                '订单明细与账单汇总差额', '其他费用明细与账单汇总差额', '原账单订单计费重复'))]
        country, raw_store, raw_wh = fact['country'], fact['raw_store'], fact['raw_warehouse']
        if country not in countries:
            errors.append('当前租户缺少对应国家站点档案')
        warehouse = resolve('warehouses', fact.get('raw_warehouses') or [raw_wh], country)
        if not warehouse:
            errors.append('仓库未唯一匹配或多仓归属冲突，请核对本账单映射')
        store = None
        data = {key: fact[key] for key in ['kind', 'country', 'bill_number', 'bill_month', 'fee_item', 'reference', 'external_order_id', 'amount', 'currency', 'occurred_on']}
        if invoice_controlled:
            if duplicate:
                data['reference'] += f':ROW:{fact["row"]}'
            evidence = fact.get('settlement_evidence') or {}
            if not cny_original and evidence.get('settlement_currency') == settlement['currency'] and evidence.get('settlement_amount'):
                data.update(amount=evidence['settlement_amount'], currency=evidence['settlement_currency'])
            if data['currency'] != settlement['currency']:
                errors.append('原币明细仅作费用依据；缺少明确结算金额，不另行登记原币费用')
            if fact['kind'] == 'other' and any(line['sheet'] == fact['sheet'] and line['row'] == fact['row']
                                            for line in settlement['lines']):
                errors = [issue for issue in errors if issue != '额外结算项目需确认分类及是否与明细重复']
        data.update(warehouse_id=warehouse.pk if warehouse else None, store_id=store.pk if store else None,
                    note=f'原账单：{file_name}；工作表：{fact["sheet"]}；行：{fact["row"]}')
        matching_source = {**fact, 'original_order_id': fact['external_order_id'], 'lookup_numbers': cny_original}
        match_error = apply_match(lookup, data, matching_source)
        if not file_policy and fact['kind'] == 'order' and matching_source.get('order_unlinked') and not data['store_id']:
            platform = next((p for p in ['shopee', 'tiktok', 'lazada'] if p in fact.get('raw_platform', '').lower()), '')
            store = resolve('stores', fact.get('raw_stores') or [raw_store], country, platform=platform)
            data['store_id'] = store.pk if store else None
        if match_error:
            errors.append(match_error)
        if not errors:
            serializer = FeeInput(data=data)
            if not serializer.is_valid():
                errors.append(str(serializer.errors))
        identity = tuple(data[k] for k in ['kind', 'country', 'warehouse_id', 'store_id', 'bill_number', 'bill_month', 'external_order_id', 'fee_item', 'reference'])
        if identity in seen:
            errors.append('归属映射后同一费用重复，不能重复导入')
        seen.add(identity)
        source = {'type': 'warehouse_original_xlsx', 'file_name': file_name, 'sha256': file_hash,
                  **{k: fact[k] for k in ['sheet', 'row', 'source_rows', 'raw_store', 'raw_stores', 'raw_warehouse', 'raw_warehouses', 'raw_platform', 'raw_amount']}}
        source.update(original_data=dict(data), parser_issues=list(fact['issues']))
        if cny_original:
            source.update(registration_mode=overrides['registration_mode'], lookup_numbers=True, registration_original_amount=fact['amount'])
        if file_policy:
            source.update(validation=fact.get('validation', []), possible_duplicate=fact.get('possible_duplicate', False))
        if invoice_controlled:
            source.update(settlement_policy=settlement['policy'], possible_duplicate=duplicate,
                          detail_amount=fact['amount'], detail_currency=fact['currency'])
        if fact.get('settlement_evidence'):
            source['settlement_evidence'] = fact['settlement_evidence']
        source.update(original_order_id=fact['external_order_id'], tracking_numbers=fact.get('tracking_numbers', []),
                      matching=matching_source['matching'], order_unlinked=bool(matching_source.get('order_unlinked')))
        yield WarehouseBillRow(number=number, data=data, source=source, error='；'.join(dict.fromkeys(errors)), status='error' if errors else 'valid')
    yield unresolved


def process_job(pk, version, operation):
    pending, running = ('queued', 'parsing') if operation == 'parse' else ('import_queued', 'importing')
    if not WarehouseBillUpload.objects.filter(pk=pk, version=version, status=pending).update(status=running, updated_at=timezone.now()):
        return
    job = WarehouseBillUpload.objects.select_related('uploaded_by__tenant').get(pk=pk)
    last_progress = 0
    def report_progress(sheet='', scanned=0, *, stage='reading', total=None):
        nonlocal last_progress
        now = monotonic()
        previous = job.summary.get('progress', {})
        if now - last_progress < 3 and previous.get('stage') == stage and previous.get('sheet') == sheet:
            return
        job.summary['progress'] = {'stage': stage, 'sheet': sheet, 'scanned': scanned, 'total': total}
        if not WarehouseBillUpload.objects.filter(pk=pk, version=version, status=running).update(
                summary=job.summary, updated_at=timezone.now()):
            raise ValueError('Job superseded')
        last_progress = now
    try:
        require_original(job.uploaded_by)
        if operation == 'parse':
            report_progress()
            with source_path(job).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != job.file_hash:
                    raise ValueError('Stored source hash mismatch')
            if job.overrides.get('registration_mode') == FILE_POLICY:
                from .warehouse_bill_formats import parse_new_bill
                facts, summary = parse_new_bill(job.uploaded_by, source_path(job), job.file_name, job.overrides, progress=report_progress)
            else:
                facts, summary = parse_bill(source_path(job), job.file_name, job.overrides, progress=report_progress)
            with source_path(job).open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != job.file_hash:
                    raise ValueError('Stored source changed during parsing')
            summary.update({k: v for k, v in job.summary.items() if k in {
                'settlement_active', 'settlement_result', 'settlement_warehouse_id'}})
            job.summary = dict(summary)
            report_progress(stage='matching', total=len(facts))
            with transaction.atomic():
                current = WarehouseBillUpload.objects.select_for_update().get(pk=pk)
                if current.version != version or current.status != running:
                    return
                current.rows.all().delete()

            def save_rows(rows, processed):
                with transaction.atomic():
                    current = WarehouseBillUpload.objects.select_for_update().get(pk=pk)
                    if current.version != version or current.status != running:
                        return False
                    WarehouseBillRow.objects.bulk_create(rows)
                    current.processed = processed
                    current.save(update_fields=['processed', 'updated_at'])
                    return True

            pending_rows = []
            counts, sums = Counter(), defaultdict(int)
            mapped_warehouses = set()
            for row in normalize_rows(job.uploaded_by, facts, job.overrides, job.file_name, job.file_hash, summary.get('settlement')):
                if isinstance(row, dict):
                    summary['unresolved'] = {k: [{'name': name, 'count': count} for name, count in v.most_common(200)] for k, v in row.items()}
                    break
                row.upload = job
                if job.overrides.get('registration_mode') == FILE_POLICY:
                    rule = summary.get('applied_rule') or {}
                    row.source.update(job_id=str(job.pk), applied_rule={k: rule.get(k) for k in ['id', 'name', 'record_version']})
                mapped_warehouses.add(row.data.get('warehouse_id'))
                counts[row.status] += 1
                counts[row.data['kind']] += 1
                if row.data['amount'] and row.data['currency']:
                    sums[row.data['currency']] += Decimal(row.data['amount'])
                pending_rows.append(row)
                if len(pending_rows) == 1000:
                    if not save_rows(pending_rows, sum(counts[k] for k in ['valid', 'error'])):
                        return
                    pending_rows = []
            if pending_rows:
                if not save_rows(pending_rows, len(facts)):
                    return
            summary.update(counts=dict(counts), totals=[{'currency': k, 'amount': str(v)} for k, v in sorted(sums.items())])
            if job.overrides.get('registration_mode') in {CNY_ORIGINAL, FILE_POLICY}:
                summary['settlement_warehouse_id'] = next(iter(mapped_warehouses)) if len(mapped_warehouses) == 1 else None
            with transaction.atomic():
                current = WarehouseBillUpload.objects.select_for_update().get(pk=pk)
                if current.version != version or current.status != running:
                    return
                current.summary = summary
                if current.overrides.get('_row_edits'):
                    from .warehouse_bill_edits import refresh_preview
                    rows = list(current.rows.order_by('number'))
                    refresh_preview(current.uploaded_by, current, rows)
                    WarehouseBillRow.objects.bulk_update(rows, ['data', 'source', 'status', 'error'], batch_size=500)
                current.status, current.processed, current.error = 'ready', len(facts), ''
                current.save(update_fields=['summary', 'status', 'processed', 'error', 'updated_at'])
        else:
            effective_rows = list(job.rows.filter(status='valid').only('data', 'source'))
            import_lookup = LocalOrderLookup(job.uploaded_by, [(r.data, r.source) for r in effective_rows])
            # Importers of the same retained file share one lock even when a
            # correction changes the business key or the destination warehouse.
            anchor = WarehouseBillUpload.objects.filter(tenant=job.tenant, file_hash=job.file_hash).order_by('created_at', 'pk').values_list('pk', flat=True).first()
            while True:
                with transaction.atomic():
                    WarehouseBillUpload.objects.select_for_update().get(pk=anchor)
                    current = WarehouseBillUpload.objects.select_for_update().get(pk=pk)
                    if current.version != version or current.status != running:
                        return
                    # Re-evaluate grants on every chunk; no stale worker authority.
                    current.uploaded_by.refresh_from_db()
                    require_original(current.uploaded_by)
                    rows = list(current.rows.filter(status='valid').order_by('number')[:100])
                    if not rows:
                        current.status = 'completed'
                        current.save(update_fields=['status', 'updated_at'])
                        break
                    from .warehouse_bill_edits import provenance_conflicts
                    source_conflicts = provenance_conflicts(current.uploaded_by, current, rows)
                    for row in rows:
                        try:
                            if row.number in source_conflicts:
                                raise ValidationError('原账单该行已有导入记录，不能通过修改归属或费用项目重复新增。')
                            checked = dict(row.data)
                            match_error = apply_match(import_lookup, checked, dict(row.source))
                            if match_error:
                                raise ValidationError(match_error)
                            if any(checked.get(k) != row.data.get(k) for k in ['store_id', 'external_order_id']):
                                raise ValidationError('本地订单关联已变化，请重新匹配后再导入。')
                            fee, created = create_fee(current.uploaded_by, row.data, action='import', source=row.source)
                            row.fee = fee
                            row.status = 'created' if created else 'existing'
                        except APIException as exc:
                            row.status, row.error = 'error', str(exc.detail)
                        row.save(update_fields=['fee', 'status', 'error'])
                    current.processed += len(rows)
                    current.save(update_fields=['processed', 'updated_at'])
    except Exception as exc:
        from .warehouse_bill_parser import BillError
        message = str(exc)[:500] if isinstance(exc, BillError) else '解析或导入未完成，请核对文件、权限及后台工作队列后重试。'
        logger.warning('Warehouse bill job failed: %s (%s)', pk, type(exc).__name__)
        WarehouseBillUpload.objects.filter(pk=pk, version=version, status=running).update(status='failed', error=message, updated_at=timezone.now())
