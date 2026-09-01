#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=${PILOT_APP_DIR:-/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application}
env_file=${PILOT_ENV_FILE:-$app_dir/.env.pilot}
base_compose=${PILOT_BASE_COMPOSE_FILE:-$app_dir/docker-compose.pilot-app.yml}
source_dir=${PILOT_SOURCE_DIR:-/opt/saas-collab/dfcy/saas-collab-system}
release_chain_root=${PILOT_RELEASE_CHAIN_ROOT:-/home/dfcy01/releases}
base_commit=61c68a59323e70dab226b5c6f441bf1bb14a00b3
base_version=2.44.49

fail() {
  echo "V2.44.50 preflight blocked: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

require_absolute_path() {
  value=$1
  label=$2
  case "$value" in
    /*) ;;
    *) fail "$label must be an absolute path." ;;
  esac
}

secure_file() {
  value=$1
  label=$2
  require_absolute_path "$value" "$label"
  [ -f "$value" ] || fail "$label is missing."
  [ ! -L "$value" ] || fail "$label must not be a symbolic link."
  mode=$(stat -c '%a' "$value")
  [ "$mode" = "400" ] || [ "$mode" = "600" ] || fail "$label mode must be 400 or 600."
}

secure_readonly_file() {
  value=$1
  label=$2
  require_absolute_path "$value" "$label"
  [ -f "$value" ] || fail "$label is missing."
  [ ! -L "$value" ] || fail "$label must not be a symbolic link."
  mode=$(stat -c '%a' "$value")
  [ "$mode" = "400" ] || fail "$label must be owner-read-only (0400)."
}

secure_data_dir() {
  value=$1
  label=$2
  require_absolute_path "$value" "$label"
  if [ -e "$value" ]; then
    [ -d "$value" ] || fail "$label is not a directory."
    [ ! -L "$value" ] || fail "$label must not be a symbolic link."
    mode=$(stat -c '%a' "$value")
    [ "$mode" = "700" ] || fail "$label must have mode 0700."
  else
    parent=$(dirname -- "$value")
    [ -d "$parent" ] || fail "$label parent directory is missing."
    [ ! -L "$parent" ] || fail "$label parent must not be a symbolic link."
  fi
}

[ -f "$env_file" ] || fail "missing pilot environment file."
[ -f "$base_compose" ] || fail "missing pilot base compose file."
[ -f "$release_dir/docker-compose.yml" ] || fail "missing V2.44.50 compose override."
[ -f "$release_dir/Dockerfile.backend" ] || fail "missing backend delta Dockerfile."
[ -f "$release_dir/Dockerfile.custody" ] || fail "missing custody delta Dockerfile."
[ -f "$release_dir/Dockerfile.frontend" ] || fail "missing frontend delta Dockerfile."
[ -f "$release_dir/candidate-commit.txt" ] || fail "candidate-commit.txt is required."

compose_chain=(
  "$base_compose"
  "$release_chain_root/system-v2.44.24-build-20260814/docker-compose.yml"
  "$release_chain_root/system-v2.44.26-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.28-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.29-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.30-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.31-build-20260815/docker-compose.yml"
  "$release_chain_root/system-v2.44.32-build-20260817/docker-compose.yml"
  "$release_chain_root/system-v2.44.33-build-20260821/docker-compose.yml"
  "$release_chain_root/system-v2.44.34-build-20260823/docker-compose.yml"
  "$release_chain_root/system-v2.44.35-build-20260823/docker-compose.yml"
  "$release_chain_root/system-v2.44.37-build-20260823/docker-compose.yml"
  "$release_chain_root/system-v2.44.38-build-20260824/docker-compose.yml"
  "$release_chain_root/architect-developer-a-v2.44.47-r2-20260828/docker-compose.v2.44.47.yml"
  "$release_chain_root/system-v2.44.48-build-20260828/docker-compose.yml"
  "$release_chain_root/system-v2.44.49-reviewed-pr59-20260831/docker-compose.yml"
)
for chain_file in "${compose_chain[@]}"; do
  [ -f "$chain_file" ] || fail "required V2.44.49 compose chain file is missing: $chain_file"
done

release_revision=$(tr -d '[:space:]' < "$release_dir/candidate-commit.txt")
printf '%s' "$release_revision" | grep -Eq '^[0-9a-f]{40}$' || fail "candidate commit must be a full Git SHA."

command -v docker >/dev/null 2>&1 || fail "docker is required."
command -v git >/dev/null 2>&1 || fail "git is required to verify the source base."
git -C "$source_dir" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "source checkout is unavailable."
git -C "$source_dir" cat-file -e "$base_commit^{commit}" 2>/dev/null || fail "V2.44.49 base commit is unavailable in source checkout."
git -C "$source_dir" cat-file -e "$release_revision^{commit}" 2>/dev/null || fail "candidate commit is unavailable in source checkout."
git -C "$source_dir" merge-base --is-ancestor "$base_commit" "$release_revision" || fail "candidate is not based on V2.44.49 base commit."

while IFS= read -r changed_path; do
  [ -n "$changed_path" ] || continue
  case "$changed_path" in
    backend/apps/integrations/custody.py|\
    backend/apps/integrations/capability.py|\
    backend/apps/integrations/net_guard.py|\
    backend/apps/integrations/custody_service.py|\
    backend/apps/integrations/file_custody.py|\
    backend/config/settings/base.py|\
    backend/requirements.txt|\
    backend/tests/test_custody_service.py|\
    backend/tests/test_custody_security_gate.py|\
    .env.example|\
    docs/06_release/system_v2.44.50.md|\
    deploy/pilot/releases/system-v2.44.50/*) ;;
    *) fail "candidate contains an unapproved path: $changed_path" ;;
  esac
done < <(git -C "$source_dir" diff --name-only "$base_commit" "$release_revision")

for required in \
  backend/apps/integrations/custody.py \
  backend/apps/integrations/capability.py \
  backend/apps/integrations/net_guard.py \
  backend/apps/integrations/custody_service.py \
  backend/config/settings/base.py; do
  [ -f "$source_dir/$required" ] || fail "source file is missing: $required"
done

# The running four-service baseline must be exactly V2.44.49 before a delta is
# built.  Compare immutable OCI labels as well as the visible version label.
for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1; do
  image=$(docker inspect "$container" --format '{{.Config.Image}}' 2>/dev/null) || fail "missing baseline container: $container"
  version=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.version"}}' 2>/dev/null) || fail "cannot inspect baseline image for $container"
  revision=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' 2>/dev/null) || fail "cannot inspect baseline revision for $container"
  [ "$version" = "$base_version" ] || fail "$container is not running V2.44.49."
  [ "$revision" = "$base_commit" ] || fail "$container baseline revision is not the approved V2.44.49 commit."
done

master_key_path=$(env_value PILOT_CUSTODY_MASTER_KEY_PATH)
data_path=$(env_value PILOT_CUSTODY_DATA_PATH)
service_token_path=$(env_value PILOT_CUSTODY_SERVICE_TOKEN_PATH)
ca_path=$(env_value PILOT_CUSTODY_CA_PATH)
tls_cert_path=$(env_value PILOT_CUSTODY_TLS_CERT_PATH)
tls_key_path=$(env_value PILOT_CUSTODY_TLS_KEY_PATH)
sidecar_uid=$(env_value PILOT_CUSTODY_SIDECAR_UID)
sidecar_gid=$(env_value PILOT_CUSTODY_SIDECAR_GID)
[ -n "$master_key_path" ] || fail "PILOT_CUSTODY_MASTER_KEY_PATH is required."
[ -n "$data_path" ] || fail "PILOT_CUSTODY_DATA_PATH is required."
[ -n "$service_token_path" ] || fail "PILOT_CUSTODY_SERVICE_TOKEN_PATH is required."
[ -n "$ca_path" ] || fail "PILOT_CUSTODY_CA_PATH is required."
[ -n "$tls_cert_path" ] || fail "PILOT_CUSTODY_TLS_CERT_PATH is required."
[ -n "$tls_key_path" ] || fail "PILOT_CUSTODY_TLS_KEY_PATH is required."
sidecar_uid=${sidecar_uid:-1000}
sidecar_gid=${sidecar_gid:-1000}
printf '%s' "$sidecar_uid" | grep -Eq '^[1-9][0-9]{0,8}$' || fail "PILOT_CUSTODY_SIDECAR_UID must be a non-root numeric UID."
printf '%s' "$sidecar_gid" | grep -Eq '^[1-9][0-9]{0,8}$' || fail "PILOT_CUSTODY_SIDECAR_GID must be a non-root numeric GID."
secure_readonly_file "$master_key_path" "custody master key"
secure_data_dir "$data_path" "custody data directory"
secure_file "$service_token_path" "custody service token"
secure_file "$ca_path" "custody CA bundle"
secure_file "$tls_cert_path" "custody TLS certificate"
secure_readonly_file "$tls_key_path" "custody TLS private key"

# The override hard-closes external marketplace traffic.  Reject an unsafe
# pilot env before Compose interpolation so a later override cannot hide it.
case "$(env_value PLATFORM_NETWORK_MODE | tr '[:upper:]' '[:lower:]')" in
  approved-live-test|live|production) fail "pilot environment enables external platform network mode." ;;
esac
case "$(env_value LIVE_PLATFORM_SECURITY_APPROVED | tr '[:upper:]' '[:lower:]')" in
  1|true|yes|on) fail "pilot environment enables live platform security approval." ;;
esac
[ -z "$(env_value LIVE_PLATFORM_ALLOWED_HOSTS)" ] || fail "pilot environment must not provide live platform hosts."

compose=(docker compose --project-name application --env-file "$env_file")
for chain_file in "${compose_chain[@]}"; do
  compose+=( -f "$chain_file" )
done
compose+=( -f "$release_dir/docker-compose.yml" )
"${compose[@]}" config --quiet

# No release-owned Dockerfile may copy or run a migration.  Match only actual
# Docker instructions, so explanatory words such as "migration-free" do not
# self-block the release. This check does not execute any database command.
if grep -Eiq '(RUN[[:space:]]+.*(migrat|\.sql)|COPY[[:space:]]+.*(migrations|\.sql))' \
  "$release_dir/Dockerfile.backend" "$release_dir/Dockerfile.custody" "$release_dir/Dockerfile.frontend"; then
  fail "V2.44.50 image delta contains a migration or SQL operation."
fi

echo "V2.44.50 PREFLIGHT=PASS base=$base_version base_commit=$base_commit candidate=$release_revision database_migration=none external_platform_live=closed"
