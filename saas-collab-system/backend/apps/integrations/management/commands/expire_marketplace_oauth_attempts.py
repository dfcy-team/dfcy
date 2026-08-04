from django.core.management.base import BaseCommand

from apps.integrations.oauth_services import expire_oauth_attempts


class Command(BaseCommand):
    help = "Mark expired synthetic marketplace OAuth attempts as expired."

    def handle(self, *args, **options):
        count = expire_oauth_attempts()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} marketplace OAuth attempts."))
