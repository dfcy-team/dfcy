#!/usr/bin/env bash
# CI-side immutable build hand-off. The VM must not run this script to build
# source. It validates CI outputs and emits a non-secret candidate manifest;
# image construction/push and main-ancestry checks remain CI-owned stages.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "$SCRIPT_DIR/../../../.." && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/release-common.sh"

fail() { release_fail "$@"; }

[[ "${CI:-}" = true || "${GITHUB_ACTIONS:-}" = true ]] || fail 'build hand-off is CI-only; the production VM must not build source.'
command -v git >/dev/null 2>&1 || fail 'git is required.'
command -v jq >/dev/null 2>&1 || fail 'jq is required.'
command -v sha256sum >/dev/null 2>&1 || fail 'sha256sum is required.'
command -v mktemp >/dev/null 2>&1 || fail 'mktemp is required.'

release_sha=${PILOT_RELEASE_SHA:-}
parent_sha=${PILOT_PARENT_RELEASE_SHA:-}
backend_image=${PILOT_BACKEND_IMAGE:-}
frontend_image=${PILOT_FRONTEND_IMAGE:-}
redis_image=${PILOT_REDIS_IMAGE:-}
migration_sha=${PILOT_MIGRATION_SHA256:-}
actor=${PILOT_RELEASE_ACTOR:-}
registry_user=${PILOT_REGISTRY_USER:-}
candidate_output=${PILOT_CANDIDATE_OUTPUT:-}

[[ "$release_sha" =~ ^[0-9a-f]{40}$ ]] || fail 'PILOT_RELEASE_SHA must be a full lowercase SHA.'
[[ "$parent_sha" = "$PARENT_BASE_COMMIT" ]] || fail 'PILOT_PARENT_RELEASE_SHA must equal the reviewed V2.44.58 baseline commit.'
[[ "$(git -C "$REPO_ROOT" rev-parse --verify HEAD 2>/dev/null)" = "$release_sha" ]] || fail 'CI checkout HEAD does not equal PILOT_RELEASE_SHA.'
[[ "$backend_image" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-backend@sha256:[0-9a-f]{64}$ ]] || fail 'backend image must be an immutable approved digest.'
[[ "$frontend_image" =~ ^ghcr\.io/dfcy-team/dfcy/saas-collab-frontend@sha256:[0-9a-f]{64}$ ]] || fail 'frontend image must be an immutable approved digest.'
[[ "$redis_image" =~ ^(redis|docker\.io/library/redis)@sha256:[0-9a-f]{64}$ ]] || fail 'Redis image must be an immutable approved digest.'
[[ "$migration_sha" =~ ^[0-9a-f]{64}$ ]] || fail 'migration digest must be a lowercase SHA-256.'
[[ "$actor" =~ ^[A-Za-z0-9_.-]{1,64}$ && "$registry_user" =~ ^[A-Za-z0-9_.-]{1,128}$ ]] || fail 'release actor/registry user is invalid.'
[[ "$candidate_output" = /* && "$candidate_output" != *$'\n'* && "$candidate_output" != *$'\r'* ]] || fail 'PILOT_CANDIDATE_OUTPUT must be an absolute newline-free path.'
[[ -d "$(dirname -- "$candidate_output")" && ! -L "$(dirname -- "$candidate_output")" ]] || fail 'candidate output directory is missing or unsafe.'

# The CI job that invokes this script must set these booleans only after the
# corresponding protected-main, OCI label, and migration-tree gates pass.
[[ "${PILOT_MAIN_ANCESTRY_ATTESTED:-}" = true ]] || fail 'main ancestry gate was not attested.'
[[ "${PILOT_IMAGE_DIGESTS_ATTESTED:-}" = true ]] || fail 'image digest gate was not attested.'
[[ "${PILOT_MIGRATION_DIGEST_ATTESTED:-}" = true ]] || fail 'migration digest gate was not attested.'

tmp=$(mktemp "$(dirname -- "$candidate_output")/.candidate-v24459.XXXXXX")
trap 'rm -f -- "$tmp"' EXIT HUP INT TERM
jq -n \
  --arg release_sha "$release_sha" \
  --arg parent_sha "$parent_sha" \
  --arg backend "$backend_image" \
  --arg frontend "$frontend_image" \
  --arg redis "$redis_image" \
  --arg migration "$migration_sha" \
  --arg actor "$actor" \
  --arg registry_user "$registry_user" \
  --arg source_base_commit "$PARENT_BASE_COMMIT" \
  --arg plan_ref 'release/system-v2.44.59' \
  '{schema_version:1,template_only:false,release_version:"2.44.59",parent_release:"2.44.58",source_base_commit:$source_base_commit,release_sha:$release_sha,parent_release_sha:$parent_sha,backend_image:$backend,frontend_image:$frontend,redis_image:$redis,migration_sha256:$migration,actor:$actor,registry_user:$registry_user,release_plan:{version:"2.44.59",ref:$plan_ref},rollback_reason:"V2.44.59 emergency rollback approved by architecture",ci_attestation:{main_ancestry:true,image_digests:true,migration_digest:true},candidate_manifest_file:"/etc/saas-collab/runner/approved-candidate.json"}' > "$tmp" || fail 'candidate manifest generation failed.'
chmod 640 "$tmp"
mv -f -- "$tmp" "$candidate_output"
trap - EXIT HUP INT TERM
printf 'V24459_BUILD_HANDOFF=PASS\n'
printf 'V24459_CANDIDATE_OUTPUT=%s\n' "$candidate_output"
printf 'V24459_CANDIDATE_SHA256=%s\n' "$(sha256sum "$candidate_output" | awk '{print $1}')"
printf 'V24459_BUILD_NOTE=CI must atomically stage this candidate on the target with stage-approved-candidate.sh after the VM current ledger is verified.\n'
