#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.pilot"
compose_file="$script_dir/docker-compose.pilot-db.yml"

if [ ! -f "$env_file" ]; then
  echo "Missing $env_file. Copy env.pilot.example and obtain real values from the approved secret store." >&2
  exit 1
fi

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" up -d
docker compose --env-file "$env_file" -f "$compose_file" ps
