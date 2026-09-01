#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib-v24452.sh
. "$release_dir/lib-v24452.sh"

fail() {
  echo "V2.44.52 post-verification failed: $*" >&2
  exit 1
}

ensure_evidence_dir
read_candidate_file
load_compose_chain

unified_current="$control_root/ledger/current-version.json"
legacy_current="$legacy_root/current-version.json"
record="$control_root/releases/$version/release-record.json"
marker="$control_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"
legacy_marker="$legacy_root/releases/$version/OWNER_VERIFICATION_REQUIRED.json"
for required in "$unified_current" "$legacy_current" "$record" "$marker" "$legacy_marker" "$control_root/ledger/LATEST.sha256" "$legacy_root/LATEST.sha256"; do
  [ -f "$required" ] || fail "required release-control file is missing: $required"
done
sha256sum -c "$control_root/ledger/LATEST.sha256" >/dev/null || fail "unified ledger checksum failed."
sha256sum -c "$legacy_root/LATEST.sha256" >/dev/null || fail "legacy ledger checksum failed."

[ "$(jq -r '.current_release_version' "$unified_current")" = "$version" ] || fail "unified ledger version is unexpected."
[ "$(jq -r '.current_release_version' "$legacy_current")" = "$version" ] || fail "legacy ledger version is unexpected."
[ "$(jq -r '.parent_release_version' "$unified_current")" = "$parent_version" ] || fail "unified ledger parent is unexpected."
[ "$(jq -r '.parent_release_version' "$legacy_current")" = "$parent_version" ] || fail "legacy ledger parent is unexpected."
[ "$(jq -r '.git_commit' "$unified_current")" = "$candidate" ] || fail "unified ledger commit differs from candidate."
[ "$(jq -r '.git_commit' "$legacy_current")" = "$candidate" ] || fail "legacy ledger commit differs from candidate."
[ "$(jq -r '.git_commit' "$record")" = "$candidate" ] || fail "release record commit differs from candidate."
[ "$(jq -r '.status' "$unified_current")" = deployed_pending_owner_verification ] || fail "unified owner status is unexpected."
[ "$(jq -r '.owner_verification' "$marker")" = pending ] || fail "owner verification marker is not pending."
[ "$(jq -r '.owner_verification' "$legacy_marker")" = pending ] || fail "legacy owner verification marker is not pending."
[ "$(jq -r '.database_migrations | join(",")' "$unified_current")" = masterdata.0009_warehouse_service_platform ] || fail "unified migration record is unexpected."

mirror_commit=$(git --git-dir="$mirror" rev-parse "$canonical_ref^{commit}" 2>/dev/null) || fail "canonical ref is unavailable."
[ "$mirror_commit" = "$candidate" ] || fail "canonical ref differs from ledger."
tag_commit=$(git --git-dir="$mirror" rev-parse "refs/tags/$deployed_tag^{commit}" 2>/dev/null) || fail "deployed tag is unavailable."
[ "$tag_commit" = "$candidate" ] || fail "deployed tag differs from ledger."

check_running_image application-backend-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-celery-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-celery-beat-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-frontend-1 saas-collab-frontend:v2.44.52 2.44.52 "$candidate"
check_running_image application-custody-sidecar-1 saas-collab-custody:v2.44.50 2.44.50
sidecar_health=$(docker inspect application-custody-sidecar-1 --format '{{.State.Health.Status}}')
[ "$sidecar_health" = healthy ] || fail "custody sidecar is not healthy."

"${compose[@]}" exec -T backend python manage.py showmigrations masterdata > "$evidence_dir/post-verify-migrations.txt" 2>&1 || fail "cannot read migration state."
grep -Eq '^[[:space:]]*\[[Xx]\][[:space:]]+0009_warehouse_service_platform' "$evidence_dir/post-verify-migrations.txt" || fail "masterdata.0009 is not applied."
printf 'POST_VERIFY=PASS\nOWNER_VERIFICATION_REQUIRED=TRUE\nVERSION=%s\nDATABASE_MIGRATION=masterdata.0009_warehouse_service_platform\n' "$version" \
  > "$evidence_dir/post-verify-status.txt"
chmod 600 "$evidence_dir/post-verify-status.txt"
echo "V2.44.52 POST_VERIFY=PASS status=deployed_pending_owner_verification migration=masterdata.0009_warehouse_service_platform custody=2.44.50:healthy"
