#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.sandbox"
compose_file="$script_dir/docker-compose.sandbox-app.yml"
verification_status=${1:-runtime-verified}

fail() {
  echo "Sandbox evidence generation failed: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

secure_json_file() {
  file=$1
  label=$2
  case "$file" in /*) ;; *) fail "$label path must be absolute." ;; esac
  [ -r "$file" ] || fail "$label is missing or unreadable: $file"
  [ ! -L "$file" ] || fail "$label must not be a symbolic link."
  mode=$(stat -c '%a' "$file")
  [ "$mode" = "400" ] || [ "$mode" = "600" ] || fail "$label mode must be 400 or 600."
  [ "$(jq -er '.schema_version' "$file")" = "1" ] || fail "$label schema is invalid."
  [ "$(jq -er '.environment' "$file")" = "sandbox" ] || fail "$label environment is invalid."
  [ "$(jq -er '.verification_status' "$file")" = "pass" ] || fail "$label is not PASS."
}

case "$verification_status" in runtime-verified|pass) ;; *) fail "Unknown verification status." ;; esac

git_sha=$(env_value SANDBOX_RELEASE_GIT_SHA)
backend_image=$(env_value SANDBOX_BACKEND_IMAGE)
frontend_image=$(env_value SANDBOX_FRONTEND_IMAGE)
redis_image=$(env_value SANDBOX_REDIS_IMAGE)
approved_manifest=$(env_value SANDBOX_ARTIFACT_MANIFEST_FILE)

backend_revision=$(docker image inspect "$backend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
frontend_revision=$(docker image inspect "$frontend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[ "$backend_revision" = "$git_sha" ] || fail "Backend revision mismatch."
[ "$frontend_revision" = "$git_sha" ] || fail "Frontend revision mismatch."

migration_hash=$(docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python - <<'PY'
from hashlib import sha256
from pathlib import Path

digest = sha256()
for path in sorted(Path("/app/apps").glob("*/migrations/*.py")):
    digest.update(str(path.relative_to("/app")).encode())
    digest.update(path.read_bytes())
print(digest.hexdigest())
PY
)
approved_migration_hash=$(jq -er '.migration_sha256' "$approved_manifest")
[ "$migration_hash" = "$approved_migration_hash" ] || fail "Runtime migration hash does not match the approved artifact manifest."
approved_manifest_hash=$(sha256sum "$approved_manifest" | cut -d' ' -f1)
network_evidence_json='{}'

if [ "$verification_status" = "pass" ]; then
  app_runtime=$(env_value SANDBOX_APP_RUNTIME_NETWORK_EVIDENCE_FILE)
  app_reboot=$(env_value SANDBOX_APP_POST_REBOOT_EVIDENCE_FILE)
  db_reboot=$(env_value SANDBOX_DB_POST_REBOOT_EVIDENCE_FILE)
  source_probe=$(env_value SANDBOX_UNAPPROVED_DB_SOURCE_EVIDENCE_FILE)
  db_counter=$(env_value SANDBOX_DB_REJECT_COUNTER_EVIDENCE_FILE)
  secure_json_file "$app_runtime" "Application runtime network evidence"
  secure_json_file "$app_reboot" "Application post-reboot evidence"
  secure_json_file "$db_reboot" "Database post-reboot evidence"
  secure_json_file "$source_probe" "Unapproved source evidence"
  secure_json_file "$db_counter" "Database reject counter evidence"
  jq -e '.database_connection == "allowed" and .public_egress_connection == "rejected" and (.reject_packets_after > .reject_packets_before)' "$app_runtime" >/dev/null || fail "Application runtime network evidence is incomplete."
  jq -e '.host_role == "app" and .verification_phase == "post-reboot"' "$app_reboot" >/dev/null || fail "Application post-reboot evidence is invalid."
  jq -e '.host_role == "db" and .verification_phase == "post-reboot"' "$db_reboot" >/dev/null || fail "Database post-reboot evidence is invalid."
  jq -e '.probe == "unapproved_database_source" and .connection_result == "rejected" and (.source_ip != .approved_application_ip)' "$source_probe" >/dev/null || fail "Unapproved source evidence is invalid."
  jq -e '.probe == "database_unapproved_source_reject_counter" and (.reject_packets_after > .reject_packets_before)' "$db_counter" >/dev/null || fail "Database reject counter evidence is invalid."
  network_evidence_json=$(jq -cn \
    --arg app_runtime "$(sha256sum "$app_runtime" | cut -d' ' -f1)" \
    --arg app_reboot "$(sha256sum "$app_reboot" | cut -d' ' -f1)" \
    --arg db_reboot "$(sha256sum "$db_reboot" | cut -d' ' -f1)" \
    --arg source_probe "$(sha256sum "$source_probe" | cut -d' ' -f1)" \
    --arg db_counter "$(sha256sum "$db_counter" | cut -d' ' -f1)" \
    '{app_runtime:$app_runtime,app_post_reboot:$app_reboot,db_post_reboot:$db_reboot,unapproved_db_source:$source_probe,db_reject_counter:$db_counter}')
fi

created_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)
tmp_file=$(mktemp)
trap 'rm -f "$tmp_file"' EXIT HUP INT TERM
{
  printf '{\n'
  printf '  "schema_version": 1,\n'
  printf '  "environment": "sandbox",\n'
  printf '  "verification_status": "%s",\n' "$verification_status"
  printf '  "verified_at": "%s",\n' "$created_at"
  printf '  "git_sha": "%s",\n' "$git_sha"
  printf '  "backend_image": "%s",\n' "$backend_image"
  printf '  "frontend_image": "%s",\n' "$frontend_image"
  printf '  "redis_image": "%s",\n' "$redis_image"
  printf '  "approved_manifest_sha256": "%s",\n' "$approved_manifest_hash"
  printf '  "migration_sha256": "%s",\n' "$migration_hash"
  printf '  "network_evidence_sha256": %s\n' "$network_evidence_json"
  printf '}\n'
} > "$tmp_file"

cat "$tmp_file"
if [ "$verification_status" = "pass" ]; then
  evidence_file=$(env_value SANDBOX_VERIFICATION_EVIDENCE_FILE)
  case "$evidence_file" in /*) ;; *) fail "SANDBOX_VERIFICATION_EVIDENCE_FILE must be absolute." ;; esac
  evidence_dir=$(dirname "$evidence_file")
  [ -d "$evidence_dir" ] && [ -w "$evidence_dir" ] || fail "Sandbox evidence directory must exist and be writable: $evidence_dir"
  evidence_tmp="$evidence_file.tmp.$$"
  umask 077
  cp "$tmp_file" "$evidence_tmp"
  chmod 400 "$evidence_tmp"
  mv -f "$evidence_tmp" "$evidence_file"
  echo "SANDBOX_PASS_EVIDENCE=$evidence_file"
fi
