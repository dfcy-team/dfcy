#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application
env_file="$app_dir/.env.pilot"
config_csv=$(docker inspect application-frontend-1 --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}')
IFS=',' read -r -a config_files <<< "$config_csv"
compose=(docker compose --project-name application --env-file "$env_file")
for path in "${config_files[@]}"; do compose+=(-f "$path"); done
compose+=(-f "$release_dir/docker-compose.rollback.yml")
cd "$app_dir"
"${compose[@]}" up -d --no-deps backend celery celery-beat frontend
echo "V2.44.54 application rollback to V2.44.53 completed; no database rollback was required."
