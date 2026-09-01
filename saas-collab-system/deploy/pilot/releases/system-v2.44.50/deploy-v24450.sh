#!/usr/bin/env bash
set -euo pipefail

# Architect-only deployment wrapper. It builds three immutable child images
# from the running V2.44.49 baseline, starts the isolated custody sidecar, and
# then replaces the application containers. It never invokes the inherited
# migrate service or any database DDL.

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=${PILOT_APP_DIR:-/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application}
env_file=${PILOT_ENV_FILE:-$app_dir/.env.pilot}
base_compose=${PILOT_BASE_COMPOSE_FILE:-$app_dir/docker-compose.pilot-app.yml}
source_dir=${PILOT_SOURCE_DIR:-/opt/saas-collab/dfcy/saas-collab-system}
release_chain_root=${PILOT_RELEASE_CHAIN_ROOT:-/home/dfcy01/releases}
evidence_dir=${PILOT_RELEASE_EVIDENCE_DIR:-$release_dir}

fail() {
  echo "V2.44.50 deployment blocked: $*" >&2
  exit 1
}

mkdir -p "$evidence_dir"
[ ! -L "$evidence_dir" ] || fail "release evidence directory must not be a symbolic link."

# Prepare ownership before read-only preflight checks. The bootstrap only
# changes modes/ownership of the explicitly configured dedicated custody paths.
"$release_dir/bootstrap-custody-v24450.sh"
"$release_dir/preflight-v24450.sh"

release_revision=$(tr -d '[:space:]' < "$release_dir/candidate-commit.txt")
compose_chain=(
  "$base_compose"
  "$release_chain_root/system-v2.44.24-build-20260814/docker-compose.yml"
  "$release_chain_root/system-v2.44.26-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.28-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.29-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.30-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.31-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.32-build-20260817/docker-compose.yml"
  "$release_chain_root/system-v2.44.33-build-20260821/docker-compose.yml"
  "$release_chain_root/system-v2.44.34-build-20260823/docker-compose.yml"
  "$release_chain_root/system-v2.44.35-build-20260823/docker-compose.yml"
  "$release_chain_root/system-v2.44.37-build-20260823/docker-compose.yml"
  "$release_chain_root/system-v2.44.38-build-20260824/docker-compose.yml"
  "$release_chain_root/architect-developer-a-v2.44.47-r2-20260828/docker-compose.v2.44.47.yml"
  "$release_chain_root/system-v2.44.48-build-20260828/docker-compose.yml"
  "$release_chain_root/system-v2.44.49-reviewed-pr59-20260831/docker-compose.yml"
)
compose=(docker compose --project-name application --env-file "$env_file")
for chain_file in "${compose_chain[@]}"; do
  compose+=( -f "$chain_file" )
done
compose+=( -f "$release_dir/docker-compose.yml" )

if [[ "${PRECHECK_ONLY:-0}" == 1 ]]; then
  echo "V2.44.50 PREDEPLOY_CHECK=PASS candidate=$release_revision database_migration=none"
  exit 0
fi

cd "$app_dir"
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$evidence_dir/deploy-started-at-utc.txt"
docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$evidence_dir/pre-switch-containers.txt"
for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1 application-redis-1; do
  docker inspect "$container" --format '{{.Name}}|{{.Id}}|{{.Config.Image}}|{{.Image}}' \
    >> "$evidence_dir/pre-switch-runtime-images.txt"
done

# Read-only schema snapshot proving that this release did not execute DDL.
# Capture it from the already-running V2.44.49 backend, before any image build.
docker exec application-backend-1 python manage.py showmigrations integrations \
  > "$evidence_dir/pre-deploy-migrations.txt"

"${compose[@]}" config --quiet
docker build --pull=false \
  --build-arg "RELEASE_REVISION=$release_revision" \
  -f "$release_dir/Dockerfile.backend" \
  -t saas-collab-backend:v2.44.50 "$source_dir" \
  > "$evidence_dir/backend-build.stdout" 2> "$evidence_dir/backend-build.stderr"
docker build --pull=false \
  --build-arg "RELEASE_REVISION=$release_revision" \
  -f "$release_dir/Dockerfile.custody" \
  -t saas-collab-custody:v2.44.50 "$source_dir" \
  > "$evidence_dir/custody-build.stdout" 2> "$evidence_dir/custody-build.stderr"
docker build --pull=false \
  --build-arg "RELEASE_REVISION=$release_revision" \
  -f "$release_dir/Dockerfile.frontend" \
  -t saas-collab-frontend:v2.44.50 "$source_dir" \
  > "$evidence_dir/frontend-build.stdout" 2> "$evidence_dir/frontend-build.stderr"

for image in saas-collab-backend:v2.44.50 saas-collab-custody:v2.44.50 saas-collab-frontend:v2.44.50; do
  docker image inspect "$image" --format '{{.RepoTags}}|{{.Id}}|{{index .Config.Labels "org.opencontainers.image.version"}}|{{index .Config.Labels "org.opencontainers.image.revision"}}' \
    >> "$evidence_dir/built-images.txt"
done

# The candidate image must pass its isolated test gates before any runtime
# container is replaced.  The backend test environment is SQLite-only and
# never points at the production database.
"${compose[@]}" run --rm --no-deps \
  -e DJANGO_SETTINGS_MODULE=config.settings.dev \
  -e DB_ENGINE=django.db.backends.sqlite3 \
  -e DB_NAME=/tmp/v24450-predeploy-tests.sqlite3 \
  -e DB_USER= -e DB_PASSWORD= -e DB_HOST= -e DB_PORT= \
  --entrypoint pytest backend -q \
  tests/test_custody_security_gate.py tests/test_integration_credential_maintenance.py tests/test_database_settings.py \
  > "$evidence_dir/predeploy-backend-tests.txt" 2>&1
# Run from writable /tmp so pytest never needs to read the inherited
# root-owned /app/pytest.ini.  PYTHONPATH keeps the explicitly copied package
# importable while preserving the sidecar's non-root UID/GID.
"${compose[@]}" run --rm --no-deps -w /tmp -e PYTHONPATH=/app \
  --entrypoint pytest custody-sidecar -c /dev/null /app/tests/test_custody_service.py \
  > "$evidence_dir/predeploy-sidecar-tests.txt" 2>&1

# Start the sidecar separately so its health gate is satisfied before workers
# can attempt credential maintenance. No host port is published.
"${compose[@]}" up -d --no-deps custody-sidecar
sidecar_id=$("${compose[@]}" ps -q custody-sidecar)
[ -n "$sidecar_id" ] || fail "custody-sidecar container was not created."
for attempt in $(seq 1 45); do
  state=$(docker inspect "$sidecar_id" --format '{{.State.Status}}' 2>/dev/null || true)
  health=$(docker inspect "$sidecar_id" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || true)
  if [[ "$state" == running && "$health" == healthy ]]; then
    break
  fi
  [[ "$attempt" -lt 45 ]] || fail "custody-sidecar did not become healthy."
  sleep 2
done

"${compose[@]}" up -d --no-deps backend celery celery-beat frontend
for attempt in $(seq 1 45); do
  ready=1
  for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1; do
    state=$(docker inspect "$container" --format '{{.State.Status}}' 2>/dev/null || true)
    [[ "$state" == running ]] || ready=0
  done
  [[ "$ready" == 1 ]] && break
  [[ "$attempt" -lt 45 ]] || fail "one or more V2.44.50 application containers did not start."
  sleep 2
done

# Compose profiles keep migrate out of the deployment graph. A pre-existing
# stopped migration container is not touched; this proves this invocation did
# not start one.
migrate_id=$("${compose[@]}" ps -q migrate 2>/dev/null || true)
[ -z "$migrate_id" ] || fail "migration service unexpectedly started."

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$evidence_dir/post-switch-containers.txt"
"$release_dir/verify-v24450.sh"
printf 'DEPLOYMENT_VALIDATION=PASS\nDATABASE_MIGRATION=NONE\nRELEASE_REVISION=%s\n' "$release_revision" \
  > "$evidence_dir/deployment-status.txt"
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$evidence_dir/deploy-finished-at-utc.txt"
echo "V2.44.50 DEPLOYMENT_VALIDATION=PASS candidate=$release_revision database_migration=none"
