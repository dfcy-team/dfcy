"""Read-only candidate check; never fake migrations or edit production state."""
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.db.migrations.recorder import MigrationRecorder


class Command(BaseCommand):
    help = "Block a candidate whose influencer migration sources omit already-applied hotfix migrations."

    def handle(self, *args, **options):
        loader = MigrationLoader(connection, ignore_no_migrations=True)
        applied = MigrationRecorder(connection).applied_migrations()
        missing = sorted(name for app, name in applied if app == 'influencers' and (app, name) not in loader.disk_migrations)
        if missing:
            raise CommandError('Candidate omits applied influencer migrations: ' + ', '.join(missing))
        loader.check_consistent_history(connection)
        self.stdout.write(self.style.SUCCESS('Influencer migration compatibility passed (read-only).'))
