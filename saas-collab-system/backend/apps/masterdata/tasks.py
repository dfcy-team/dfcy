from celery import shared_task

from .exchange_rates import refresh_country_exchange_rates


@shared_task
def refresh_country_cny_exchange_rates():
    return refresh_country_exchange_rates()
