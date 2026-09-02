#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib-v24452.sh
. "$release_dir/lib-v24452.sh"

fail() {
  echo "V2.44.52 registration blocked: $*" >&2
  exit 1
}

ensure_evidence_dir
[ "${PILOT_RELEASE_ACTOR:-architect}" = architect ] || fail "only the architect release actor may register a release."
read_candidate_file
load_compose_chain

[ -f "$evidence_dir/deployment-status.txt" ] || fail "deployment-status.txt is required."
grep -Fxq DEPLOYMENT_VALIDATION=PASS "$evidence_dir/deployment-status.txt" || fail "deployment validation is not PASS."
grep -Fxq DATABASE_MIGRATION=masterdata.0009_warehouse_service_platform "$evidence_dir/deployment-status.txt" || \
  fail "deployment evidence does not identify the exact migration."
[ -f "$evidence_dir/migration-status.txt" ] || fail "migration-status.txt is required."
grep -Fxq MIGRATION_APPLY=PASS "$evidence_dir/migration-status.txt" || fail "migration evidence is not PASS."
grep -Fxq MIGRATION_PLAN=masterdata.0009_warehouse_service_platform "$evidence_dir/migration-status.txt" || \
  fail "migration evidence does not prove the exact plan."

check_running_image application-backend-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-celery-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-celery-beat-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-frontend-1 saas-collab-frontend:v2.44.52 2.44.52 "$candidate"
check_running_image application-custody-sidecar-1 saas-collab-custody:v2.44.50 2.44.50

backend_digest=$(docker image inspect saas-collab-backend:v2.44.52 --format '{{.Id}}')
frontend_digest=$(docker image inspect saas-collab-frontend:v2.44.52 --format '{{.Id}}')
custody_digest=$(docker image inspect saas-collab-custody:v2.44.50 --format '{{.Id}}')
backup_path=$(sed -n 's/^BACKUP_PATH=//p' "$evidence_dir/migration-status.txt" | tail -n 1)
backup_sha=$(sed -n 's/^BACKUP_SHA256=//p' "$evidence_dir/migration-status.txt" | tail -n 1)
[ -f "$backup_path" ] || fail "recorded pre-migration backup is missing."
printf '%s' "$backup_sha" | grep -Eq '^[0-9a-f]{64}$' || fail "recorded backup SHA-256 is invalid."
[ "$(sha256sum "$backup_path" | cut -d' ' -f1)" = "$backup_sha" ] || fail "pre-migration backup checksum changed."

[ -d "$mirror" ] || fail "controlled Git mirror is unavailable."
canonical_commit=$(git --git-dir="$mirror" rev-parse "$canonical_ref^{commit}" 2>/dev/null) || fail "canonical ref is unavailable."
[ "$canonical_commit" = "$candidate" ] || fail "canonical ref does not resolve to the deployed candidate."
deployed_tag_commit=$(git --git-dir="$mirror" rev-parse "refs/tags/$deployed_tag^{commit}" 2>/dev/null) || \
  fail "$deployed_tag is not present; the main architect must create it only after final runtime verification."
[ "$deployed_tag_commit" = "$candidate" ] || fail "deployed tag does not resolve to the deployed candidate."

unified_current="$control_root/ledger/current-version.json"
unified_history="$control_root/ledger/release-history.jsonl"
unified_policy="$control_root/release-policy.json"
legacy_current="$legacy_root/current-version.json"
legacy_history="$legacy_root/release-ledger.jsonl"
for required in "$unified_current" "$unified_history" "$legacy_current" "$legacy_history"; do
  [ -f "$required" ] || fail "required release ledger file is missing: $required"
done
[ "$(jq -r '.current_release_version' "$unified_current")" = "$parent_version" ] || fail "unified ledger is not on parent V2.44.51."
[ "$(jq -r '.git_commit' "$unified_current")" = "$base_commit" ] || fail "unified ledger is not on the V2.44.51 parent commit."
[ "$(jq -r '.current_release_version' "$legacy_current")" = "$parent_version" ] || fail "legacy ledger is not on parent V2.44.51."
[ "$(jq -r '.git_commit' "$legacy_current")" = "$base_commit" ] || fail "legacy ledger is not on the V2.44.51 parent commit."
grep -Fq '"version":"2.44.52"' "$unified_history" && fail "V2.44.52 is already present in the unified history."
grep -Fq '"version":"2.44.52"' "$legacy_history" && fail "V2.44.52 is already present in the legacy history."

mkdir -p "$control_root/releases/$version" "$legacy_root/releases/$version"
backup_dir="$evidence_dir/pre-register-ledger-$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p "$backup_dir"
cp -a "$unified_current" "$backup_dir/unified-current-version.json"
cp -a "$unified_history" "$backup_dir/unified-release-history.jsonl"
cp -a "$legacy_current" "$backup_dir/legacy-current-version.json"
cp -a "$legacy_history" "$backup_dir/legacy-release-ledger.jsonl"
[ -f "$control_root/ledger/LATEST.sha256" ] && cp -a "$control_root/ledger/LATEST.sha256" "$backup_dir/unified-LATEST.sha256"
[ -f "$legacy_root/LATEST.sha256" ] && cp -a "$legacy_root/LATEST.sha256" "$backup_dir/legacy-LATEST.sha256"
[ -f "$unified_policy" ] && cp -a "$unified_policy" "$backup_dir/release-policy.json"
[ -f "$control_root/releases/$parent_version/release-record.json" ] && cp -a "$control_root/releases/$parent_version/release-record.json" "$backup_dir/parent-release-record.json"

atomic_write() {
  local target=$1
  local content=$2
  local temporary="$target.tmp.$BASHPID"
  umask 077
  printf '%s\n' "$content" > "$temporary"
  chmod 640 "$temporary"
  mv -f "$temporary" "$target"
}

append_jsonl() {
  local target=$1
  local event=$2
  python3 - "$target" "$event" <<'PY'
import os
import sys

path, line = sys.argv[1:]
with open(path, "a", encoding="utf-8") as handle:
    handle.write(line + "\n")
    handle.flush()
    os.fsync(handle.fileno())
PY
}

now_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
now_local=$(date +%Y-%m-%dT%H:%M:%S%z)
record_path="$control_root/releases/$version/release-record.json"
marker_path="$control_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"
legacy_marker_path="$legacy_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"

release_record=$(jq -n \
  --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$deployed_tag" \
  --arg scope "integrations.shopee_oauth+masterdata.warehouse_service_platform" --arg canonical "$canonical_ref" \
  --arg backend_image saas-collab-backend:v2.44.52 --arg backend_digest "$backend_digest" \
  --arg frontend_image saas-collab-frontend:v2.44.52 --arg frontend_digest "$frontend_digest" \
  --arg custody_image saas-collab-custody:v2.44.50 --arg custody_digest "$custody_digest" \
  --arg backup "$backup_path" --arg backup_sha "$backup_sha" --arg evidence "$evidence_dir" \
  --arg now_utc "$now_utc" --arg now_local "$now_local" \
  '{schema_version:3,version:$version,parent_version:$parent,git_commit:$commit,git_tag:$tag,actor:"architect",source_actor:"architect",current:true,status_in_unified_ledger:"deployed_pending_owner_verification",scope:$scope,canonical_ref:$canonical,source_manifest:$evidence,frontend_image:$frontend_image,frontend_digest:$frontend_digest,backend_image:$backend_image,backend_digest:$backend_digest,celery_image:$backend_image,celery_beat_image:$backend_image,custody_image:$custody_image,custody_digest:$custody_digest,database_migration_required:true,database_migrations:["masterdata.0009_warehouse_service_platform"],database_backup:$backup,database_backup_sha256:$backup_sha,external_platform_live:false,menu_changed:false,router_changed:false,permission_catalog_changed:false,owner_verification:"pending",owner_verification_required:true,deployment_evidence_directory:$evidence,registered_at_utc:$now_utc,registered_at_local:$now_local,rollback:{application_release:$parent,backend_image:"saas-collab-backend:v2.44.50",frontend_image:"saas-collab-frontend:v2.44.51",custody_sidecar:"saas-collab-custody:v2.44.50",database_restore_required:false,database_migration:"masterdata.0009_warehouse_service_platform retained"}}')
atomic_write "$record_path" "$release_record"

owner_marker=$(jq -n \
  --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$deployed_tag" \
  --arg scope "integrations.shopee_oauth+masterdata.warehouse_service_platform" --arg canonical "$canonical_ref" \
  --arg backend saas-collab-backend:v2.44.52 --arg frontend saas-collab-frontend:v2.44.52 --arg custody saas-collab-custody:v2.44.50 \
  --arg evidence "$evidence_dir" --arg now "$now_utc" \
  '{schema_version:1,status:"deployed_pending_owner_verification",version:$version,parent_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:$canonical,actor:"architect",source_actor:"architect",scope:$scope,frontend_image:$frontend,backend_image:$backend,custody_image:$custody,database_migrations:["masterdata.0009_warehouse_service_platform"],owner_verification:"pending",owner_verification_required:true,verification_evidence:$evidence,created_at_utc:$now}')
atomic_write "$marker_path" "$owner_marker"
atomic_write "$legacy_marker_path" "$owner_marker"

unified_current_payload=$(jq -n \
  --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$deployed_tag" \
  --arg canonical "$canonical_ref" --arg backend "$backend_digest" --arg frontend "$frontend_digest" --arg custody "$custody_digest" \
  --arg backup "$backup_path" --arg backup_sha "$backup_sha" --arg now_utc "$now_utc" --arg now_local "$now_local" \
  --arg scope "integrations.shopee_oauth+masterdata.warehouse_service_platform" --arg evidence "$evidence_dir" \
  '{schema_version:3,captured_date:($now_utc|split("T")[0]),current_release_version:$version,parent_release_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:$canonical,source_manifest:$evidence,runtime_frontend_image:"saas-collab-frontend:v2.44.52",runtime_frontend_digest:$frontend,runtime_backend_image:"saas-collab-backend:v2.44.52",runtime_backend_digest:$backend,runtime_custody_image:"saas-collab-custody:v2.44.50",runtime_custody_digest:$custody,runtime_celery_image:"saas-collab-backend:v2.44.52",runtime_celery_beat_image:"saas-collab-backend:v2.44.52",status:"deployed_pending_owner_verification",release_actor:"architect",source_actor:"architect",release_scope:$scope,release_record:"/opt/saas-collab/release-control/unified/releases/2.44.52/release-record.json",database_migration_required:true,database_migrations:["masterdata.0009_warehouse_service_platform"],database_backup:$backup,database_backup_sha256:$backup_sha,menu_changed:false,router_changed:false,permission_catalog_changed:false,owner_verification:"pending",owner_verification_required:true,deployed_at_utc:$now_utc,deployed_at_local:$now_local}')
atomic_write "$unified_current" "$unified_current_payload"

legacy_current_payload=$(jq -n \
  --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$deployed_tag" \
  --arg backend "$backend_digest" --arg frontend "$frontend_digest" --arg custody "$custody_digest" --arg backup "$backup_path" --arg backup_sha "$backup_sha" \
  --arg now_utc "$now_utc" --arg now_local "$now_local" --arg scope "integrations.shopee_oauth+masterdata.warehouse_service_platform" --arg evidence "$evidence_dir" \
  '{schema_version:2,current_release_version:$version,parent_release_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:"refs/baselines/canonical-deployed",source_manifest:$evidence,runtime_frontend_image:"saas-collab-frontend:v2.44.52",runtime_frontend_image_id:$frontend,runtime_frontend_digest:$frontend,runtime_backend_image:"saas-collab-backend:v2.44.52",runtime_backend_image_id:$backend,runtime_backend_digest:$backend,runtime_custody_image:"saas-collab-custody:v2.44.50",runtime_custody_image_id:$custody,status:"deployed_pending_owner_verification",release_actor:"architect",source_actor:"architect",release_scope:$scope,database_migration_required:true,database_migrations:["masterdata.0009_warehouse_service_platform"],database_backup:$backup,database_backup_sha256:$backup_sha,menu_changed:false,router_changed:false,permission_catalog_changed:false,owner_verification:"pending",owner_verification_required:true,deployed_at_utc:$now_utc,deployed_at_local:$now_local}')
atomic_write "$legacy_current" "$legacy_current_payload"

if [ -f "$control_root/releases/$parent_version/release-record.json" ]; then
  atomic_write "$control_root/releases/$parent_version/release-record.json" "$(jq '.current = false' "$control_root/releases/$parent_version/release-record.json")"
fi
if [ -f "$unified_policy" ]; then
  atomic_write "$unified_policy" "$(jq --arg version "$version" --arg tag "$deployed_tag" --arg commit "$candidate" --arg migration "masterdata.0009_warehouse_service_platform" \
    '.current_baseline = {version:$version,git_tag:$tag,git_commit:$commit,status:"deployed_pending_owner_verification",database_migrations:[$migration]}' "$unified_policy")"
fi

event=$(jq -nc \
  --arg now_utc "$now_utc" --arg now_local "$now_local" --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$deployed_tag" \
  --arg canonical "$canonical_ref" --arg scope "integrations.shopee_oauth+masterdata.warehouse_service_platform" --arg backend "$backend_digest" --arg frontend "$frontend_digest" --arg custody "$custody_digest" --arg backup "$backup_path" --arg backup_sha "$backup_sha" \
  '{schema_version:3,event:"architect_controlled_release_registered",version:$version,parent_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:$canonical,actor:"architect",source_actor:"architect",scope:$scope,frontend_image:"saas-collab-frontend:v2.44.52",frontend_digest:$frontend,backend_image:"saas-collab-backend:v2.44.52",backend_digest:$backend,custody_image:"saas-collab-custody:v2.44.50",custody_digest:$custody,database_migration_required:true,database_migrations:["masterdata.0009_warehouse_service_platform"],database_backup:$backup,database_backup_sha256:$backup_sha,menu_changed:false,router_changed:false,permission_catalog_changed:false,status:"deployed_pending_owner_verification",owner_verification:"pending",time_utc:$now_utc,time_local:$now_local}')
append_jsonl "$unified_history" "$event"
append_jsonl "$legacy_history" "$event"

if [ -e "$control_root/current" ] && [ ! -L "$control_root/current" ]; then
  fail "unified current path is not a symbolic link."
fi
ln -s "$control_root/releases/$version" "$control_root/current.tmp.$BASHPID"
mv -Tf "$control_root/current.tmp.$BASHPID" "$control_root/current"
atomic_write "$control_root/ledger/LATEST.sha256" "$(sha256sum "$unified_current")"
atomic_write "$legacy_root/LATEST.sha256" "$(sha256sum "$legacy_current")"

jq empty "$record_path" "$marker_path" "$legacy_marker_path" "$unified_current" "$legacy_current"
sha256sum -c "$control_root/ledger/LATEST.sha256" >/dev/null
sha256sum -c "$legacy_root/LATEST.sha256" >/dev/null
echo "V2.44.52 REGISTRATION=PASS status=deployed_pending_owner_verification owner_verification=pending migration=masterdata.0009_warehouse_service_platform tag=$deployed_tag"
