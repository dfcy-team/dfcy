from django.core.management.base import BaseCommand, CommandError
from apps.accounts.models import CustomUser
from apps.masterdata.models import CountrySiteMaster
from apps.alerts.models import InventoryWarningRun
from apps.alerts.warning_snapshot import calculate_country
class Command(BaseCommand):
    help='Build full-country warning snapshots in background.'
    def add_arguments(self,parser):
        parser.add_argument('--tenant-id',type=int,required=True);parser.add_argument('--country-code');parser.add_argument('--queued-only',action='store_true')
    def handle(self,*args,**opts):
        actor=CustomUser.objects.filter(tenant_id=opts['tenant_id'],user_type=CustomUser.UserType.INTERNAL,is_active=True,is_superuser=True).order_by('pk').first()
        if not actor:raise CommandError('No full-scope internal superuser is available.')
        countries=CountrySiteMaster.objects.filter(tenant_id=opts['tenant_id'],status='active')
        if opts['country_code']:countries=countries.filter(country_code__iexact=opts['country_code'])
        if opts['queued_only']:countries=countries.filter(pk__in=InventoryWarningRun.objects.filter(tenant_id=opts['tenant_id'],status='queued').values('country_id'))
        for country in countries.order_by('country_code'):
            queued=InventoryWarningRun.objects.filter(tenant_id=actor.tenant_id,country=country,status='queued').order_by('pk').first()
            run=calculate_country(actor,country,run=queued)
            self.stdout.write(f'{country.country_code}: {run.status}; rows={run.rows.count()}')
