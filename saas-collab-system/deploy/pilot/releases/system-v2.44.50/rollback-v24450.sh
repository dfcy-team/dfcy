#!/usr/bin/env bash
set -euo pipefail

# Application-only rollback to the immutable V2.44.49 baseline. The custody
# data/key mounts remain for incident review; no database data or migrations
# are touched.

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=${PILOT_APP_DIR:-/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application}
env_file=${PILOT_ENV_FILE:-$app_dir/.env.pilot}
base_compose=${PILOT_BASE_COMPOSE_FILE:-$app_dir/docker-compose.pilot-app.yml}
release_chain_root=${PILOT_RELEASE_CHAIN_ROOT:-/home/dfcy01/releases}
rollback_compose=$release_dir/docker-compose.rollback.yml
evidence_dir=${PILOT_RELEASE_EVIDENCE_DIR:-$release_dir}
base_commit=61c68a59323e70dab226b5c6f441bf1bb14a00b3

fail() {
  echo "V2.44.50 rollback blocked: $*" >&2
  exit 1
}

mkdir -p "$evidence_dir"
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
for chain_file in "${compose_chain[@]}"; do
  [ -f "$chain_file" ] || fail "required V2.44.49 compose chain file is missing: $chain_file"
done
compose=(docker compose --project-name application --env-file "$env_file")
for chain_file in "${compose_chain[@]}"; do
  compose+=( -f "$chain_file" )
done
compose+=( -f "$rollback_compose" )

for image in saas-collab-backend:v2.44.49 saas-collab-frontend:v2.44.49; do
  docker image inspect "$image" >/dev/null 2>&1 || fail "baseline image is unavailable: $image"
  version=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
  revision=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$version" = 2.44.49 ] || fail "baseline image label mismatch: $image"
  [ "$revision" = "$base_commit" ] || fail "baseline image revision mismatch: $image"
done

"${compose[@]}" config --quiet
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$evidence_dir/rollback-started-at-utc.txt"
"${compose[@]}" exec -T backend python manage.py showmigrations integrations > "$evidence_dir/rollback-migrations.txt" 2>/dev/null || true

# Remove only the sidecar container. Its dedicated bind-mounted encrypted data
# and key files are not touched.
if docker inspect application-custody-sidecar-1 >/dev/null 2>&1; then
  docker rm -f application-custody-sidecar-1 >/dev/null
fi

"${compose[@]}" up -d --no-deps backend celery celery-beat frontend
for attempt in $(seq 1 45); do
  ready=1
  for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1; do
    state=$(docker inspect "$container" --format '{{.State.Status}}' 2>/dev/null || true)
    [[ "$state" == running ]] || ready=0
  done
  [[ "$ready" == 1 ]] && break
  [[ "$attempt" -lt 45 ]] || fail "baseline application containers did not start."
  sleep 2
done

[ "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = saas-collab-backend:v2.44.49 ] || fail "backend did not roll back."
[ "$(docker inspect application-celery-1 --format '{{.Config.Image}}')" = saas-collab-backend:v2.44.49 ] || fail "celery did not roll back."
[ "$(docker inspect application-celery-beat-1 --format '{{.Config.Image}}')" = saas-collab-backend:v2.44.49 ] || fail "celery-beat did not roll back."
[ "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = saas-collab-frontend:v2.44.49 ] || fail "frontend did not roll back."
[ -z "$("${compose[@]}" ps -q migrate 2>/dev/null || true)" ] || fail "migration service unexpectedly started."

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$evidence_dir/rollback-runtime.txt"
printf 'ROLLBACK_VALIDATION=PASS\nDATABASE_MIGRATION=NONE\nBASE_COMMIT=%s\n' "$base_commit" \
  > "$evidence_dir/rollback-status.txt"
echo "V2.44.50 ROLLBACK=PASS target=2.44.49 database_migration=none"
