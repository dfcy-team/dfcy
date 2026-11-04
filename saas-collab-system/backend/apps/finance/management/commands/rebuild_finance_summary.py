from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import CustomUser
from apps.finance.summary_service import dataset_for
from apps.finance.summary_rebuild import rebuild


class Command(BaseCommand):
    help = '从SaaS数据库重新生成财务汇总；不调用平台接口，不重复入账。'

    def add_arguments(self, parser):
        parser.add_argument('--actor', required=True)

    def handle(self, *args, **options):
        actor = CustomUser.objects.get(username=options['actor'], is_active=True)
        previous = dataset_for(actor)
        dataset = rebuild(previous, actor, previous.accounting_state.revision)
        if dataset is None:
            raise CommandError('批次或设置已变化，未切换，请重试。')
        self.stdout.write('已从SaaS数据库生成批次 %s；各级核对 %s 项通过。' % (
            dataset.pk, dataset.metadata['reconciliation']['checks']))
