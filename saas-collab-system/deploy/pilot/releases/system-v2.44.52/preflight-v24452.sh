#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib-v24452.sh
. "$release_dir/lib-v24452.sh"

fail() {
  echo "V2.44.52 preflight blocked: $*" >&2
  exit 1
}

ensure_evidence_dir
[ "${PILOT_RELEASE_ACTOR:-architect}" = architect ] || fail "only the architect release actor may run this package."
[ -f "$env_file" ] || fail "missing protected .env.pilot."
[ ! -L "$env_file" ] || fail ".env.pilot must not be a symbolic link."
env_mode=$(stat -c '%a' "$env_file")
[ "$env_mode" = 600 ] || [ "$env_mode" = 640 ] || fail ".env.pilot mode must be 0600 or 0640."
[ -f "$repo_dir/.git/HEAD" ] || git -C "$repo_dir" rev-parse --git-dir >/dev/null 2>&1 || fail "reviewed source checkout is unavailable: $repo_dir"

for command_name in docker git jq sha256sum stat sed grep awk curl mysqldump; do
  command -v "$command_name" >/dev/null 2>&1 || fail "$command_name is required on the application VM."
done
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 is required."

read_candidate_file
git -C "$repo_dir" cat-file -e "$base_commit^{commit}" 2>/dev/null || fail "parent V2.44.51 commit is unavailable in source checkout."
git -C "$repo_dir" cat-file -e "$candidate^{commit}" 2>/dev/null || fail "approved candidate commit is unavailable in source checkout."
git -C "$repo_dir" merge-base --is-ancestor "$base_commit" "$candidate" || fail "candidate is not based directly on V2.44.51 parent ancestry."
git -C "$repo_dir" diff --check "$base_commit" "$candidate" >/dev/null || fail "candidate diff --check failed."

# The source delta is fixed to the reviewed Shopee OAuth and warehouse
# service-platform increment. Any accumulated or unrelated path blocks the
# release before Docker build or database access.
while IFS= read -r changed_path; do
  [ -n "$changed_path" ] || continue
  case "$changed_path" in
    saas-collab-system/backend/.gitignore|\
    saas-collab-system/backend/apps/integrations/live_providers.py|\
    saas-collab-system/backend/apps/integrations/management/__init__.py|\
    saas-collab-system/backend/apps/integrations/management/commands/__init__.py|\
    saas-collab-system/backend/apps/integrations/management/commands/repair_shopee_callback.py|\
    saas-collab-system/backend/apps/integrations/platform_schema_service.py|\
    saas-collab-system/backend/apps/integrations/serializers.py|\
    saas-collab-system/backend/apps/integrations/subject_access_service.py|\
    saas-collab-system/backend/apps/integrations/views.py|\
    saas-collab-system/backend/apps/masterdata/migrations/0009_warehouse_service_platform.py|\
    saas-collab-system/backend/apps/masterdata/models.py|\
    saas-collab-system/backend/apps/masterdata/serializers.py|\
    saas-collab-system/backend/apps/masterdata/views.py|\
    saas-collab-system/backend/scripts/ci_guard.py|\
    saas-collab-system/backend/tests/test_custody_security_gate.py|\
    saas-collab-system/backend/tests/test_custody_service.py|\
    saas-collab-system/backend/tests/test_integration_credential_maintenance.py|\
    saas-collab-system/backend/tests/test_shopee_callback_repair_command.py|\
    saas-collab-system/backend/tests/test_shopee_production_oauth_readiness.py|\
    saas-collab-system/backend/tests/test_subject_api_access.py|\
    saas-collab-system/backend/tests/test_ui_p2_system_masterdata.py|\
    saas-collab-system/docs/06_release/system_v2.44.52.md|\
    saas-collab-system/frontend/src/components/AdminResourcePage.vue|\
    saas-collab-system/frontend/src/components/SubjectApiAccessDialog.vue|\
    saas-collab-system/frontend/src/views/integrations/IntegrationWorkspace.vue|\
    saas-collab-system/frontend/src/views/masterdata/PlatformMasterList.vue|\
    saas-collab-system/frontend/src/views/masterdata/StoreMasterList.vue|\
    saas-collab-system/frontend/src/views/masterdata/WarehouseMasterList.vue|\
    saas-collab-system/frontend/tests/master-data-handoff.spec.js|\
    saas-collab-system/frontend/tests/shopee-production-authorization.spec.js) ;;
    *) fail "candidate contains an unapproved changed path: $changed_path" ;;
  esac
done < <(git -C "$repo_dir" diff --name-only "$base_commit" "$candidate")

assert_no_sensitive_bundle_files
[ -f "$source_dir/backend/apps/masterdata/migrations/0009_warehouse_service_platform.py" ] || fail "0009 migration file is missing from candidate source."
[ "$(sha256sum "$source_dir/backend/apps/masterdata/migrations/0009_warehouse_service_platform.py" | cut -d' ' -f1)" = \
  1391cfdce4813e873cf53d696564d86d317dc63df080b4dc829885a578782818 ] || fail "0009 migration digest differs from reviewed candidate."

expected_user=$(env_value PILOT_APPLICATION_DB_USER)
expected_name=$(env_value PILOT_APPLICATION_DB_NAME)
[ "${expected_user:-saas_collab_pilot_user}" = saas_collab_pilot_user ] || fail "PILOT_APPLICATION_DB_USER must be saas_collab_pilot_user."
[ "${expected_name:-saas_collab_pilot}" = saas_collab_pilot ] || fail "PILOT_APPLICATION_DB_NAME must be saas_collab_pilot."
application_db_env_args

load_compose_chain
"${compose[@]}" config --quiet >/dev/null 2>&1 || fail "application base/override Compose chain is invalid."

# Verify the mixed deployed baseline supplied by the owner. This is read-only;
# it does not pull, stop, recreate, or mutate any container.
check_running_image application-backend-1 saas-collab-backend:v2.44.50 2.44.50
check_running_image application-celery-1 saas-collab-backend:v2.44.50 2.44.50
check_running_image application-celery-beat-1 saas-collab-backend:v2.44.50 2.44.50
check_running_image application-frontend-1 saas-collab-frontend:v2.44.51 2.44.51
check_running_image application-custody-sidecar-1 saas-collab-custody:v2.44.50 2.44.50
sidecar_health=$(docker inspect application-custody-sidecar-1 --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')
[ "$sidecar_health" = healthy ] || fail "V2.44.50 custody sidecar is not healthy."

# The release compose must keep custody isolated and must not expose a host
# port. Check the rendered service shape without printing its environment.
sidecar_ports=$(docker inspect application-custody-sidecar-1 --format '{{json .HostConfig.PortBindings}}')
case "$sidecar_ports" in '{}'|'null'|'') ;; *) fail "custody sidecar has a host port binding." ;; esac
for container in application-backend-1 application-celery-1 application-celery-beat-1; do
  mounts=$(docker inspect "$container" --format '{{range .Mounts}}{{println .Destination}}{{end}}')
  printf '%s\n' "$mounts" | grep -Fxq /run/secrets/custody-service.token || fail "$container is missing the custody service-token mount."
  printf '%s\n' "$mounts" | grep -Fxq /run/secrets/custody-ca.pem || fail "$container is missing the custody CA mount."
  for forbidden in /run/secrets/custody-master.key /run/secrets/custody-tls.key /var/lib/saas-collab-custody; do
    if printf '%s\n' "$mounts" | grep -Fxq "$forbidden"; then
      fail "$container received forbidden custody mount: $forbidden"
    fi
  done
done

echo "V2.44.52 PREFLIGHT=PASS parent=$parent_version parent_commit=$base_commit candidate=$candidate database=masterdata.0009_warehouse_service_platform application_db=approved custody=2.44.50:healthy"
