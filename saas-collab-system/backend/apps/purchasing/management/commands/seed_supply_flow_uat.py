"""Controlled SC-SUPPLY-FLOW-UAT-1 synthetic data command."""

import json

from django.core.management.base import BaseCommand, CommandError

from apps.purchasing.uat_data import (
    DATA_VERSION,
    TENANT_CODES,
    UATDataError,
    check_fixture,
    cleanup_fixture,
    generate_fixture,
    make_context,
    validate_local_database,
)


class Command(BaseCommand):
    help = "Generate, self-check, or deactivate the local SC-SUPPLY-FLOW-UAT-1 synthetic fixture."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("generate", "check", "cleanup"))
        parser.add_argument("--environment", default="", help="Must be exactly local.")
        parser.add_argument("--database-name", default="", help="Must exactly match the loaded local database name.")
        parser.add_argument("--data-version", default=DATA_VERSION)
        parser.add_argument("--payload", default="fixture-v1", help="Deterministic fixture payload label.")
        parser.add_argument("--confirm-local", action="store_true", help="Acknowledge that this is a local UAT database.")
        parser.add_argument("--allow-inmemory-test", action="store_true", help="Only for isolated automated tests using in-memory SQLite.")
        parser.add_argument("--tenant-code", action="append", choices=TENANT_CODES, dest="tenant_codes", help="Cleanup one exact UAT tenant; repeatable.")
        parser.add_argument("--json", action="store_true", dest="as_json", help="Emit one machine-readable JSON result.")

    def handle(self, *args, **options):
        try:
            validate_local_database(
                environment=options.get("environment"),
                database_name=options.get("database_name"),
                confirm_local=options.get("confirm_local", False),
                allow_inmemory_test=options.get("allow_inmemory_test", False),
            )
            context = make_context(options.get("data_version"), options.get("payload"))
            action = options["action"]
            if action == "generate":
                result = generate_fixture(context)
            elif action == "check":
                result = check_fixture(context)
            else:
                result = cleanup_fixture(context, tuple(options.get("tenant_codes") or TENANT_CODES))
        except UATDataError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            # Do not hide a domain failure, but keep command output free from
            # credentials or connection details.  Django will still log the
            # traceback when the caller explicitly requests --traceback.
            if isinstance(exc, CommandError):
                raise
            raise CommandError(f"SC-UAT operation failed safely: {exc}") from exc
        output = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        if options.get("as_json"):
            self.stdout.write(output)
        else:
            self.stdout.write(self.style.SUCCESS(output))
