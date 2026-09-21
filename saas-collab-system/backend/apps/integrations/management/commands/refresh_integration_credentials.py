import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from apps.integrations.automatic_refresh import refresh_due_authorizations


class Command(BaseCommand):
    help = "Refresh due approved Shopee/WMS authorizations; --watch runs only this maintenance loop."

    def add_arguments(self, parser):
        parser.add_argument("--watch", action="store_true")

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            counts = refresh_due_authorizations()
            self.stdout.write(str(counts))
            if not options["watch"]:
                return
            time.sleep(60)
