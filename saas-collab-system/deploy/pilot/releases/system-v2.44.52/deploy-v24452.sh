#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib-v24452.sh
. "$release_dir/lib-v24452.sh"

fail() {
  echo "V2.44.52 deployment blocked: $*" >&2
  exit 1
}

case "${1:-}" in
  "") ;;
  --precheck-only) export PRECHECK_ONLY=1 ;;
  *) fail "usage: $0 [--precheck-only]" ;;
esac

ensure_evidence_dir
read_candidate_file

# Preflight is read-only and must pass while the mixed V2.44.50/V2.44.51
# runtime is still in place.
"$release_dir/preflight-v24452.sh" > "$evidence_dir/preflight-v24452.txt"
load_compose_chain
cd "$app_dir"

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$evidence_dir/pre-switch-containers.txt"
for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1 application-custody-sidecar-1 application-redis-1; do
  docker inspect "$container" --format '{{.Name}}|{{.Id}}|{{.Config.Image}}|{{.Image}}|{{.State.Status}}' \
    >> "$evidence_dir/pre-switch-runtime-images.txt" 2>/dev/null || fail "baseline container is missing: $container"
done
"${compose[@]}" config --images > "$evidence_dir/compose-images.txt"

# Build complete, reproducible application images from the reviewed source
# checkout. The custody sidecar is deliberately not built in this release.
docker build --pull=false --build-arg "RELEASE_REVISION=$candidate" \
  -f "$release_dir/Dockerfile.backend" -t saas-collab-backend:v2.44.52 "$source_dir" \
  > "$evidence_dir/backend-build.stdout" 2> "$evidence_dir/backend-build.stderr"
docker build --pull=false --build-arg "RELEASE_REVISION=$candidate" \
  -f "$release_dir/Dockerfile.frontend" -t saas-collab-frontend:v2.44.52 "$source_dir" \
  > "$evidence_dir/frontend-build.stdout" 2> "$evidence_dir/frontend-build.stderr"

for image in saas-collab-backend:v2.44.52 saas-collab-frontend:v2.44.52; do
  [ "$(image_version "$image")" = 2.44.52 ] || fail "$image OCI version label is incorrect."
  [ "$(image_revision "$image")" = "$candidate" ] || fail "$image OCI revision label does not match candidate."
  docker image inspect "$image" --format '{{.RepoTags}}|{{.Id}}|{{index .Config.Labels "org.opencontainers.image.version"}}|{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    >> "$evidence_dir/built-images.txt"
done
check_running_image application-custody-sidecar-1 saas-collab-custody:v2.44.50 2.44.50

# Candidate tests run before the first application container switch and use an
# isolated SQLite database. They never contact the production DB or platforms.
"${compose[@]}" run --rm --no-deps \
  -e DJANGO_SETTINGS_MODULE=config.settings.dev \
  -e DB_ENGINE=django.db.backends.sqlite3 \
  -e DB_NAME=/tmp/v24452-predeploy.sqlite3 \
  -e DB_USER= -e DB_PASSWORD= -e DB_HOST= -e DB_PORT= \
  --entrypoint pytest backend -q \
  tests/test_subject_api_access.py \
  tests/test_ui_p2_system_masterdata.py \
  tests/test_shopee_callback_repair_command.py \
  tests/test_shopee_production_oauth_readiness.py \
  > "$evidence_dir/predeploy-backend-tests.txt" 2>&1 \
  || fail "candidate backend tests failed before deployment."

if [ "${PRECHECK_ONLY:-0}" = 1 ]; then
  "$release_dir/migrate-v24452.sh" --plan-only > "$evidence_dir/migration-plan-check.txt"
  echo "V2.44.52 PREDEPLOY_CHECK=PASS candidate=$candidate migration=masterdata.0009_warehouse_service_platform"
  exit 0
fi

# This performs the only production schema operation in the package. It first
# proves the plan and creates a gzip+SHA256 backup using the application DB
# account from .env.pilot, then executes only masterdata.0009.
"$release_dir/migrate-v24452.sh"

# Do not recreate a healthy custody sidecar. If it is absent, start exactly
# that service and wait for its health gate before replacing workers.
sidecar_state=$(runtime_state application-custody-sidecar-1)
sidecar_health=$(docker inspect application-custody-sidecar-1 --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true)
if [ "$sidecar_state" != running ] || [ "$sidecar_health" != healthy ]; then
  [ "$sidecar_state" = "" ] || [ "$sidecar_state" = exited ] || fail "existing custody sidecar is not healthy; refusing an automatic restart."
  "${compose[@]}" up -d --no-deps custody-sidecar > "$evidence_dir/custody-start.stdout" 2> "$evidence_dir/custody-start.stderr" \
    || fail "custody sidecar could not be started."
  for attempt in $(seq 1 45); do
    sidecar_state=$(runtime_state application-custody-sidecar-1)
    sidecar_health=$(docker inspect application-custody-sidecar-1 --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true)
    if [ "$sidecar_state" = running ] && [ "$sidecar_health" = healthy ]; then break; fi
    [ "$attempt" -lt 45 ] || fail "custody sidecar did not become healthy."
    sleep 2
  done
fi

"${compose[@]}" up -d --no-deps backend celery celery-beat frontend \
  > "$evidence_dir/application-switch.stdout" 2> "$evidence_dir/application-switch.stderr" \
  || fail "application containers could not be switched."
for attempt in $(seq 1 45); do
  ready=1
  for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1; do
    [ "$(runtime_state "$container")" = running ] || ready=0
  done
  [ "$ready" = 1 ] && break
  [ "$attempt" -lt 45 ] || fail "one or more V2.44.52 application containers did not start."
  sleep 2
done

if [ -n "$(docker ps -q --filter name=application-migrate-1 2>/dev/null || true)" ]; then
  fail "migration service is unexpectedly running after the explicit migration."
fi

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$evidence_dir/post-switch-containers.txt"
"$release_dir/verify-v24452.sh"
printf 'DEPLOYMENT_VALIDATION=PASS\nDATABASE_MIGRATION=masterdata.0009_warehouse_service_platform\nRELEASE_REVISION=%s\n' "$candidate" \
  > "$evidence_dir/deployment-status.txt"
chmod 600 "$evidence_dir/deployment-status.txt"
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$evidence_dir/deploy-finished-at-utc.txt"
echo "V2.44.52 DEPLOYMENT_VALIDATION=PASS candidate=$candidate migration=masterdata.0009_warehouse_service_platform custody=2.44.50:healthy"
