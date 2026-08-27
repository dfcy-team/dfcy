#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
# shellcheck disable=SC1091
source "$SCRIPT_DIR/../lib/production-common.sh"

release_sha=""
backend_image=""
frontend_image=""
redis_image=""
migration_sha=""
actor="owner"
confirm=0

while (($#)); do
  case "$1" in
    --release-sha=*) release_sha=${1#*=} ;;
    --backend-image=*) backend_image=${1#*=} ;;
    --frontend-image=*) frontend_image=${1#*=} ;;
    --redis-image=*) redis_image=${1#*=} ;;
    --migration-sha256=*) migration_sha=${1#*=} ;;
    --actor=*) actor=${1#*=} ;;
    --confirm-current) confirm=1 ;;
    --help)
      printf '%s\n' 'Owner-only command: adopt the already-running VM version before enabling CI releases.'
      exit 0
      ;;
    *) die 'unknown adopt-current option.' ;;
  esac
  shift
done

require_control_identity
require_command jq
require_command date
load_production_env
valid_sha40 "$release_sha" || die 'current release SHA must be a full lowercase commit SHA.'
validate_approved_images "$backend_image" "$frontend_image" "$redis_image"
valid_sha256 "$migration_sha" || die 'current migration digest must be a lowercase SHA-256.'
validate_actor "$actor"
[[ "$confirm" -eq 1 ]] || die 'adoption requires --confirm-current.'

ensure_control_dirs
current_file=${PRODUCTION_CURRENT_FILE:-$CONTROL_ROOT/current.json}
[[ "$current_file" = /* ]] || die 'current metadata path must be absolute.'
if [[ -e "$current_file" ]]; then
  die 'a managed current release already exists; do not overwrite it with adoption.'
fi

completed_at=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
completed_epoch=$(date +%s)
write_json_atomic "$current_file" \
  --argjson schema_version 1 \
  --arg environment production \
  --arg release_sha "$release_sha" \
  --arg backend_image "$backend_image" \
  --arg frontend_image "$frontend_image" \
  --arg redis_image "$redis_image" \
  --arg migration_sha256 "$migration_sha" \
  --arg manifest_sha256 owner-adopted \
  --arg actor "$actor" \
  --arg action adopt \
  --arg completed_at "$completed_at" \
  --argjson completed_at_epoch "$completed_epoch" \
  '{schema_version:$schema_version,environment:$environment,release_sha:$release_sha,backend_image:$backend_image,frontend_image:$frontend_image,redis_image:$redis_image,migration_sha256:$migration_sha256,manifest_sha256:$manifest_sha256,actor:$actor,action:$action,completed_at:$completed_at,completed_at_epoch:$completed_at_epoch}'
append_audit 'adopt-current' 'success' "$release_sha" "$actor" 'owner verified the pre-existing running release'
printf 'PRODUCTION_ADOPT_CURRENT=PASS\n'
