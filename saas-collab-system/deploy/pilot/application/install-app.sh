#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.pilot"
compose_file="$script_dir/docker-compose.pilot-app.yml"

if [ ! -f "$env_file" ]; then
  echo "Missing $env_file. Copy env.pilot.example and obtain real values from the approved secret store." >&2
  exit 1
fi

docker network inspect saas-pilot-network >/dev/null 2>&1 || {
  echo "Missing Docker network saas-pilot-network. Install the database stack first." >&2
  exit 1
}

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" build
docker compose --env-file "$env_file" -f "$compose_file" run --rm migrate
docker compose --env-file "$env_file" -f "$compose_file" up -d backend celery celery-beat
docker compose --env-file "$env_file" -f "$compose_file" ps
