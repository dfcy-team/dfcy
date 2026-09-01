#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib-v24452.sh
. "$release_dir/lib-v24452.sh"

fail() {
  echo "V2.44.52 rollback blocked: $*" >&2
  exit 1
}

ensure_evidence_dir
[ "${PILOT_RELEASE_ACTOR:-architect}" = architect ] || fail "only the architect release actor may run rollback."
[ ! -f "$release_dir/.influencers-migration.cnf" ] || fail "forbidden .influencers-migration.cnf is present."
[ ! -f "$app_dir/.influencers-migration.cnf" ] || fail "forbidden application .influencers-migration.cnf is present."
load_compose_chain

for image in saas-collab-backend:v2.44.50 saas-collab-frontend:v2.44.51 saas-collab-custody:v2.44.50; do
  docker image inspect "$image" >/dev/null 2>&1 || fail "rollback image is unavailable: $image"
done
[ "$(image_version saas-collab-backend:v2.44.50)" = 2.44.50 ] || fail "rollback backend image label is incorrect."
[ "$(image_version saas-collab-frontend:v2.44.51)" = 2.44.51 ] || fail "rollback frontend image label is incorrect."
[ "$(image_version saas-collab-custody:v2.44.50)" = 2.44.50 ] || fail "rollback custody image label is incorrect."

cd "$app_dir"
docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$evidence_dir/rollback-pre-switch-containers.txt"
"${compose[@]}" config --quiet >/dev/null 2>&1 || fail "application/rollback Compose chain is invalid."

# Keep 0009 applied. This rollback only restores application image behavior;
# it never reverses a migration, restores a database, or deletes custody data.
"${compose[@]}" exec -T backend python manage.py showmigrations masterdata \
  > "$evidence_dir/rollback-migrations.txt" 2>&1 || fail "cannot read current migration state."
grep -Eq '^\[[Xx]\][[:space:]]+0009_warehouse_service_platform' "$evidence_dir/rollback-migrations.txt" || \
  fail "masterdata.0009 is not recorded as applied; refuse an application-only rollback."

rollback_compose=("${compose[@]}" -f "$release_dir/docker-compose.rollback.yml")
"${rollback_compose[@]}" config --quiet >/dev/null 2>&1 || fail "rollback Compose override is invalid."
"${rollback_compose[@]}" up -d --no-deps backend celery celery-beat frontend \
  > "$evidence_dir/rollback-switch.stdout" 2> "$evidence_dir/rollback-switch.stderr" \
  || fail "application rollback switch failed."
for attempt in $(seq 1 45); do
  ready=1
  for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1; do
    [ "$(runtime_state "$container")" = running ] || ready=0
  done
  [ "$ready" = 1 ] && break
  [ "$attempt" -lt 45 ] || fail "rollback application containers did not start."
  sleep 2
done

check_running_image application-backend-1 saas-collab-backend:v2.44.50 2.44.50
check_running_image application-celery-1 saas-collab-backend:v2.44.50 2.44.50
check_running_image application-celery-beat-1 saas-collab-backend:v2.44.50 2.44.50
check_running_image application-frontend-1 saas-collab-frontend:v2.44.51 2.44.51
check_running_image application-custody-sidecar-1 saas-collab-custody:v2.44.50 2.44.50

if [ -n "$(docker ps -q --filter name=application-migrate-1 2>/dev/null || true)" ]; then
  fail "migration service is unexpectedly running during rollback."
fi
docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$evidence_dir/rollback-runtime.txt"
printf 'ROLLBACK_VALIDATION=PASS\nTARGET_APPLICATION_RELEASE=2.44.51\nBACKEND_BASELINE=2.44.50\nFRONTEND_BASELINE=2.44.51\nCUSTODY_BASELINE=2.44.50\nDATABASE_MIGRATION_RETAINED=masterdata.0009_warehouse_service_platform\nDATABASE_RESTORE=NOT_PERFORMED\n' \
  > "$evidence_dir/rollback-status.txt"
chmod 600 "$evidence_dir/rollback-status.txt" "$evidence_dir/rollback-runtime.txt"
echo "V2.44.52 ROLLBACK=PASS application_target=2.44.51 database_migration=retained custody=2.44.50:healthy"
