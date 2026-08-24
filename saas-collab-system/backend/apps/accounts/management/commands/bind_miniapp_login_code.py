import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.accounts.miniapp_auth import digest_miniapp_subject, exchange_login_code
from apps.accounts.models import CustomUser, MiniAppIdentity
from apps.common.exceptions import ContractViolation


class Command(BaseCommand):
    help = (
        "Exchange a Mini Program one-time login code from stdin and bind only "
        "its hashed provider identity to an existing non-RPA user."
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument(
            "--code-stdin",
            action="store_true",
            required=True,
            help="Read the one-time login code from stdin without echoing it.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        code = sys.stdin.read(513).strip()
        if not code or len(code) > 512:
            raise CommandError("A valid one-time login code is required on stdin.")

        try:
            user = CustomUser.objects.select_for_update().get(
                username=options["username"],
                is_active=True,
            )
        except CustomUser.DoesNotExist as exc:
            raise CommandError("Active user does not exist.") from exc
        if user.user_type == CustomUser.UserType.RPA:
            raise CommandError("RPA users cannot be bound to a Mini Program identity.")

        try:
            provider, subject = exchange_login_code(code)
        except ContractViolation as exc:
            raise CommandError(str(exc.detail)) from exc
        finally:
            code = ""

        digest = digest_miniapp_subject(provider, subject)
        subject = ""
        identity, created = MiniAppIdentity.objects.update_or_create(
            provider=provider,
            subject_digest=digest,
            defaults={
                "user": user,
                "status": MiniAppIdentity.Status.ACTIVE,
            },
        )
        action = "created" if created else "updated"
        self.stdout.write(
            self.style.SUCCESS(
                f"Mini Program identity {action}: provider={identity.provider}, "
                f"user={user.username}, digest={digest[:12]}..."
            )
        )
