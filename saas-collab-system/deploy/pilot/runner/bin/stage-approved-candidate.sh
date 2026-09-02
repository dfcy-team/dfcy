#!/usr/bin/env bash
# Root-only, atomic CI/architecture hand-off for the generic pilot runner.
# The source is a non-secret candidate manifest; registry credentials are never
# accepted here and must remain in the separate owner-managed token file.
set -Eeuo pipefail

readonly CONTROL_ROOT=${PILOT_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/unified}
readonly OUTPUT_FILE=${PILOT_RUNNER_MANIFEST_FILE:-/etc/saas-collab/runner/approved-candidate.json}
readonly OUTPUT_GROUP=${PILOT_RUNNER_GROUP:-saas-runner}

fail() {
  printf 'approved candidate staging blocked: %s\n' "$*" >&2
  exit 1
}

usage() {
  printf '%s\n' 'Usage: stage-approved-candidate.sh --source=/absolute/path/candidate.json [--check-only]'
}

source_file=""
check_only=0
while (($#)); do
  case "$1" in
    --source=*) source_file=${1#*=} ;;
    --check-only) check_only=1 ;;
    --help) usage; exit 0 ;;
    *) usage >&2; fail 'unknown option.' ;;
  esac
  shift
done

[[ "$(id -u)" -eq 0 ]] || fail 'run candidate staging as root.'
[[ "$source_file" = /* && "$source_file" != *$'\n'* && "$source_file" != *$'\r'* ]] || fail 'candidate source must be an absolute newline-free path.'
[[ -f "$source_file" && ! -L "$source_file" ]] || fail 'candidate source must be a regular non-symlink file.'
[[ -f "$CONTROL_ROOT/current.json" && ! -L "$CONTROL_ROOT/current.json" ]] || fail 'production current ledger is missing.'
[[ -d "$(dirname -- "$OUTPUT_FILE")" && ! -L "$(dirname -- "$OUTPUT_FILE")" ]] || fail 'runner configuration directory is missing or unsafe.'

command -v jq >/dev/null 2>&1 || fail 'jq is required.'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required.'
command -v mktemp >/dev/null 2>&1 || fail 'mktemp is required.'

source_owner=$(stat -c '%U' "$source_file" 2>/dev/null) || fail 'cannot inspect candidate source owner.'
source_mode=$(stat -c '%a' "$source_file" 2>/dev/null) || fail 'cannot inspect candidate source mode.'
[[ "$source_owner" = root || "$source_owner" = dfcy01 ]] || fail 'candidate source owner is not controlled.'
(( (8#$source_mode & 0022) == 0 )) || fail 'candidate source must not be group/world writable.'

ledger_owner=$(stat -c '%U' "$CONTROL_ROOT/current.json" 2>/dev/null) || fail 'cannot inspect current ledger owner.'
ledger_mode=$(stat -c '%a' "$CONTROL_ROOT/current.json" 2>/dev/null) || fail 'cannot inspect current ledger mode.'
[[ "$ledger_owner" = root && ( "$ledger_mode" = 400 || "$ledger_mode" = 600 ) ]] || fail 'current ledger must be root-owned mode 0400/0600.'

source_sha_before=$(sha256sum "$source_file" | awk '{print $1}') || fail 'cannot hash candidate source.'
candidate_json=$(/usr/bin/cat "$source_file") || fail 'cannot read candidate source.'
source_sha_after=$(sha256sum "$source_file" | awk '{print $1}') || fail 'cannot hash candidate source.'
[[ "$source_sha_before" = "$source_sha_after" && "$source_sha_before" =~ ^[0-9a-f]{64}$ ]] || fail 'candidate source changed during validation.'

current_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/current.json") || fail 'current ledger release SHA is missing.'
current_version=$(jq -er '.release_version // empty' "$CONTROL_ROOT/current.json") || fail 'current ledger JSON is invalid.'
release_version=$(jq -er '.release_version' <<<"$candidate_json") || fail 'candidate release version is missing.'
parent_version=$(jq -er '.parent_release' <<<"$candidate_json") || fail 'candidate parent version is missing.'
parent_sha=$(jq -er '.parent_release_sha' <<<"$candidate_json") || fail 'candidate parent SHA is missing.'
release_sha=$(jq -er '.release_sha' <<<"$candidate_json") || fail 'candidate release SHA is missing.'
migration_sha=$(jq -er '.migration_sha256' <<<"$candidate_json") || fail 'candidate migration digest is missing.'
backend_image=$(jq -er '.backend_image' <<<"$candidate_json") || fail 'candidate backend image is missing.'
frontend_image=$(jq -er '.frontend_image' <<<"$candidate_json") || fail 'candidate frontend image is missing.'
redis_image=$(jq -er '.redis_image' <<<"$candidate_json") || fail 'candidate Redis image is missing.'
actor=$(jq -er '.actor' <<<"$candidate_json") || fail 'candidate actor is missing.'
registry_user=$(jq -er '.registry_user' <<<"$candidate_json") || fail 'candidate registry user is missing.'
plan_version=$(jq -er '.release_plan.version' <<<"$candidate_json") || fail 'candidate release plan version is missing.'
plan_ref=$(jq -er '.release_plan.ref' <<<"$candidate_json") || fail 'candidate release plan reference is missing.'
rollback_reason=$(jq -er '.rollback_reason' <<<"$candidate_json") || fail 'candidate rollback reason is missing.'

[[ "$release_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$parent_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'candidate release or parent version is invalid.'
[[ -z "$current_version" || "$parent_version" = "$current_version" ]] || fail 'candidate parent version does not match current ledger.'
[[ "$parent_sha" = "$current_sha" ]] || fail 'candidate parent SHA does not match current ledger.'
[[ "$release_sha" =~ ^[0-9a-f]{40}$ && "$parent_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'candidate release SHA is invalid.'
[[ "$migration_sha" =~ ^[0-9a-f]{64}$ ]] || fail 'candidate migration digest is invalid.'
[[ "$backend_image" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-backend@sha256:[0-9a-f]{64}$ ]] || fail 'backend image is not an approved digest.'
[[ "$frontend_image" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-frontend@sha256:[0-9a-f]{64}$ ]] || fail 'frontend image is not an approved digest.'
[[ "$redis_image" =~ ^(redis|docker\.io/library/redis)@sha256:[0-9a-f]{64}$ ]] || fail 'Redis image is not an approved digest.'
[[ "$actor" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$registry_user" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || fail 'candidate actor or registry user is invalid.'
[[ "$plan_version" = "$release_version" && "$plan_ref" =~ ^[A-Za-z0-9_.:/-]{1,200}$ ]] || fail 'release plan does not correspond to candidate version.'
[[ -n "$rollback_reason" && "${#rollback_reason}" -le 512 && "$rollback_reason" != *$'\n'* && "$rollback_reason" != *$'\r'* ]] || fail 'candidate rollback reason is invalid.'
jq -e '.ci_attestation.main_ancestry == true and .ci_attestation.image_digests == true and .ci_attestation.migration_digest == true' <<<"$candidate_json" >/dev/null || fail 'candidate CI attestation is incomplete.'

if [[ "$check_only" -eq 1 ]]; then
  printf 'APPROVED_CANDIDATE_CHECK=PASS\n'
  printf 'APPROVED_CANDIDATE_VERSION=%s\n' "$release_version"
  printf 'APPROVED_CANDIDATE_SHA256=%s\n' "$source_sha_before"
  exit 0
fi

output_dir=$(dirname -- "$OUTPUT_FILE")
output_owner=$(stat -c '%U' "$output_dir" 2>/dev/null) || fail 'cannot inspect runner configuration directory owner.'
output_mode=$(stat -c '%a' "$output_dir" 2>/dev/null) || fail 'cannot inspect runner configuration directory mode.'
[[ "$output_owner" = root && $((8#$output_mode & 0022)) -eq 0 ]] || fail 'runner configuration directory must be root-owned and non-writable by group/other.'
getent group "$OUTPUT_GROUP" >/dev/null 2>&1 || fail 'runner group is missing.'
tmp=$(mktemp "$output_dir/.approved-candidate.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT HUP INT TERM
chmod 440 "$tmp"
chown root:"$OUTPUT_GROUP" "$tmp"
/usr/bin/cp -- "$source_file" "$tmp" || fail 'candidate copy failed.'
chmod 440 "$tmp"
chown root:"$OUTPUT_GROUP" "$tmp"
copied_sha=$(sha256sum "$tmp" | awk '{print $1}') || fail 'cannot hash staged candidate.'
[[ "$copied_sha" = "$source_sha_before" ]] || fail 'staged candidate hash differs from validated source.'
mv -f -- "$tmp" "$OUTPUT_FILE"
trap - EXIT HUP INT TERM
chmod 440 "$OUTPUT_FILE"
chown root:"$OUTPUT_GROUP" "$OUTPUT_FILE"
printf 'APPROVED_CANDIDATE_STAGE=PASS\n'
printf 'APPROVED_CANDIDATE_VERSION=%s\n' "$release_version"
printf 'APPROVED_CANDIDATE_SHA256=%s\n' "$source_sha_before"
