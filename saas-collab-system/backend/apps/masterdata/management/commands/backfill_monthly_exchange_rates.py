from django.core.management.base import BaseCommand, CommandError

from apps.accounts.models import CustomUser
from apps.masterdata.models import DailyExchangeRateSnapshot
from apps.masterdata.monthly_exchange_rates import (
    ExchangeRateEvidenceError, fetch_daily_rates, month_days, monthly_average_quotes, store_daily_rates,
)
from apps.finance.summary_service import require_access


class Command(BaseCommand):
    help = 'Save daily public-rate evidence for complete months; never update platform or fee records.'

    def add_arguments(self, parser):
        parser.add_argument('--username', required=True)
        parser.add_argument('--month', action='append', required=True)

    def handle(self, *args, **options):
        user = CustomUser.objects.get(username=options['username'], is_active=True)
        require_access(user, write=True)
        from django.utils import timezone
        from zoneinfo import ZoneInfo
        today = timezone.localdate(timezone=ZoneInfo('Asia/Shanghai'))
        try:
            for month in sorted(set(options['month'])):
                days = month_days(month)
                if days[-1] >= today:
                    raise CommandError('仅支持已经结束的完整自然月。')
                saved = set(DailyExchangeRateSnapshot.objects.filter(tenant=user.tenant,
                    rate_date__range=(days[0], days[-1])).values_list('rate_date', flat=True))
                for day in days:
                    if day not in saved:
                        fetched = fetch_daily_rates(day)
                        store_daily_rates(user.tenant, day, fetched['rates'], fetched['source_url'])
                    self.stdout.write(f'DAILY_FX {day} saved')
                pairs = [(country, base, target) for country, target in [('PH','PHP'), ('TH','THB'), ('MY','MYR')]
                         for base in ['CNY','USD']]
                quotes = monthly_average_quotes(user.tenant, [month], pairs)
                if len(quotes) != len(pairs):
                    raise CommandError(f'{month} 缺少必要币种，不生成完整月均汇率。')
                for key, quote in sorted(quotes.items()):
                    self.stdout.write(f"MONTHLY_FX {key} {quote['rate']} days={quote['days']}")
        except (ExchangeRateEvidenceError, ValueError) as exc:
            raise CommandError(str(exc)) from None
