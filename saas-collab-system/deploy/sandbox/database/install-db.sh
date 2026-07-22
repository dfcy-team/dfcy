#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.sandbox"
compose_file="$script_dir/docker-compose.sandbox-db.yml"
network_script="$script_dir/../network/apply-db-policy.sh"
network_verify="$script_dir/../network/verify-network-policy.sh"

fail() {
  echo "Sandbox database install blocked: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

file_value() {
  file=$1
  key=$2
  sed -n "s/^$key=//p" "$file" | tail -n 1 | tr -d '\r'
}

valid_digest_image() {
  printf '%s' "$1" | grep -Eq '^[A-Za-z0-9._/:@-]+@sha256:[0-9a-f]{64}$'
}

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || fail "sudo is required to apply the Sandbox database network policy."
    sudo "$@"
  fi
}

[ -f "$env_file" ] || fail "Missing $env_file. Copy env.sandbox.example and inject approved Sandbox-only secrets."
grep -Eq 'change-me|example\.(internal|com)|not-a-real' "$env_file" && fail "Placeholder values remain in $env_file."
chmod 600 "$env_file"

[ "$(env_value SANDBOX_ENVIRONMENT_CODE)" = "sandbox" ] || fail "SANDBOX_ENVIRONMENT_CODE must be sandbox."
mysql_image=$(env_value SANDBOX_MYSQL_IMAGE)
valid_digest_image "$mysql_image" || fail "SANDBOX_MYSQL_IMAGE must use an immutable sha256 digest."
case "$mysql_image" in mysql@sha256:*|docker.io/library/mysql@sha256:*) ;; *) fail "MySQL image is not an approved official digest reference." ;; esac
case "$(env_value MYSQL_DATABASE)" in
  *sandbox*) ;;
  *) fail "MYSQL_DATABASE must be dedicated to Sandbox." ;;
esac
[ "$(env_value MYSQL_USER)" != "root" ] || fail "MYSQL_USER must not be root."
mysql_password=$(env_value MYSQL_PASSWORD)
root_password=$(env_value MYSQL_ROOT_PASSWORD)
[ "${#mysql_password}" -ge 20 ] || fail "MYSQL_PASSWORD must contain at least 20 characters."
[ "${#root_password}" -ge 24 ] || fail "MYSQL_ROOT_PASSWORD must contain at least 24 characters."
[ "$mysql_password" != "$root_password" ] || fail "Application and root database passwords must be different."

db_bind_ip=$(env_value SANDBOX_DB_BIND_IP)
case "$db_bind_ip" in
  10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) ;;
  *) fail "SANDBOX_DB_BIND_IP must be a private address and must not expose MySQL publicly." ;;
esac

network_policy_file=$(env_value SANDBOX_NETWORK_POLICY_FILE)
case "$network_policy_file" in
  /*) ;;
  *) fail "SANDBOX_NETWORK_POLICY_FILE must be an absolute path." ;;
esac
[ -r "$network_policy_file" ] || fail "Sandbox network policy file is missing or unreadable: $network_policy_file"
[ "$(file_value "$network_policy_file" SANDBOX_NETWORK_APPLY)" = "YES" ] || fail "Sandbox database network policy is not approved."
[ "$(file_value "$network_policy_file" SANDBOX_DB_HOST_IP)" = "$db_bind_ip" ] || fail "SANDBOX_DB_BIND_IP does not match the approved network policy."

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" pull mysql
docker compose --env-file "$env_file" -f "$compose_file" create mysql
[ -x "$network_script" ] || fail "Missing executable database network policy script: $network_script"
run_privileged "$network_script" "$network_policy_file"
docker compose --env-file "$env_file" -f "$compose_file" up -d --wait --wait-timeout 180
[ -x "$network_verify" ] || fail "Missing executable database network verification script: $network_verify"
run_privileged "$network_verify" db "$network_policy_file"
docker compose --env-file "$env_file" -f "$compose_file" ps
