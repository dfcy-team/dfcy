"""Register a reviewed HTML2 input batch in the local SaaS, without reposting sources."""
import gzip
import hashlib
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.models import CustomUser
from apps.masterdata.models import StoreMaster
from apps.finance.models import FinanceAuditLog
from apps.finance.summary_models import FinanceSummaryDataset, FinanceSummaryState
from apps.finance.summary_service import engine, private_root, source_checkpoint, require_access, unpack_values


class Command(BaseCommand):
    help = '接入已核查的本地HTML2财务批次；不改写平台、订单及仓库原始记录。'

    def add_arguments(self, parser):
        parser.add_argument('--source', required=True)
        parser.add_argument('--actor', required=True)
        parser.add_argument('--label', default='财务汇总 · 已验收HTML2批次')

    def handle(self, *args, **options):
        if settings.DATABASES['default'].get('HOST') not in {'127.0.0.1', 'localhost'}:
            raise CommandError('本命令只允许接入本地数据库。')
        actor = CustomUser.objects.get(username=options['actor'], is_active=True)
        require_access(actor, write=True)
        data = Path(options['source']).read_bytes()
        if len(data) > 180_000_000 or b'id="html2-ledger-fees"' not in data or b'id="snapshot"' not in data:
            raise CommandError('不是已验收HTML2财务文件。')
        digest = hashlib.sha256(data).hexdigest()
        root = private_root(); root.mkdir(parents=True, exist_ok=True)
        file = root / (digest + '.html.gz')
        if file.exists():
            if hashlib.sha256(gzip.decompress(file.read_bytes())).hexdigest() != digest:
                raise CommandError('已有批次文件校验失败。')
        else:
            file.write_bytes(gzip.compress(data))
        candidate = FinanceSummaryDataset(document_file=file.name, source_hash=digest)
        info = engine(candidate, {'action': 'inspect'})
        stores = {r.pk: r for r in StoreMaster.objects.filter(pk__in=set(info['rawStores']) | {r['id'] for r in info['stores']})}
        if len(stores) != len(set(info['rawStores']) | {r['id'] for r in info['stores']}) or any(r.tenant_id != actor.tenant_id for r in stores.values()):
            raise CommandError('来源店铺不属于当前租户，未接入。')
        if any(stores[r['id']].code != r['code'] for r in info['stores']):
            raise CommandError('来源店铺标识与本地SaaS不一致。')
        meta = {**info, 'store_ids': sorted(stores), 'checkpoint': source_checkpoint(list(stores)),
                'basis': '已验收财务来源批次；非实时采集；原有缺口保留待核'}
        with transaction.atomic():
            existing = FinanceSummaryDataset.objects.filter(tenant=actor.tenant, source_hash=digest).first()
            if existing:
                self.stdout.write('批次已接入：%s（未重复创建或清空调整）' % existing.pk)
                return
            previous = FinanceSummaryDataset.objects.select_for_update().filter(tenant=actor.tenant, active=True).order_by('-pk').first()
            values = previous.accounting_state.values if previous else {}
            engine(candidate, {'action': 'inspect', 'state': unpack_values(values)})
            FinanceSummaryDataset.objects.filter(tenant=actor.tenant, active=True).update(active=False)
            dataset = FinanceSummaryDataset.objects.create(tenant=actor.tenant, label=options['label'], source_hash=digest,
                document_file=file.name, metadata=meta, created_by=actor)
            FinanceSummaryState.objects.create(dataset=dataset, values=values, updated_by=actor)
            FinanceAuditLog.objects.create(tenant=actor.tenant, actor=actor, action='summary_import',
                object_type='finance_summary', object_id=str(dataset.pk), masked_detail={'source_hash': digest, 'raw_rows': info['rawRows']})
        self.stdout.write('已接入批次 %s；%s 个店铺；原始平台和订单记录写入 0。' % (dataset.pk, len(stores)))
