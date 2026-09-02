#!/usr/bin/env bash
# Root-owned bridge helpers for the standalone pilot runner.  These helpers
# accept no client arguments and consume only the owner/CI atomically staged
# approved-candidate manifest and registry token for deploy/rollback. Recovery
# intentionally uses only the root-owned production current ledger.
set -Eeuo pipefail

readonly CONTROL_ROOT=/opt/saas-collab/release-control/unified
readonly MANIFEST_FILE=/etc/saas-collab/runner/approved-candidate.json
readonly REGISTRY_TOKEN_FILE=/etc/saas-collab/runner/registry-token

bridge_fail() {
  printf 'pilot runner bridge blocked: %s\n' "$*" >&2
  exit 1
}

secure_file() {
  local path=$1 label=$2 mode owner group
  [[ "$path" = /* && -f "$path" && ! -L "$path" ]] || bridge_fail "$label is missing or unsafe."
  mode=$(stat -c '%a' "$path" 2>/dev/null) || bridge_fail "cannot inspect $label mode."
  if [[ "$label" = registry-token ]]; then
    [[ "$mode" = 400 || "$mode" = 600 ]] || bridge_fail 'registry token must be mode 0400 or 0600.'
  elif [[ "$label" = candidate-manifest ]]; then
    [[ "$mode" = 400 || "$mode" = 440 || "$mode" = 600 || "$mode" = 640 ]] || bridge_fail 'candidate manifest must be mode 0400/0440/0600/0640.'
  else
    [[ "$mode" = 400 || "$mode" = 600 ]] || bridge_fail "$label must be mode 0400 or 0600."
  fi
  owner=$(stat -c '%U' "$path" 2>/dev/null) || bridge_fail "cannot inspect $label owner."
  group=$(stat -c '%G' "$path" 2>/dev/null) || bridge_fail "cannot inspect $label group."
  [[ "$owner" = root ]] || bridge_fail "$label owner is not controlled."
  if [[ "$label" = registry-token ]]; then
    [[ "$group" = root ]] || bridge_fail 'registry token group must be root.'
  fi
}

load_manifest() {
  command -v jq >/dev/null 2>&1 || bridge_fail 'jq is required.'
  command -v sha256sum >/dev/null 2>&1 || bridge_fail 'sha256sum is required.'
  secure_file "$MANIFEST_FILE" candidate-manifest
  local require_registry_token=${1:-1}
  if [[ "$require_registry_token" = 1 ]]; then
    secure_file "$REGISTRY_TOKEN_FILE" registry-token
    [[ -s "$REGISTRY_TOKEN_FILE" ]] || bridge_fail 'registry token file is empty.'
  fi
  [[ -f "$CONTROL_ROOT/current.json" && ! -L "$CONTROL_ROOT/current.json" ]] || bridge_fail 'production current ledger is missing.'

  # Snapshot the non-secret JSON once so an atomic manifest replacement cannot
  # produce a mixed set of release arguments.
  local manifest_sha_before manifest_sha_after
  manifest_sha_before=$(sha256sum "$MANIFEST_FILE" | awk '{print $1}') || bridge_fail 'candidate manifest digest cannot be read.'
  CANDIDATE_MANIFEST_JSON=$(/usr/bin/cat "$MANIFEST_FILE") || bridge_fail 'candidate manifest cannot be read.'
  manifest_sha_after=$(sha256sum "$MANIFEST_FILE" | awk '{print $1}') || bridge_fail 'candidate manifest digest cannot be read.'
  [[ "$manifest_sha_before" = "$manifest_sha_after" ]] || bridge_fail 'candidate manifest changed during the operation.'
  [[ "$manifest_sha_before" =~ ^[0-9a-f]{64}$ ]] || bridge_fail 'candidate manifest digest is invalid.'
  CANDIDATE_MANIFEST_SHA=$manifest_sha_before
  CANDIDATE_VERSION=$(jq -er '.release_version' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate release version is missing.'
  CANDIDATE_PARENT=$(jq -er '.parent_release' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate parent version is missing.'
  CANDIDATE_PARENT_SHA=$(jq -er '.parent_release_sha' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate parent SHA is missing.'
  current_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/current.json") || bridge_fail 'current ledger SHA is missing.'
  CANDIDATE_RELEASE_SHA=$(jq -er '.release_sha' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate release SHA is missing.'
  CANDIDATE_MIGRATION_SHA=$(jq -er '.migration_sha256' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate migration digest is missing.'
  CANDIDATE_BACKEND=$(jq -er '.backend_image' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate backend image is missing.'
  CANDIDATE_FRONTEND=$(jq -er '.frontend_image' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate frontend image is missing.'
  CANDIDATE_REDIS=$(jq -er '.redis_image' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'candidate Redis image is missing.'
  CANDIDATE_ACTOR=$(jq -er '.actor' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'release actor is missing.'
  CANDIDATE_REGISTRY_USER=$(jq -er '.registry_user' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'registry user is missing.'
  CANDIDATE_PLAN_VERSION=$(jq -er '.release_plan.version' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'release plan version is missing.'
  CANDIDATE_PLAN_REF=$(jq -er '.release_plan.ref' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'release plan reference is missing.'
  CANDIDATE_ROLLBACK_REASON=$(jq -er '.rollback_reason' <<<"$CANDIDATE_MANIFEST_JSON") || bridge_fail 'rollback reason is missing.'
  jq -e '.ci_attestation.main_ancestry == true and .ci_attestation.image_digests == true and .ci_attestation.migration_digest == true' <<<"$CANDIDATE_MANIFEST_JSON" >/dev/null || bridge_fail 'candidate CI attestation is incomplete.'
  current_version=$(jq -er '.release_version // empty' "$CONTROL_ROOT/current.json") || bridge_fail 'current ledger cannot be parsed.'
  [[ "$CANDIDATE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && "$CANDIDATE_PARENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || bridge_fail 'candidate version or parent is invalid.'
  [[ "$CANDIDATE_RELEASE_SHA" =~ ^[0-9a-f]{40}$ && "$CANDIDATE_PARENT_SHA" =~ ^[0-9a-f]{40}$ ]] || bridge_fail 'candidate SHA is invalid.'
  [[ "$CANDIDATE_MIGRATION_SHA" =~ ^[0-9a-f]{64}$ ]] || bridge_fail 'migration digest is invalid.'
  [[ "$CANDIDATE_BACKEND" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-backend@sha256:[0-9a-f]{64}$ ]] || bridge_fail 'backend image is not an approved digest.'
  [[ "$CANDIDATE_FRONTEND" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-frontend@sha256:[0-9a-f]{64}$ ]] || bridge_fail 'frontend image is not an approved digest.'
  [[ "$CANDIDATE_REDIS" =~ ^(redis|docker\.io/library/redis)@sha256:[0-9a-f]{64}$ ]] || bridge_fail 'Redis image is not an approved digest.'
  [[ "$CANDIDATE_ACTOR" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$CANDIDATE_REGISTRY_USER" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || bridge_fail 'manifest actor or registry user is invalid.'
  [[ "$CANDIDATE_PLAN_VERSION" = "$CANDIDATE_VERSION" && "$CANDIDATE_PLAN_REF" =~ ^[A-Za-z0-9_.:/-]{1,200}$ ]] || bridge_fail 'release plan does not correspond to candidate version.'
  [[ -n "$CANDIDATE_ROLLBACK_REASON" && "${#CANDIDATE_ROLLBACK_REASON}" -le 512 && "$CANDIDATE_ROLLBACK_REASON" != *$'\n'* && "$CANDIDATE_ROLLBACK_REASON" != *$'\r'* ]] || bridge_fail 'rollback reason is invalid.'
}

validate_deploy_binding() {
  local current_sha current_version
  secure_file "$CONTROL_ROOT/current.json" current-ledger
  current_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/current.json") || bridge_fail 'current ledger SHA is missing.'
  [[ "$CANDIDATE_PARENT_SHA" = "$current_sha" ]] || bridge_fail 'candidate parent SHA does not match production current ledger.'
  current_version=$(jq -er '.release_version // empty' "$CONTROL_ROOT/current.json") || bridge_fail 'current ledger cannot be parsed.'
  if [[ -n "$current_version" && "$current_version" != "$CANDIDATE_PARENT" ]]; then
    bridge_fail 'candidate parent version does not match production current ledger.'
  fi
}

validate_rollback_binding() {
  local current_sha previous_sha
  secure_file "$CONTROL_ROOT/current.json" current-ledger
  secure_file "$CONTROL_ROOT/previous.json" previous-ledger
  current_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/current.json") || bridge_fail 'current ledger SHA is missing.'
  previous_sha=$(jq -er '.release_sha' "$CONTROL_ROOT/previous.json") || bridge_fail 'previous ledger SHA is missing.'
  [[ "$CANDIDATE_RELEASE_SHA" = "$current_sha" ]] || bridge_fail 'rollback candidate is not the running release.'
  [[ "$CANDIDATE_PARENT_SHA" = "$previous_sha" ]] || bridge_fail 'rollback candidate parent is not the registered previous release.'
}

validate_recovery_binding() {
  secure_file "$CONTROL_ROOT/current.json" current-ledger
  [[ -x "$CONTROL_ROOT/bin/production-recovery" && ! -L "$CONTROL_ROOT/bin/production-recovery" ]] || bridge_fail 'production-recovery is not installed.'
}

run_deploy() {
  [[ "$#" -eq 0 ]] || bridge_fail 'deploy bridge accepts no arguments.'
  load_manifest
  validate_deploy_binding
  local manifest_sha
  manifest_sha=$CANDIDATE_MANIFEST_SHA
  [[ -x "$CONTROL_ROOT/bin/production-deploy" && ! -L "$CONTROL_ROOT/bin/production-deploy" ]] || bridge_fail 'production-deploy is not installed.'
  [[ -x /usr/bin/sudo && -x /usr/bin/cat ]] || bridge_fail 'required fixed bridge tools are unavailable.'
  set -o pipefail
  if [[ "$(id -u)" -eq 0 ]]; then
    /usr/bin/cat "$REGISTRY_TOKEN_FILE" | "$CONTROL_ROOT/bin/production-deploy" \
      "--release-sha=$CANDIDATE_RELEASE_SHA" "--backend-image=$CANDIDATE_BACKEND" "--frontend-image=$CANDIDATE_FRONTEND" \
      "--redis-image=$CANDIDATE_REDIS" "--migration-sha256=$CANDIDATE_MIGRATION_SHA" "--manifest-sha256=$manifest_sha" \
      "--actor=$CANDIDATE_ACTOR" "--registry-user=$CANDIDATE_REGISTRY_USER" --registry-token-stdin
  else
    /usr/bin/cat "$REGISTRY_TOKEN_FILE" | /usr/bin/sudo -n "$CONTROL_ROOT/bin/production-deploy" \
    "--release-sha=$CANDIDATE_RELEASE_SHA" "--backend-image=$CANDIDATE_BACKEND" "--frontend-image=$CANDIDATE_FRONTEND" \
    "--redis-image=$CANDIDATE_REDIS" "--migration-sha256=$CANDIDATE_MIGRATION_SHA" "--manifest-sha256=$manifest_sha" \
    "--actor=$CANDIDATE_ACTOR" "--registry-user=$CANDIDATE_REGISTRY_USER" --registry-token-stdin
  fi
}

run_recovery() {
  [[ "$#" -eq 0 ]] || bridge_fail 'recovery bridge accepts no arguments.'
  validate_recovery_binding
  if [[ "$(id -u)" -eq 0 ]]; then
    "$CONTROL_ROOT/bin/production-recovery"
  else
    /usr/bin/sudo -n "$CONTROL_ROOT/bin/production-recovery"
  fi
}

run_rollback() {
  [[ "$#" -eq 0 ]] || bridge_fail 'rollback bridge accepts no arguments.'
  load_manifest
  validate_rollback_binding
  [[ -x "$CONTROL_ROOT/bin/production-rollback" && ! -L "$CONTROL_ROOT/bin/production-rollback" ]] || bridge_fail 'production-rollback is not installed.'
  set -o pipefail
  if [[ "$(id -u)" -eq 0 ]]; then
    /usr/bin/cat "$REGISTRY_TOKEN_FILE" | "$CONTROL_ROOT/bin/production-rollback" \
      --emergency "--reason=$CANDIDATE_ROLLBACK_REASON" "--actor=$CANDIDATE_ACTOR" "--registry-user=$CANDIDATE_REGISTRY_USER" --registry-token-stdin
  else
    /usr/bin/cat "$REGISTRY_TOKEN_FILE" | /usr/bin/sudo -n "$CONTROL_ROOT/bin/production-rollback" \
    --emergency "--reason=$CANDIDATE_ROLLBACK_REASON" "--actor=$CANDIDATE_ACTOR" "--registry-user=$CANDIDATE_REGISTRY_USER" --registry-token-stdin
  fi
}
