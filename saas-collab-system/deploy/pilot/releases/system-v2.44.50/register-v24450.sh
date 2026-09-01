#!/usr/bin/env bash
set -euo pipefail

# Architect-only release registration. It does not merge or push Git and it
# does not accept owner verification. It writes both release ledgers only
# after the runtime and canonical Git checks pass.

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
version=2.44.50
parent_version=2.44.49
base_commit=61c68a59323e70dab226b5c6f441bf1bb14a00b3
tag=v2.44.50-deployed
scope=integrations.credential_custody
control_root=${PILOT_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/unified}
legacy_root=${PILOT_LEGACY_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/shared-version-ledger}
mirror=${PILOT_RELEASE_MIRROR:-/home/dfcy01/releases/developer-a-authorized-releases/git-mirror.git}
canonical_ref=${PILOT_CANONICAL_REF:-refs/baselines/canonical-deployed}
evidence_dir=${PILOT_RELEASE_EVIDENCE_DIR:-$release_dir}

fail() {
  echo "V2.44.50 registration blocked: $*" >&2
  exit 1
}

atomic_write() {
  target=$1
  content=$2
  tmp="$target.tmp.$BASHPID"
  umask 077
  printf '%s\n' "$content" > "$tmp"
  chmod 640 "$tmp"
  mv -f "$tmp" "$target"
}

append_jsonl() {
  target=$1
  event=$2
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

[ -f "$release_dir/candidate-commit.txt" ] || fail "candidate-commit.txt is required."
candidate=$(tr -d '[:space:]' < "$release_dir/candidate-commit.txt")
printf '%s' "$candidate" | grep -Eq '^[0-9a-f]{40}$' || fail "candidate commit must be a full Git SHA."
[ -f "$evidence_dir/deployment-status.txt" ] || fail "deployment-status.txt is required."
grep -Fxq DEPLOYMENT_VALIDATION=PASS "$evidence_dir/deployment-status.txt" || fail "deployment validation is not PASS."

[ "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = saas-collab-backend:v2.44.50 ] || fail "backend is not V2.44.50."
[ "$(docker inspect application-celery-1 --format '{{.Config.Image}}')" = saas-collab-backend:v2.44.50 ] || fail "celery is not V2.44.50."
[ "$(docker inspect application-celery-beat-1 --format '{{.Config.Image}}')" = saas-collab-backend:v2.44.50 ] || fail "celery-beat is not V2.44.50."
[ "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = saas-collab-frontend:v2.44.50 ] || fail "frontend is not V2.44.50."
[ "$(docker inspect application-custody-sidecar-1 --format '{{.Config.Image}}')" = saas-collab-custody:v2.44.50 ] || fail "custody sidecar is not V2.44.50."
[ "$(docker inspect application-custody-sidecar-1 --format '{{.State.Health.Status}}')" = healthy ] || fail "custody sidecar is not healthy."

backend_digest=$(docker image inspect saas-collab-backend:v2.44.50 --format '{{.Id}}')
frontend_digest=$(docker image inspect saas-collab-frontend:v2.44.50 --format '{{.Id}}')
custody_digest=$(docker image inspect saas-collab-custody:v2.44.50 --format '{{.Id}}')
backend_revision=$(docker image inspect saas-collab-backend:v2.44.50 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
frontend_revision=$(docker image inspect saas-collab-frontend:v2.44.50 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
custody_revision=$(docker image inspect saas-collab-custody:v2.44.50 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
[ "$backend_revision" = "$candidate" ] || fail "backend image revision does not match candidate."
[ "$frontend_revision" = "$candidate" ] || fail "frontend image revision does not match candidate."
[ "$custody_revision" = "$candidate" ] || fail "custody image revision does not match candidate."

[ -d "$mirror" ] || fail "Git mirror is unavailable."
canonical_commit=$(git --git-dir="$mirror" rev-parse "$canonical_ref^{commit}" 2>/dev/null) || fail "canonical ref is unavailable."
[ "$canonical_commit" = "$candidate" ] || fail "canonical ref does not resolve to candidate."
deployed_tag_commit=$(git --git-dir="$mirror" rev-parse "refs/tags/$tag^{commit}" 2>/dev/null) || fail "deployed tag is unavailable."
[ "$deployed_tag_commit" = "$candidate" ] || fail "deployed tag does not resolve to candidate."

unified_current="$control_root/ledger/current-version.json"
unified_history="$control_root/ledger/release-history.jsonl"
unified_policy="$control_root/release-policy.json"
legacy_current="$legacy_root/current-version.json"
legacy_history="$legacy_root/release-ledger.jsonl"
[ -f "$unified_current" ] || fail "unified current-version.json is missing."
[ -f "$unified_history" ] || fail "unified release-history.jsonl is missing."
[ -f "$legacy_current" ] || fail "legacy current-version.json is missing."
[ -f "$legacy_history" ] || fail "legacy release-ledger.jsonl is missing."
[ "$(jq -r '.current_release_version' "$unified_current")" = "$parent_version" ] || fail "unified ledger is not on V2.44.49."
[ "$(jq -r '.git_commit' "$unified_current")" = "$base_commit" ] || fail "unified ledger commit is not V2.44.49 baseline."
[ "$(jq -r '.current_release_version' "$legacy_current")" = "$parent_version" ] || fail "legacy ledger is not on V2.44.49."
[ "$(jq -r '.git_commit' "$legacy_current")" = "$base_commit" ] || fail "legacy ledger commit is not V2.44.49 baseline."
grep -Fq '"version":"2.44.50"' "$unified_history" && fail "V2.44.50 is already registered."

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

now_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)
now_local=$(date +%Y-%m-%dT%H:%M:%S%z)
record_path="$control_root/releases/$version/release-record.json"
marker_path="$control_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"
legacy_marker_path="$legacy_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"

release_record=$(jq -n \
  --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$tag" \
  --arg scope "$scope" --arg canonical "$canonical_ref" --arg actor architect --arg source architect \
  --arg backend_image saas-collab-backend:v2.44.50 --arg backend_digest "$backend_digest" \
  --arg frontend_image saas-collab-frontend:v2.44.50 --arg frontend_digest "$frontend_digest" \
  --arg custody_image saas-collab-custody:v2.44.50 --arg custody_digest "$custody_digest" \
  --arg evidence "$evidence_dir" --arg now_utc "$now_utc" --arg now_local "$now_local" \
  '{schema_version:2,version:$version,parent_version:$parent,git_commit:$commit,git_tag:$tag,actor:$actor,source_actor:$source,current:true,status_in_unified_ledger:"deployed_pending_owner_verification",scope:$scope,canonical_ref:$canonical,source_manifest:$evidence,frontend_image:$frontend_image,frontend_digest:$frontend_digest,backend_image:$backend_image,backend_digest:$backend_digest,celery_image:$backend_image,celery_beat_image:$backend_image,custody_image:$custody_image,custody_digest:$custody_digest,database_migration_required:false,database_migrations:"NONE",external_platform_live:false,menu_changed:false,router_changed:false,permission_catalog_changed:false,owner_verification:"pending",owner_verification_required:true,deployment_evidence_directory:$evidence,registered_at_utc:$now_utc,registered_at_local:$now_local,rollback:{application_release:$parent,backend_image:"saas-collab-backend:v2.44.49",frontend_image:"saas-collab-frontend:v2.44.49",custody_sidecar:"stopped",database_restore_required:false}}')
atomic_write "$record_path" "$release_record"

owner_marker=$(jq -n \
  --arg version "$version" --arg commit "$candidate" --arg tag "$tag" --arg parent "$parent_version" \
  --arg scope "$scope" --arg canonical "$canonical_ref" --arg evidence "$evidence_dir" --arg now "$now_utc" \
  '{schema_version:1,status:"deployed_pending_owner_verification",version:$version,parent_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:$canonical,actor:"architect",source_actor:"architect",scope:$scope,frontend_image:"saas-collab-frontend:v2.44.50",backend_image:"saas-collab-backend:v2.44.50",custody_image:"saas-collab-custody:v2.44.50",database_migrations:["NONE"],menu_changed:false,router_changed:false,permission_catalog_changed:false,owner_verification:"pending",verification_evidence:$evidence,created_at_utc:$now}')
atomic_write "$marker_path" "$owner_marker"
atomic_write "$legacy_marker_path" "$owner_marker"

unified_current_payload=$(jq -n \
  --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$tag" \
  --arg canonical "$canonical_ref" --arg backend "$backend_digest" --arg frontend "$frontend_digest" --arg custody "$custody_digest" \
  --arg now_utc "$now_utc" --arg now_local "$now_local" --arg scope "$scope" \
  '{schema_version:2,captured_date:($now_utc|split("T")[0]),current_release_version:$version,parent_release_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:$canonical,source_manifest:$evidence,runtime_frontend_image:"saas-collab-frontend:v2.44.50",runtime_frontend_digest:$frontend,runtime_backend_image:"saas-collab-backend:v2.44.50",runtime_backend_digest:$backend,runtime_custody_image:"saas-collab-custody:v2.44.50",runtime_custody_digest:$custody,runtime_celery_image:"saas-collab-backend:v2.44.50",runtime_celery_beat_image:"saas-collab-backend:v2.44.50",status:"deployed_pending_owner_verification",release_actor:"architect",source_actor:"architect",release_scope:$scope,release_record:"/opt/saas-collab/release-control/unified/releases/2.44.50/release-record.json",database_migrations:"NONE",menu_changed:false,router_changed:false,permission_catalog_changed:false,owner_verification:"pending",owner_verification_required:true,deployed_at_utc:$now_utc,deployed_at_local:$now_local}')
atomic_write "$unified_current" "$unified_current_payload"

legacy_current_payload=$(jq -n \
  --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$tag" \
  --arg backend "$backend_digest" --arg frontend "$frontend_digest" --arg custody "$custody_digest" --arg now_utc "$now_utc" --arg now_local "$now_local" --arg scope "$scope" \
  '{schema_version:1,current_release_version:$version,parent_release_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:"refs/baselines/canonical-deployed",source_manifest:$evidence,runtime_frontend_image:"saas-collab-frontend:v2.44.50",runtime_frontend_image_id:$frontend,runtime_frontend_digest:$frontend,runtime_backend_image:"saas-collab-backend:v2.44.50",runtime_backend_image_id:$backend,runtime_backend_digest:$backend,runtime_custody_image:"saas-collab-custody:v2.44.50",runtime_custody_image_id:$custody,status:"deployed_pending_owner_verification",release_actor:"architect",source_actor:"architect",release_scope:$scope,menu_baseline:"2.44.48",permission_ui_baseline:"2.44.48",menu_changed:false,router_changed:false,permission_catalog_changed:false,database_migrations:"NONE",owner_verification:"pending",owner_verification_required:true,deployed_at_utc:$now_utc,deployed_at_local:$now_local}')
atomic_write "$legacy_current" "$legacy_current_payload"

if [ -f "$control_root/releases/$parent_version/release-record.json" ]; then
  parent_payload=$(jq '.current = false' "$control_root/releases/$parent_version/release-record.json")
  atomic_write "$control_root/releases/$parent_version/release-record.json" "$parent_payload"
fi
if [ -f "$unified_policy" ]; then
  policy_payload=$(jq --arg version "$version" --arg tag "$tag" --arg commit "$candidate" \
    '.current_baseline = {version:$version,git_tag:$tag,git_commit:$commit,status:"deployed_pending_owner_verification"}' "$unified_policy")
  atomic_write "$unified_policy" "$policy_payload"
fi

event=$(jq -nc \
  --arg now_utc "$now_utc" --arg now_local "$now_local" --arg version "$version" --arg parent "$parent_version" --arg commit "$candidate" --arg tag "$tag" --arg canonical "$canonical_ref" --arg scope "$scope" --arg backend "$backend_digest" --arg frontend "$frontend_digest" --arg custody "$custody_digest" \
  '{schema_version:2,event:"architect_controlled_release_registered",version:$version,parent_version:$parent,git_commit:$commit,git_tag:$tag,canonical_ref:$canonical,actor:"architect",source_actor:"architect",scope:$scope,frontend_image:"saas-collab-frontend:v2.44.50",frontend_digest:$frontend,backend_image:"saas-collab-backend:v2.44.50",backend_digest:$backend,custody_image:"saas-collab-custody:v2.44.50",custody_digest:$custody,database_migrations:"NONE",menu_changed:false,router_changed:false,permission_catalog_changed:false,status:"deployed_pending_owner_verification",owner_verification:"pending",time_utc:$now_utc,time_local:$now_local}')
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
echo "V2.44.50 REGISTRATION=PASS status=deployed_pending_owner_verification owner_verification=pending database_migration=none"
