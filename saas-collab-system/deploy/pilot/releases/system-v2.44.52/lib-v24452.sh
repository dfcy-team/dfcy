#!/usr/bin/env bash
set -euo pipefail

# Shared, non-secret helpers for the V2.44.52 controlled release. This file
# never prints values read from .env.pilot or the migration password file.

release_dir=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
version=2.44.52
parent_version=2.44.51
base_commit=db8a4dabfaac40f0baef444ff0de26abe7d98091
candidate_commit=e3dc85b948ffa7ddee9bf5ffc7e3ae16d95d4644
deployed_tag=v2.44.52-deployed
canonical_ref=${PILOT_CANONICAL_REF:-refs/baselines/canonical-deployed}

app_dir=${PILOT_APP_DIR:-/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application}
env_file=${PILOT_ENV_FILE:-$app_dir/.env.pilot}
base_compose=${PILOT_BASE_COMPOSE_FILE:-$app_dir/docker-compose.pilot-app.yml}
repo_dir=${PILOT_REPO_DIR:-$release_dir/reviewed-source}
source_dir=${PILOT_SOURCE_DIR:-$repo_dir/saas-collab-system}
evidence_dir=${PILOT_RELEASE_EVIDENCE_DIR:-$release_dir}
control_root=${PILOT_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/unified}
legacy_root=${PILOT_LEGACY_RELEASE_CONTROL_ROOT:-/opt/saas-collab/release-control/shared-version-ledger}
mirror=${PILOT_RELEASE_MIRROR:-/home/dfcy01/releases/developer-a-authorized-releases/git-mirror.git}

fail() {
  echo "V2.44.52 release blocked: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

require_absolute_path() {
  case "$1" in
    /*) ;;
    *) fail "$2 must be an absolute path." ;;
  esac
}

secure_file() {
  local path=$1
  local label=$2
  require_absolute_path "$path" "$label"
  [ -f "$path" ] || fail "$label is missing."
  [ ! -L "$path" ] || fail "$label must not be a symbolic link."
  local mode
  mode=$(stat -c '%a' "$path")
  [ "$mode" = 400 ] || [ "$mode" = 600 ] || fail "$label mode must be 0400 or 0600."
}

ensure_evidence_dir() {
  mkdir -p "$evidence_dir"
  [ ! -L "$evidence_dir" ] || fail "release evidence directory must not be a symbolic link."
  chmod 700 "$evidence_dir"
}

load_compose_chain() {
  [ -f "$env_file" ] || fail "missing protected pilot environment file."
  [ -f "$base_compose" ] || fail "missing application base compose file."
  local chain
  chain=$(env_value PILOT_RELEASE_COMPOSE_CHAIN)
  compose=(docker compose --project-name application --env-file "$env_file")
  local path
  if [ -n "$chain" ]; then
    IFS=':' read -r -a configured_chain <<< "$chain"
  else
    # Older production baselines did not persist PILOT_RELEASE_COMPOSE_CHAIN
    # in .env.pilot. The current frontend container label is Compose's
    # authoritative record of the exact files that created the running
    # mixed V2.44.50/V2.44.51 baseline; read it rather than guessing or
    # copying the protected environment file.
    local config_csv
    config_csv=$(docker inspect application-frontend-1 \
      --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' 2>/dev/null) || \
      fail "cannot read the running Compose file chain."
    [ -n "$config_csv" ] || fail "running Compose file chain is empty."
    IFS=',' read -r -a configured_chain <<< "$config_csv"
  fi
  [ "${#configured_chain[@]}" -gt 0 ] || fail "PILOT_RELEASE_COMPOSE_CHAIN is empty."
  for path in "${configured_chain[@]}"; do
    [ -n "$path" ] || fail "PILOT_RELEASE_COMPOSE_CHAIN contains an empty path."
    require_absolute_path "$path" "compose chain entry"
    [ -f "$path" ] || fail "compose chain file is missing: $path"
    [ ! -L "$path" ] || fail "compose chain file must not be a symbolic link: $path"
    compose+=( -f "$path" )
  done
  compose+=( -f "$release_dir/docker-compose.yml" )
}

read_candidate_file() {
  [ -f "$release_dir/candidate-commit.txt" ] || fail "candidate-commit.txt is missing."
  candidate=$(tr -d '[:space:]' < "$release_dir/candidate-commit.txt")
  printf '%s' "$candidate" | grep -Eq '^[0-9a-f]{40}$' || fail "candidate commit must be a full Git SHA."
  [ "$candidate" = "$candidate_commit" ] || fail "candidate commit is not the approved e3dc85b release commit."
}

runtime_image() {
  docker inspect "$1" --format '{{.Config.Image}}' 2>/dev/null || true
}

runtime_state() {
  docker inspect "$1" --format '{{.State.Status}}' 2>/dev/null || true
}

image_version() {
  docker image inspect "$1" --format '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null || true
}

image_revision() {
  docker image inspect "$1" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null || true
}

check_running_image() {
  local container=$1
  local expected_image=$2
  local expected_version=$3
  local expected_revision=${4:-}
  [ "$(runtime_state "$container")" = running ] || fail "$container is not running."
  [ "$(runtime_image "$container")" = "$expected_image" ] || fail "$container image is not $expected_image."
  [ "$(image_version "$expected_image")" = "$expected_version" ] || fail "$expected_image OCI version label is not $expected_version."
  if [ -n "$expected_revision" ]; then
    [ "$(image_revision "$expected_image")" = "$expected_revision" ] || fail "$expected_image OCI revision label is not the expected baseline."
  fi
}

application_db_env_args() {
  # The production application account is the only approved identity for the
  # schema operation. INFLUENCERS_MIGRATOR is read-only on this database and
  # must never be substituted or granted additional privileges.
  db_user=$(env_value DB_USER)
  db_name=$(env_value DB_NAME)
  db_host=$(env_value DB_HOST)
  db_port=$(env_value DB_PORT)
  db_password=$(env_value DB_PASSWORD)
  expected_db_user=$(env_value PILOT_APPLICATION_DB_USER)
  expected_db_name=$(env_value PILOT_APPLICATION_DB_NAME)
  expected_db_user=${expected_db_user:-saas_collab_pilot_user}
  expected_db_name=${expected_db_name:-saas_collab_pilot}
  [ "$db_user" = "$expected_db_user" ] || fail "application DB_USER is not the approved saas_collab_pilot_user."
  [ "$db_name" = "$expected_db_name" ] || fail "application DB_NAME is not the approved saas_collab_pilot schema."
  [ "$db_user" = saas_collab_pilot_user ] || fail "refusing a non-application database account."
  [ "$db_name" = saas_collab_pilot ] || fail "refusing a database other than saas_collab_pilot."
  [ -n "$db_password" ] || fail "application DB_PASSWORD is missing from protected .env.pilot."
  db_port=${db_port:-3306}
  printf '%s' "$db_host" | grep -Eq '^[A-Za-z0-9._:-]+$' || fail "application DB_HOST contains unexpected characters."
  printf '%s' "$db_port" | grep -Eq '^[0-9]{1,5}$' || fail "application DB_PORT is invalid."
  migration_env=(
    -e "DB_HOST=$db_host"
    -e "DB_PORT=$db_port"
    -e "DB_NAME=$db_name"
    -e "DB_USER=$db_user"
    -e "DB_PASSWORD=$db_password"
  )
}

assert_no_sensitive_bundle_files() {
  local path
  while IFS= read -r path; do
    case "$path" in
      .env.example|*/.env.example) ;;
      *.pem|*.key|*.p12|*.pfx|*.sql|*.sql.gz|.env|.env.*|*/.env|*/.env.*)
        fail "candidate source contains a forbidden sensitive file: $path" ;;
    esac
  done < <(git -C "$repo_dir" ls-tree -r --name-only "$candidate")
}
