#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
candidate=cb022ea3bee8a79e45800632a898afe62d54524a
app_dir=/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application
env_file="$app_dir/.env.pilot"
source_dir="$release_dir/reviewed-source/saas-collab-system"

fail() { echo "V2.44.54 blocked: $*" >&2; exit 1; }
image_label() { docker image inspect "$1" --format "{{index .Config.Labels \"$2\"}}" 2>/dev/null || true; }
runtime_image() { docker inspect "$1" --format '{{.Config.Image}}' 2>/dev/null || true; }
runtime_id() { docker inspect "$1" --format '{{.Id}}' 2>/dev/null || true; }

case "${1:-}" in
  "") precheck_only=0 ;;
  --precheck-only) precheck_only=1 ;;
  *) fail "usage: $0 [--precheck-only]" ;;
esac

[ "$(cat "$release_dir/candidate-commit.txt")" = "$candidate" ] || fail "candidate commit mismatch"
[ -f "$release_dir/v24454-source.tar.gz" ] || fail "reviewed source archive is missing"
(cd "$release_dir" && sha256sum -c source-sha256.txt >/dev/null) || fail "reviewed source archive checksum mismatch"
[ -f "$env_file" ] || fail "protected application environment is missing"
[ -f "$source_dir/backend/apps/masterdata/views.py" ] || fail "reviewed masterdata source is missing"
[ -f "$source_dir/frontend/tests/master-data-safe-delete.spec.js" ] || fail "reviewed frontend contract test is missing"
[ "$(jq -r .current_release_version /opt/saas-collab/release-control/unified/ledger/current-version.json)" = 2.44.53 ] || fail "production ledger is not V2.44.53"
[ "$(jq -r .git_commit /opt/saas-collab/release-control/unified/ledger/current-version.json)" = 37eaa4a3344be9d3a3c6897e6e4936972a429c40 ] || fail "production commit is not the approved V2.44.53 parent"
[ "$(runtime_image application-backend-1)" = saas-collab-backend:v2.44.53 ] || fail "backend baseline changed"
[ "$(runtime_image application-frontend-1)" = saas-collab-frontend:v2.44.53 ] || fail "frontend baseline changed"
[ "$(runtime_image application-custody-sidecar-1)" = saas-collab-custody:v2.44.50 ] || fail "custody baseline changed"
[ "$(image_label saas-collab-backend:v2.44.53 org.opencontainers.image.revision)" = 37eaa4a3344be9d3a3c6897e6e4936972a429c40 ] || fail "backend baseline revision changed"
[ "$(image_label saas-collab-frontend:v2.44.53 org.opencontainers.image.revision)" = 37eaa4a3344be9d3a3c6897e6e4936972a429c40 ] || fail "frontend baseline revision changed"

config_csv=$(docker inspect application-frontend-1 --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}')
IFS=',' read -r -a config_files <<< "$config_csv"
compose=(docker compose --project-name application --env-file "$env_file")
for path in "${config_files[@]}"; do [ -f "$path" ] || fail "compose file missing: $path"; compose+=(-f "$path"); done
compose+=(-f "$release_dir/docker-compose.yml")
"${compose[@]}" config --quiet >/dev/null || fail "compose configuration is invalid"

if [ "$precheck_only" = 1 ]; then
  echo "V2.44.54 PRECHECK=PASS parent=2.44.53 candidate=$candidate migration=NONE"
  exit 0
fi

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$release_dir/pre-switch-containers.txt"
: > "$release_dir/pre-switch-container-ids.txt"
for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1 application-custody-sidecar-1 application-redis-1; do
  printf '%s|%s\n' "$container" "$(runtime_id "$container")" >> "$release_dir/pre-switch-container-ids.txt"
done

docker build --pull=false --build-arg "RELEASE_REVISION=$candidate" -f "$release_dir/Dockerfile.backend" -t saas-collab-backend:v2.44.54 "$source_dir" > "$release_dir/backend-build.stdout" 2> "$release_dir/backend-build.stderr"
docker build --pull=false --build-arg "RELEASE_REVISION=$candidate" -f "$release_dir/Dockerfile.frontend" -t saas-collab-frontend:v2.44.54 "$source_dir" > "$release_dir/frontend-build.stdout" 2> "$release_dir/frontend-build.stderr"

[ "$(image_label saas-collab-backend:v2.44.54 org.opencontainers.image.version)" = 2.44.54 ] || fail "backend version label mismatch"
[ "$(image_label saas-collab-backend:v2.44.54 org.opencontainers.image.revision)" = "$candidate" ] || fail "backend revision label mismatch"
[ "$(image_label saas-collab-frontend:v2.44.54 org.opencontainers.image.version)" = 2.44.54 ] || fail "frontend version label mismatch"
[ "$(image_label saas-collab-frontend:v2.44.54 org.opencontainers.image.revision)" = "$candidate" ] || fail "frontend revision label mismatch"

docker run --rm --entrypoint pytest -e DJANGO_SETTINGS_MODULE=config.settings.dev -e DB_ENGINE=django.db.backends.sqlite3 -e DB_NAME=/tmp/v24454.sqlite3 -e DB_USER= -e DB_PASSWORD= -e DB_HOST= -e DB_PORT= saas-collab-backend:v2.44.54 -q tests/test_ui_p2_system_masterdata.py apps/influencers/tests/test_creation_boundaries.py tests/test_influencer_fulfillment.py > "$release_dir/predeploy-backend-tests.txt" 2>&1 || fail "pre-deploy masterdata and influencer regression tests failed"
docker run --rm --entrypoint python -e DJANGO_SETTINGS_MODULE=config.settings.dev -e DB_ENGINE=django.db.backends.sqlite3 -e DB_NAME=/tmp/v24454-check.sqlite3 -e DB_USER= -e DB_PASSWORD= -e DB_HOST= -e DB_PORT= saas-collab-backend:v2.44.54 manage.py makemigrations --check --dry-run > "$release_dir/predeploy-migration-check.txt" 2>&1 || fail "migration check failed"

cd "$app_dir"
"${compose[@]}" config --images > "$release_dir/compose-images.txt"
"${compose[@]}" up -d --no-deps backend celery celery-beat frontend > "$release_dir/application-switch.stdout" 2> "$release_dir/application-switch.stderr" || fail "application switch failed"

for attempt in $(seq 1 45); do
  ready=1
  for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1; do
    [ "$(docker inspect "$container" --format '{{.State.Status}}' 2>/dev/null || true)" = running ] || ready=0
  done
  [ "$ready" = 1 ] && break
  [ "$attempt" -lt 45 ] || fail "application containers did not become ready"
  sleep 2
done

"$release_dir/verify-v24454.sh"
printf 'DEPLOYMENT_VALIDATION=PASS\nDATABASE_MIGRATION=NONE\nRELEASE_REVISION=%s\n' "$candidate" > "$release_dir/deployment-status.txt"
chmod 600 "$release_dir/deployment-status.txt"
date -u +%Y-%m-%dT%H:%M:%SZ > "$release_dir/deploy-finished-at-utc.txt"
echo "V2.44.54 DEPLOYMENT_VALIDATION=PASS candidate=$candidate migration=NONE custody=unchanged redis=unchanged"
