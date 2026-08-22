"""Manage short-lived local SC-SUPPLY-FLOW UAT credentials."""

import json
import sys
from decimal import Decimal, InvalidOperation

from django.core.management.base import BaseCommand, CommandError

from apps.purchasing.uat_data import DATA_VERSION, TENANT_CODES, make_context, validate_local_database
from apps.purchasing.uat_credentials import (
    CredentialToolError,
    activate_credentials,
    revoke_credentials,
    status_credentials,
)


class Command(BaseCommand):
    help = "Dry-run or atomically activate/revoke/status exact local SC-UAT credential leases."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=("activate", "revoke", "status"))
        parser.add_argument("--environment", default="")
        parser.add_argument("--database-name", default="")
        parser.add_argument("--data-version", default=DATA_VERSION)
        parser.add_argument("--payload", default="fixture-v1")
        parser.add_argument("--confirm-local", action="store_true")
        parser.add_argument("--allow-inmemory-test", action="store_true")
        parser.add_argument("--username", action="append", dest="usernames")
        parser.add_argument("--tenant-code", choices=TENANT_CODES, default="SC-UAT-A")
        parser.add_argument("--all-allowed", action="store_true")
        parser.add_argument("--duration-hours", default="8")
        parser.add_argument("--apply", action="store_true", help="Commit a mutation; default is a dry-run.")
        parser.add_argument("--json", action="store_true", dest="as_json")

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
            if action == "activate" and options.get("apply") and options.get("as_json"):
                raise CredentialToolError("Activation delivery cannot be combined with JSON output.")
            if action == "activate":
                duration = _parse_duration(options.get("duration_hours"))
                sink = self._interactive_sink() if options.get("apply") else None
                result = activate_credentials(
                    context,
                    options.get("usernames"),
                    tenant_code=options.get("tenant_code"),
                    all_allowed=options.get("all_allowed", False),
                    duration_hours=duration,
                    apply=options.get("apply", False),
                    secret_sink=sink,
                )
            elif action == "revoke":
                result = revoke_credentials(
                    context,
                    options.get("usernames"),
                    tenant_code=options.get("tenant_code"),
                    all_allowed=options.get("all_allowed", False),
                    apply=options.get("apply", False),
                )
            else:
                result = status_credentials(
                    context,
                    options.get("usernames"),
                    tenant_code=options.get("tenant_code"),
                    all_allowed=options.get("all_allowed", False),
                )
        except CredentialToolError as exc:
            raise CommandError(str(exc)) from exc
        except Exception as exc:
            # Do not reflect exception details from a secret sink or password
            # validator into command output.
            raise CommandError("UAT credential operation failed safely; no secret was recorded.") from exc
        output = json.dumps(result, ensure_ascii=False, sort_keys=True, default=str)
        if options.get("as_json"):
            self.stdout.write(output)
        else:
            self.stdout.write(self.style.SUCCESS(output))

    def _interactive_sink(self):
        if not sys.stdin.isatty() or not self.stdout.isatty():
            raise CredentialToolError("Activation requires an interactive terminal for one-time delivery.")

        def sink(credentials):
            self.stderr.write("One-time UAT credentials; do not save or repeat this display:")
            for username, password in credentials:
                self.stderr.write(f"{username}: {password}")

        return sink


def _parse_duration(raw) -> Decimal:
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        raise CredentialToolError("Credential duration must be a positive number of hours.") from exc
    return value
