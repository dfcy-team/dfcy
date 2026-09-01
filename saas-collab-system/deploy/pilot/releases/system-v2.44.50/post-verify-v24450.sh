#!/usr/bin/env bash
set -euo pipefail

# Read-only owner handoff verification. This script never changes owner
# verification state and never calls Docker Compose up/down or a migration.

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
version=2.44.50
control_root=${PILOT_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/unified}
legacy_root=${PILOT_LEGACY_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/shared-version-ledger}
mirror=${PILOT_RELEASE_MIRROR:-/home/dfcy01/releases/developer-a-authorized-releases/git-mirror.git}
canonical_ref=${PILOT_CANONICAL_REF:-refs/baselines/canonical-deployed}
tag=v2.44.50-deployed
evidence_dir=${PILOT_RELEASE_EVIDENCE_DIR:-$release_dir}

fail() {
  echo "V2.44.50 post-verification failed: $*" >&2
  exit 1
}

unified_current="$control_root/ledger/current-version.json"
unified_history="$control_root/ledger/release-history.jsonl"
legacy_current="$legacy_root/current-version.json"
legacy_history="$legacy_root/release-ledger.jsonl"
record="$control_root/releases/$version/release-record.json"
marker="$control_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"
legacy_marker="$legacy_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"

for path in "$unified_current" "$unified_history" "$legacy_current" "$legacy_history" "$record" "$marker" "$legacy_marker" "$control_root/ledger/LATEST.sha256" "$legacy_root/LATEST.sha256"; do
  [ -f "$path" ] || fail "required release-control file is missing."
done
sha256sum -c "$control_root/ledger/LATEST.sha256" >/dev/null || fail "unified ledger checksum failed."
sha256sum -c "$legacy_root/LATEST.sha256" >/dev/null || fail "legacy ledger checksum failed."

[ "$(jq -r '.current_release_version' "$unified_current")" = "$version" ] || fail "unified current version is unexpected."
[ "$(jq -r '.current_release_version' "$legacy_current")" = "$version" ] || fail "legacy current version is unexpected."
[ "$(jq -r '.parent_release_version' "$unified_current")" = 2.44.49 ] || fail "unified parent version is unexpected."
[ "$(jq -r '.parent_release_version' "$legacy_current")" = 2.44.49 ] || fail "legacy parent version is unexpected."
[ "$(jq -r '.git_tag' "$unified_current")" = "$tag" ] || fail "unified deployed tag is unexpected."
[ "$(jq -r '.git_tag' "$legacy_current")" = "$tag" ] || fail "legacy deployed tag is unexpected."
[ "$(jq -r '.status' "$unified_current")" = deployed_pending_owner_verification ] || fail "unified owner status is not pending."
[ "$(jq -r '.status' "$legacy_current")" = deployed_pending_owner_verification ] || fail "legacy owner status is not pending."
[ "$(jq -r '.owner_verification' "$marker")" = pending ] || fail "owner verification marker is not pending."
[ "$(jq -r '.owner_verification' "$legacy_marker")" = pending ] || fail "legacy owner verification marker is not pending."
[ "$(jq -r '.release_actor' "$unified_current")" = architect ] || fail "unified release actor is unexpected."
[ "$(jq -r '.source_actor' "$unified_current")" = architect ] || fail "unified source actor is unexpected."
[ "$(jq -r '.source_actor' "$legacy_current")" = architect ] || fail "legacy source actor is unexpected."
[ "$(jq -r '.source_actor' "$record")" = architect ] || fail "release record source actor is unexpected."
[ "$(jq -r '.source_actor' "$marker")" = architect ] || fail "owner marker source actor is unexpected."
[ "$(jq -r '.database_migrations' "$unified_current")" = NONE ] || fail "unified ledger records a migration."
[ "$(jq -r '.database_migrations' "$legacy_current")" = NONE ] || fail "legacy ledger records a migration."
[ "$(jq -r '.current' "$record")" = true ] || fail "release record is not current."
[ "$(jq -r '.status_in_unified_ledger' "$record")" = deployed_pending_owner_verification ] || fail "release record owner status is not pending."

[ -L "$control_root/current" ] || fail "unified current link is missing."
[ "$(readlink -f "$control_root/current")" = "$control_root/releases/$version" ] || fail "unified current link is stale."
[ -d "$mirror" ] || fail "Git mirror is unavailable."
commit=$(jq -r '.git_commit' "$unified_current")
[ "$commit" = "$(jq -r '.git_commit' "$legacy_current")" ] || fail "dual ledger commits differ."
[ "$commit" = "$(jq -r '.git_commit' "$record")" ] || fail "release record commit differs."
[ "$commit" = "$(git --git-dir="$mirror" rev-parse "$canonical_ref^{commit}")" ] || fail "canonical ref differs from ledger."
[ "$commit" = "$(git --git-dir="$mirror" rev-parse "refs/tags/$tag^{commit}")" ] || fail "deployed tag differs from ledger."

check_runtime() {
  container=$1
  expected_image=$2
  image=$(docker inspect "$container" --format '{{.Config.Image}}')
  [ "$image" = "$expected_image" ] || fail "$container image is unexpected."
  [ "$(docker inspect "$container" --format '{{.State.Status}}')" = running ] || fail "$container is not running."
  actual_digest=$(docker image inspect "$image" --format '{{.Id}}')
  ledger_digest=$3
  [ "$actual_digest" = "$ledger_digest" ] || fail "$container image digest differs from ledger."
}

check_runtime application-backend-1 saas-collab-backend:v2.44.50 "$(jq -r '.runtime_backend_digest' "$unified_current")"
check_runtime application-celery-1 saas-collab-backend:v2.44.50 "$(jq -r '.runtime_backend_digest' "$unified_current")"
check_runtime application-celery-beat-1 saas-collab-backend:v2.44.50 "$(jq -r '.runtime_backend_digest' "$unified_current")"
check_runtime application-frontend-1 saas-collab-frontend:v2.44.50 "$(jq -r '.runtime_frontend_digest' "$unified_current")"
check_runtime application-custody-sidecar-1 saas-collab-custody:v2.44.50 "$(jq -r '.runtime_custody_digest' "$unified_current")"
[ "$(docker inspect application-custody-sidecar-1 --format '{{.State.Health.Status}}')" = healthy ] || fail "sidecar health is not healthy."
port_bindings=$(docker inspect application-custody-sidecar-1 --format '{{json .HostConfig.PortBindings}}')
case "$port_bindings" in '{}'|'null'|'') ;; *) fail "sidecar has a host port." ;; esac

backend_mounts=$(docker inspect application-backend-1 --format '{{range .Mounts}}{{println .Destination}}{{end}}')
frontend_mounts=$(docker inspect application-frontend-1 --format '{{range .Mounts}}{{println .Destination}}{{end}}')
printf '%s\n' "$backend_mounts" | grep -Fxq /app/media || fail "backend product-media mount is missing."
printf '%s\n' "$frontend_mounts" | grep -Fxq /usr/share/nginx/html/media || fail "frontend product-media mount is missing."

if [ -f "$evidence_dir/deployment-status.txt" ]; then
  grep -Fxq DATABASE_MIGRATION=NONE "$evidence_dir/deployment-status.txt" || fail "deployment evidence is not migration-free."
fi
printf 'POST_VERIFY=PASS\nOWNER_VERIFICATION_REQUIRED=TRUE\nVERSION=%s\n' "$version" > "$evidence_dir/post-verify-status.txt"
echo "V2.44.50 POST_VERIFY=PASS status=deployed_pending_owner_verification owner_verification=pending database_migration=none"
