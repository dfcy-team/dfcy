import json
import os
import tempfile
from pathlib import Path
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from apps.accounts.automation import validate_observations

class Command(BaseCommand):
    help = "Import sanitized system automation observations collected by a privileged operator."

    def add_arguments(self, parser):
        parser.add_argument("snapshot")

    def handle(self, *args, **options):
        target = getattr(settings, "AUTOMATION_OBSERVATIONS_FILE", "")
        if not target:
            raise CommandError("AUTOMATION_OBSERVATIONS_FILE is required")
        source = Path(options["snapshot"])
        try:
            size = source.stat().st_size
        except OSError as exc:
            raise CommandError("Cannot read observation snapshot") from exc
        if size > 131072:
            raise CommandError("Snapshot exceeds 128 KB")
        try:
            data = json.loads(source.read_text(encoding="utf-8"))
            rows = list(validate_observations(data).values())
        except (ValueError, KeyError, TypeError):
            raise CommandError("Invalid observation snapshot")
        destination = Path(target)
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(dir=destination.parent, prefix=".automation-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"tasks": rows}, stream)
            os.chmod(name, 0o600)
            os.replace(name, destination)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        self.stdout.write(f"Imported {len(rows)} observations")
