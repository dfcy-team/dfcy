#!/usr/bin/env bash
# Shared checks for the V2.44.59 candidate materials.  The runner itself is
# generic; this file only pins the release-package acceptance criteria.
set -Eeuo pipefail

readonly RELEASE_VERSION=2.44.59
readonly PARENT_RELEASE=2.44.58
readonly PARENT_BASE_COMMIT=7fd5f7f35630a10a5b88da9ae228deb9c31aee08
readonly CONTROL_ROOT=${PILOT_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/unified}
readonly CANDIDATE_FILE=${PILOT_RUNNER_MANIFEST_FILE:-/etc/saas-collab/runner/approved-candidate.json}

release_fail() {
  printf 'V2.44.59 release gate blocked: %s\n' "$*" >&2
  exit 1
}

require_root() {
  [[ "$(id -u)" -eq 0 ]] || release_fail 'this production release gate must run as root.'
}

require_tools() {
  local tool
  for tool in jq sha256sum stat; do
    command -v "$tool" >/dev/null 2>&1 || release_fail "required command is unavailable: $tool"
  done
}

require_candidate_file() {
  [[ "$CANDIDATE_FILE" = /* && -f "$CANDIDATE_FILE" && ! -L "$CANDIDATE_FILE" ]] || release_fail 'approved candidate manifest is missing or unsafe.'
  local owner mode
  owner=$(stat -c '%U' "$CANDIDATE_FILE" 2>/dev/null) || release_fail 'cannot inspect candidate ownership.'
  mode=$(stat -c '%a' "$CANDIDATE_FILE" 2>/dev/null) || release_fail 'cannot inspect candidate mode.'
  [[ "$owner" = root && ( "$mode" = 400 || "$mode" = 440 || "$mode" = 600 || "$mode" = 640 ) ]] || release_fail 'approved candidate must be root-owned mode 0400/0440/0600/0640.'
}

validate_candidate() {
  local require_parent_current=${1:-1}
  require_candidate_file
  [[ -f "$CONTROL_ROOT/current.json" && ! -L "$CONTROL_ROOT/current.json" ]] || release_fail 'production current ledger is missing.'
  local candidate_json current_sha current_version release_version parent_release parent_sha release_sha plan_version plan_ref migration_sha backend frontend redis actor registry_user
  candidate_json=$(/usr/bin/cat "$CANDIDATE_FILE") || release_fail 'approved candidate cannot be read.'
  release_version=$(jq -er '.release_version' <<<"$candidate_json") || release_fail 'candidate release version is missing.'
  parent_release=$(jq -er '.parent_release' <<<"$candidate_json") || release_fail 'candidate parent version is missing.'
  parent_sha=$(jq -er '.parent_release_sha' <<<"$candidate_json") || release_fail 'candidate parent SHA is missing.'
  release_sha=$(jq -er '.release_sha' <<<"$candidate_json") || release_fail 'candidate release SHA is missing.'
  migration_sha=$(jq -er '.migration_sha256' <<<"$candidate_json") || release_fail 'candidate migration digest is missing.'
  backend=$(jq -er '.backend_image' <<<"$candidate_json") || release_fail 'candidate backend image is missing.'
  frontend=$(jq -er '.frontend_image' <<<"$candidate_json") || release_fail 'candidate frontend image is missing.'
  redis=$(jq -er '.redis_image' <<<"$candidate_json") || release_fail 'candidate Redis image is missing.'
  actor=$(jq -er '.actor' <<<"$candidate_json") || release_fail 'candidate actor is missing.'
  registry_user=$(jq -er '.registry_user' <<<"$candidate_json") || release_fail 'candidate registry user is missing.'
  plan_version=$(jq -er '.release_plan.version' <<<"$candidate_json") || release_fail 'candidate release plan version is missing.'
  plan_ref=$(jq -er '.release_plan.ref' <<<"$candidate_json") || release_fail 'candidate release plan ref is missing.'
  current_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/current.json") || release_fail 'current ledger release SHA is missing.'
  current_version=$(jq -er '.release_version // empty' "$CONTROL_ROOT/current.json") || release_fail 'current ledger JSON is invalid.'

  [[ "$release_version" = "$RELEASE_VERSION" && "$parent_release" = "$PARENT_RELEASE" && "$plan_version" = "$RELEASE_VERSION" ]] || release_fail 'candidate does not match V2.44.59 based on V2.44.58.'
  if [[ "$require_parent_current" = 1 ]]; then
    [[ "$parent_sha" = "$current_sha" ]] || release_fail 'candidate parent SHA differs from the production current ledger.'
    [[ -z "$current_version" || "$current_version" = "$parent_release" ]] || release_fail 'candidate parent version differs from the production current ledger.'
  fi
  [[ "$release_sha" =~ ^[0-9a-f]{40}$ && "$parent_sha" =~ ^[0-9a-f]{40}$ && "$migration_sha" =~ ^[0-9a-f]{64}$ ]] || release_fail 'candidate SHA/digest format is invalid.'
  [[ "$backend" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-backend@sha256:[0-9a-f]{64}$ ]] || release_fail 'candidate backend image is not an approved digest.'
  [[ "$frontend" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-frontend@sha256:[0-9a-f]{64}$ ]] || release_fail 'candidate frontend image is not an approved digest.'
  [[ "$redis" =~ ^(redis|docker\.io/library/redis)@sha256:[0-9a-f]{64}$ ]] || release_fail 'candidate Redis image is not an approved digest.'
  [[ "$actor" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$registry_user" =~ ^[A-Za-z0-9_.-]{1,128}$ && "$plan_ref" =~ ^[A-Za-z0-9_.:/-]{1,200}$ ]] || release_fail 'candidate actor/registry/release-plan ref is invalid.'
  jq -e '.ci_attestation.main_ancestry == true and .ci_attestation.image_digests == true and .ci_attestation.migration_digest == true' <<<"$candidate_json" >/dev/null || release_fail 'candidate CI attestation is incomplete.'
}

control_baseline() {
  [[ -x "$CONTROL_ROOT/bin/production-baseline-check" && ! -L "$CONTROL_ROOT/bin/production-baseline-check" ]] || release_fail 'production baseline checker is missing.'
  "$CONTROL_ROOT/bin/production-baseline-check" --runtime >/dev/null || release_fail 'production baseline/backup gate failed.'
}

runner_preflight() {
  [[ -x /usr/local/sbin/saas-collab-pilot-runner-preflight && ! -L /usr/local/sbin/saas-collab-pilot-runner-preflight ]] || release_fail 'installed runner preflight is missing.'
  /usr/local/sbin/saas-collab-pilot-runner-preflight
}

print_candidate_digest() {
  printf 'V24459_CANDIDATE_SHA256=%s\n' "$(sha256sum "$CANDIDATE_FILE" | awk '{print $1}')"
}
