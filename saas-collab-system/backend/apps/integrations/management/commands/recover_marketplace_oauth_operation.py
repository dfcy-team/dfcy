import json

from django.core.management.base import BaseCommand, CommandError

from apps.integrations.oauth_services import recover_oauth_operation


class Command(BaseCommand):
    help = "Recover a synthetic Marketplace OAuth operation using its hashed operation ID."

    def add_arguments(self, parser):
        parser.add_argument("operation_id_hash")

    def handle(self, *args, **options):
        operation_id_hash = str(options["operation_id_hash"])
        if len(operation_id_hash) != 64 or any(char not in "0123456789abcdef" for char in operation_id_hash.lower()):
            raise CommandError("operation_id_hash must be a 64-character hexadecimal hash.")
        try:
            result = recover_oauth_operation(operation_id_hash)
        except Exception as exc:
            raise CommandError("OAuth operation recovery failed.") from exc
        self.stdout.write(json.dumps(result, sort_keys=True))
