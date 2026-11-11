import json
from pathlib import Path
import re

from django.core.management.base import BaseCommand, CommandError
from apps.demo_sync.shared_readiness import SharedReadinessError, inspect_shared_snapshot


class Command(BaseCommand):
    help = 'Read-only acceptance of a maintenance-held, administrator-only shared Demo snapshot.'

    def add_arguments(self, parser):
        parser.add_argument('--bundle', type=Path, required=True)
        parser.add_argument('--tenant-id', type=int, required=True)
        parser.add_argument('--manifest-sha256', required=True)
        parser.add_argument('--admin-id', type=int, action='append', required=True)

    def handle(self, *args, **options):
        digest, admins = options['manifest_sha256'], options['admin_id']
        if (not re.fullmatch('[0-9a-f]{64}', digest) or options['tenant_id'] <= 0
                or any(v <= 0 for v in admins) or len(set(admins)) != len(admins)):
            raise CommandError('REVIEW_ARGUMENT_INVALID')
        try:
            result = inspect_shared_snapshot(options['bundle'], options['tenant_id'], digest, admins)
        except SharedReadinessError as exc:
            raise CommandError(str(exc)) from None
        except Exception:
            raise CommandError('SHARED_ACCEPTANCE_CHECK_FAILED') from None
        self.stdout.write(json.dumps(result, sort_keys=True))
        if result['errors']:
            raise CommandError('SHARED_SNAPSHOT_REJECTED')
