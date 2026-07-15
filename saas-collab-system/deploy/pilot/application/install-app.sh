#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.pilot"
compose_file="$script_dir/docker-compose.pilot-app.yml"

if [ ! -f "$env_file" ]; then
  echo "Missing $env_file. Copy env.pilot.example and obtain real values from the approved secret store." >&2
  exit 1
fi

if grep -Eq 'change-me|example\.internal' "$env_file"; then
  echo "Placeholder values remain in $env_file. Set host addresses and approved secrets before installation." >&2
  exit 1
fi

chmod 600 "$env_file"

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" build backend frontend
docker compose --env-file "$env_file" -f "$compose_file" up -d redis
docker compose --env-file "$env_file" -f "$compose_file" run --rm migrate
docker compose --env-file "$env_file" -f "$compose_file" up -d backend celery celery-beat frontend
docker compose --env-file "$env_file" -f "$compose_file" ps
