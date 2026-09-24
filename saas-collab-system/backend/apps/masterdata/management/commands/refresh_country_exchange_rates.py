from django.core.management.base import BaseCommand

from apps.masterdata.exchange_rates import refresh_country_exchange_rates


class Command(BaseCommand):
    help = "Refresh cached CNY reference rates for country archives."

    def handle(self, *args, **options):
        result = refresh_country_exchange_rates()
        self.stdout.write(self.style.SUCCESS(
            f"exchange rates refreshed: updated={result['updated']} missing={len(result['missing'])} date={result['date']} source={result['source']}"
        ))
