#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file=${SANDBOX_RUNTIME_ENV_FILE:-$script_dir/.env.sandbox}
compose_file=${SANDBOX_RUNTIME_COMPOSE_FILE:-$script_dir/docker-compose.sandbox-app.yml}

[ -f "$env_file" ] || { echo "Missing $env_file" >&2; exit 1; }

docker compose --env-file "$env_file" -f "$compose_file" run --rm backend python manage.py shell <<'PY'
from django.db import transaction

from apps.pilot.models import PilotEnvironment

with transaction.atomic():
    environment, created = PilotEnvironment.objects.get_or_create(
        code="sandbox",
        defaults={"name": "Sandbox", "status": "controlled"},
    )
    if environment.name != "Sandbox" or environment.status != "controlled":
        raise SystemExit("Existing sandbox environment has an invalid name or status; manual review required.")
    if PilotEnvironment.objects.filter(code="sandbox").count() != 1:
        raise SystemExit("Sandbox environment identity is not unique.")
    print(f"SANDBOX_ENVIRONMENT_REGISTERED=PASS created={str(created).lower()}")
PY
