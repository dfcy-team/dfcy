#!/usr/bin/env bash
# Shared, non-secret helpers for the production release control plane.
# This file is copied to a root-owned directory on the production VM by
# install-control.sh. It must never be sourced from an unreviewed checkout on
# the VM.

set -Eeuo pipefail

COMMON_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
CONTROL_ROOT="$(CDPATH= cd -- "$COMMON_DIR/.." && pwd)"
readonly CONTROL_ROOT

die() {
  printf 'Production release blocked: %s\n' "$*" >&2
  exit 1
}

log_info() {
  printf 'Production release: %s\n' "$*"
}

require_control_identity() {
  if [[ "$(id -u)" -eq 0 ]]; then
    return 0
  fi
  local runtime_user owner path mode
  runtime_user=$(id -un)
  [[ "$runtime_user" = "dfcy01" ]] || die 'the fixed release entrypoint must run as root or the dedicated dfcy01 deployment account.'
  owner=$(stat -c '%U' "$CONTROL_ROOT" 2>/dev/null) || die 'cannot inspect control-root ownership.'
  [[ "$owner" = "$runtime_user" ]] || die 'non-root operation requires a deployment-account-owned control root.'
  for path in "$CONTROL_ROOT/bin" "$CONTROL_ROOT/lib" "$CONTROL_ROOT/config"; do
    [[ -d "$path" && ! -L "$path" ]] || die 'the installed control tree is incomplete or unsafe.'
    owner=$(stat -c '%U' "$path" 2>/dev/null) || die 'cannot inspect control-tree ownership.'
    mode=$(stat -c '%a' "$path" 2>/dev/null) || die 'cannot inspect control-tree mode.'
    [[ "$owner" = "$runtime_user" ]] || die 'the installed control tree has an unexpected owner.'
    (( (8#$mode & 0022) == 0 )) || die 'the installed control tree is writable by group or other users.'
  done
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command is unavailable: $1"
}

secure_path() {
  local path=$1 label=${2:-file}
  [[ "$path" = /* ]] || die "$label must use an absolute path."
  [[ ! -L "$path" ]] || die "$label must not be a symbolic link."
  [[ -f "$path" ]] || die "$label is missing: $path"
}

secure_directory() {
  local path=$1 label=${2:-directory}
  [[ "$path" = /* ]] || die "$label must use an absolute path."
  [[ ! -L "$path" ]] || die "$label must not be a symbolic link."
  [[ -d "$path" ]] || die "$label is missing: $path"
}

secure_mode_400_or_600() {
  local path=$1 label=${2:-file} mode
  mode=$(stat -c '%a' "$path" 2>/dev/null) || die "cannot inspect $label mode."
  [[ "$mode" = 400 || "$mode" = 600 ]] || die "$label must have mode 0400 or 0600."
}

valid_sha40() {
  [[ "$1" =~ ^[0-9a-f]{40}$ ]]
}

valid_sha256() {
  [[ "$1" =~ ^[0-9a-f]{64}$ ]]
}

valid_immutable_image() {
  [[ "$1" =~ ^[A-Za-z0-9._/:@-]+@sha256:[0-9a-f]{64}$ ]]
}

validate_approved_images() {
  local backend=$1 frontend=$2 redis=$3
  valid_immutable_image "$backend" || die 'backend image must be an immutable sha256 digest.'
  valid_immutable_image "$frontend" || die 'frontend image must be an immutable sha256 digest.'
  valid_immutable_image "$redis" || die 'Redis image must be an immutable sha256 digest.'
  [[ "$backend" = ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:* ]] || die 'backend image is outside the approved GHCR repository.'
  [[ "$frontend" = ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:* ]] || die 'frontend image is outside the approved GHCR repository.'
  case "$redis" in
    redis@sha256:*|docker.io/library/redis@sha256:*) ;;
    *) die 'Redis image is outside the approved official repository.' ;;
  esac
}

resolve_runtime_env_file() {
  local pointer="$CONTROL_ROOT/config/env.path" env_file
  if [[ -f "$pointer" ]]; then
    [[ ! -L "$pointer" ]] || die 'the runtime environment pointer must not be a symbolic link.'
    IFS= read -r env_file < "$pointer" || true
  else
    env_file="$CONTROL_ROOT/config/.env.production"
  fi
  [[ -n "${env_file:-}" && "$env_file" = /* ]] || die 'the runtime environment path must be absolute.'
  secure_path "$env_file" 'production environment file'
  secure_mode_400_or_600 "$env_file" 'production environment file'
  printf '%s\n' "$env_file"
}

load_production_env() {
  require_command stat
  ENV_FILE="$(resolve_runtime_env_file)"
  # Image references are supplied by the CI command line and deliberately
  # take precedence over any stale image values left in the dotenv file.
  local ci_backend="${PRODUCTION_BACKEND_IMAGE-}"
  local ci_frontend="${PRODUCTION_FRONTEND_IMAGE-}"
  local ci_redis="${PRODUCTION_REDIS_IMAGE-}"
  # The file is root-owned and mode 0400/0600. It is an operator-managed
  # dotenv file, so sourcing it is intentional; its values are never printed.
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
  local control_env="$CONTROL_ROOT/config/control.env"
  if [[ -f "$control_env" ]]; then
    [[ ! -L "$control_env" ]] || die 'the control environment file must not be a symbolic link.'
    set -a
    # shellcheck disable=SC1090
    source "$control_env"
    set +a
  fi
  if [[ -n "$ci_backend" ]]; then export PRODUCTION_BACKEND_IMAGE="$ci_backend"; fi
  if [[ -n "$ci_frontend" ]]; then export PRODUCTION_FRONTEND_IMAGE="$ci_frontend"; fi
  if [[ -n "$ci_redis" ]]; then export PRODUCTION_REDIS_IMAGE="$ci_redis"; fi
  export ENV_FILE

  # The installed script location is authoritative. Values supplied through
  # the environment cannot redirect the control plane to an arbitrary tree.
  export PRODUCTION_CONTROL_ROOT="$CONTROL_ROOT"
  export PRODUCTION_ENV_FILE="$ENV_FILE"
  export PRODUCTION_RUNTIME_ENV_FILE="$ENV_FILE"
}

split_compose_files() {
  local raw=${PRODUCTION_COMPOSE_FILES:-$CONTROL_ROOT/production-compose.yml}
  [[ -n "$raw" ]] || die 'PRODUCTION_COMPOSE_FILES must not be empty.'
  IFS=: read -r -a COMPOSE_FILES <<< "$raw"
  [[ "${#COMPOSE_FILES[@]}" -gt 0 ]] || die 'at least one Compose file is required.'
  local file
  for file in "${COMPOSE_FILES[@]}"; do
    [[ -n "$file" && "$file" = /* ]] || die 'every Compose file path must be absolute.'
    secure_path "$file" 'Compose file'
  done
  export COMPOSE_FILES
}

init_compose() {
  require_command docker
  docker compose version >/dev/null 2>&1 || die 'Docker Compose v2 is required.'
  split_compose_files
  local project_dir=${PRODUCTION_COMPOSE_PROJECT_DIR:-$CONTROL_ROOT}
  [[ "$project_dir" = /* ]] || die 'PRODUCTION_COMPOSE_PROJECT_DIR must be absolute.'
  secure_directory "$project_dir" 'Compose project directory'
  COMPOSE=(docker compose --ansi never --project-directory "$project_dir" --env-file "$ENV_FILE")
  local file
  for file in "${COMPOSE_FILES[@]}"; do
    COMPOSE+=( -f "$file" )
  done
  export COMPOSE
}

ensure_control_dirs() {
  mkdir -p "$CONTROL_ROOT/locks" "$CONTROL_ROOT/ledger" "$CONTROL_ROOT/releases"
  chmod 700 "$CONTROL_ROOT/locks" "$CONTROL_ROOT/ledger" "$CONTROL_ROOT/releases"
  [[ ! -L "$CONTROL_ROOT" ]] || die 'control root must not be a symbolic link.'
}

acquire_release_lock() {
  require_command flock
  ensure_control_dirs
  RELEASE_LOCK_FILE=${PRODUCTION_LOCK_FILE:-$CONTROL_ROOT/locks/production-release.lock}
  [[ "$RELEASE_LOCK_FILE" = /* ]] || die 'PRODUCTION_LOCK_FILE must be absolute.'
  [[ "$RELEASE_LOCK_FILE" != *$'\n'* ]] || die 'PRODUCTION_LOCK_FILE contains a newline.'
  mkdir -p "$(dirname -- "$RELEASE_LOCK_FILE")"
  chmod 700 "$(dirname -- "$RELEASE_LOCK_FILE")"
  exec {RELEASE_LOCK_FD}>"$RELEASE_LOCK_FILE"
  chmod 600 "$RELEASE_LOCK_FILE"
  flock -n "$RELEASE_LOCK_FD" || die 'another production operation is already running.'
  export RELEASE_LOCK_FILE RELEASE_LOCK_FD
}

json_field() {
  local file=$1 filter=$2
  jq -er "$filter" "$file"
}

write_json_atomic() {
  local target=$1
  shift
  local directory tmp
  directory=$(dirname -- "$target")
  mkdir -p "$directory"
  chmod 700 "$directory"
  tmp=$(mktemp "$directory/.json.XXXXXX")
  chmod 600 "$tmp"
  if ! jq -n "$@" > "$tmp"; then
    rm -f -- "$tmp"
    die 'failed to create release metadata.'
  fi
  mv -f -- "$tmp" "$target"
  chmod 600 "$target"
}

append_audit() {
  local action=$1 status=$2 release_sha=$3 actor=$4 reason=$5
  local audit_file=${PRODUCTION_AUDIT_FILE:-$CONTROL_ROOT/ledger/audit.jsonl}
  [[ "$audit_file" = /* ]] || die 'PRODUCTION_AUDIT_FILE must be absolute.'
  mkdir -p "$(dirname -- "$audit_file")"
  chmod 700 "$(dirname -- "$audit_file")"
  [[ ! -L "$audit_file" ]] || die 'audit ledger must not be a symbolic link.'
  touch "$audit_file"
  chmod 600 "$audit_file"
  local now epoch record
  now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  epoch=$(date +%s)
  record=$(jq -nc \
    --arg schema '1' \
    --arg environment 'production' \
    --arg action "$action" \
    --arg status "$status" \
    --arg release_sha "$release_sha" \
    --arg actor "$actor" \
    --arg reason "$reason" \
    --arg occurred_at "$now" \
    --argjson occurred_at_epoch "$epoch" \
    '{schema_version:($schema|tonumber),environment:$environment,action:$action,status:$status,release_sha:$release_sha,actor:$actor,reason:$reason,occurred_at:$occurred_at,occurred_at_epoch:$occurred_at_epoch}')
  printf '%s\n' "$record" >> "$audit_file"
}

metadata_fields_are_valid() {
  local file=$1 sha backend frontend redis migration
  secure_path "$file" 'release metadata'
  sha=$(json_field "$file" '.release_sha') || return 1
  backend=$(json_field "$file" '.backend_image') || return 1
  frontend=$(json_field "$file" '.frontend_image') || return 1
  redis=$(json_field "$file" '.redis_image') || return 1
  migration=$(json_field "$file" '.migration_sha256') || return 1
  valid_sha40 "$sha" || return 1
  validate_approved_images "$backend" "$frontend" "$redis" >/dev/null 2>&1 || return 1
  valid_sha256 "$migration" || return 1
}

metadata_json_args() {
  local release_sha=$1 backend=$2 frontend=$3 redis=$4 migration=$5 manifest=$6 actor=$7 action=$8 epoch=$9 occurred_at=${10}
  printf '%s\n' \
    --argjson schema_version 1 \
    --arg environment production \
    --arg release_sha "$release_sha" \
    --arg backend_image "$backend" \
    --arg frontend_image "$frontend" \
    --arg redis_image "$redis" \
    --arg migration_sha256 "$migration" \
    --arg manifest_sha256 "$manifest" \
    --arg actor "$actor" \
    --arg action "$action" \
    --argjson completed_at_epoch "$epoch" \
    --arg completed_at "$occurred_at"
}

validate_actor() {
  [[ "$1" =~ ^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$ ]] || die 'release actor is invalid.'
}

validate_reason() {
  local reason=$1
  [[ -n "$reason" ]] || die 'a rollback reason is required.'
  [[ "${#reason}" -le 512 ]] || die 'rollback reason is too long.'
  [[ "$reason" != *$'\n'* && "$reason" != *$'\r'* ]] || die 'rollback reason must be a single line.'
}

image_revision() {
  local image=$1
  docker image inspect "$image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}'
}

runtime_migration_sha256() {
  local image=$1
  docker run --rm --entrypoint python "$image" -c \
    'from hashlib import sha256; from pathlib import Path; d=sha256(); root=Path("/app"); files=sorted(root.glob("apps/*/migrations/*.py")); [ (d.update(str(p.relative_to(root)).encode()), d.update(p.read_bytes())) for p in files ]; print(d.hexdigest())' \
    2>/dev/null
}

read_registry_token() {
  local token
  token=$(cat)
  [[ -n "$token" ]] || die 'the registry token was not supplied.'
  printf '%s' "$token"
}

docker_login_from_stdin() {
  local username=$1 token
  validate_actor "$username"
  token=$(read_registry_token)
  # Docker's credential file is temporary and is removed by the caller's
  # EXIT trap. No token is written to release metadata or the audit ledger.
  printf '%s' "$token" | docker --config "$DOCKER_CONFIG" login ghcr.io --username "$username" --password-stdin >/dev/null 2>&1 || die 'GHCR authentication failed.'
  unset token
}

remove_docker_config() {
  if [[ -n "${DOCKER_CONFIG:-}" && -d "$DOCKER_CONFIG" ]]; then
    rm -rf -- "$DOCKER_CONFIG"
  fi
}

new_docker_config() {
  DOCKER_CONFIG=$(mktemp -d "$CONTROL_ROOT/.docker-config.XXXXXX")
  chmod 700 "$DOCKER_CONFIG"
  export DOCKER_CONFIG
}
