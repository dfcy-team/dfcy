from django.core.management.base import BaseCommand, CommandError

from apps.accounts.miniapp_auth import digest_miniapp_subject
from apps.accounts.models import CustomUser, MiniAppIdentity


class Command(BaseCommand):
    help = "Bind a hashed Mini Program provider subject to an existing non-RPA user."

    def add_arguments(self, parser):
        parser.add_argument("--username", required=True)
        parser.add_argument("--subject", required=True)
        parser.add_argument(
            "--provider",
            default=MiniAppIdentity.Provider.WECHAT,
            choices=[value for value, _label in MiniAppIdentity.Provider.choices],
        )

    def handle(self, *args, **options):
        try:
            user = CustomUser.objects.get(username=options["username"], is_active=True)
        except CustomUser.DoesNotExist as exc:
            raise CommandError("Active user does not exist.") from exc
        if user.user_type == CustomUser.UserType.RPA:
            raise CommandError("RPA users cannot be bound to a Mini Program identity.")

        digest = digest_miniapp_subject(options["provider"], options["subject"])
        identity, created = MiniAppIdentity.objects.update_or_create(
            provider=options["provider"],
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
