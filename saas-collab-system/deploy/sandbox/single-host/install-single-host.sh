#!/usr/bin/env sh
set -eu

# Install the Sandbox application and MySQL on one Linux ECS host. The legacy
# application/install-app.sh and database/install-db.sh remain the dual-host
# workflow; this installer is deliberately explicit about the single-host
# topology so an operator cannot accidentally mix the two layouts.
script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
sandbox_root=$(CDPATH= cd -- "$script_dir/.." && pwd)
env_file=${SANDBOX_RUNTIME_ENV_FILE:-$script_dir/.env.sandbox}
compose_file="$script_dir/docker-compose.sandbox-single-host.yml"
network_dir="$sandbox_root/network"
app_verify="$sandbox_root/application/verify-sandbox.sh"
network_verify="$network_dir/verify-network-policy.sh"

fail() {
  echo "Sandbox single-host install blocked: $*" >&2
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

is_private_ipv4() {
  case "$1" in
    10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*) return 0 ;;
    *) return 1 ;;
  esac
}

valid_cidr() {
  printf '%s' "$1" | grep -Eq '^[0-9]{1,3}(\.[0-9]{1,3}){3}/[0-9]{1,2}$'
}

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || fail "sudo is required to apply the Sandbox network policy."
    sudo "$@"
  fi
}

[ -f "$env_file" ] || fail "Missing $env_file. Copy env.sandbox.example and inject approved Sandbox-only values."
grep -Eq 'change-me|example\.(internal|com)|not-a-real' "$env_file" && fail "Placeholder values remain in $env_file."
chmod 600 "$env_file"

[ "$(env_value SANDBOX_ENVIRONMENT_CODE)" = "sandbox" ] || fail "SANDBOX_ENVIRONMENT_CODE must be sandbox."
[ "$(env_value SANDBOX_DEPLOYMENT_MODE)" = "single-host" ] || fail "SANDBOX_DEPLOYMENT_MODE must be single-host."
git_sha=$(env_value SANDBOX_RELEASE_GIT_SHA)
printf '%s' "$git_sha" | grep -Eq '^[0-9a-f]{40}$' || fail "SANDBOX_RELEASE_GIT_SHA must be a full 40-character commit SHA."

backend_image=$(env_value SANDBOX_BACKEND_IMAGE)
frontend_image=$(env_value SANDBOX_FRONTEND_IMAGE)
redis_image=$(env_value SANDBOX_REDIS_IMAGE)
mysql_image=$(env_value SANDBOX_MYSQL_IMAGE)
valid_digest_image "$backend_image" || fail "SANDBOX_BACKEND_IMAGE must use an immutable sha256 digest."
valid_digest_image "$frontend_image" || fail "SANDBOX_FRONTEND_IMAGE must use an immutable sha256 digest."
valid_digest_image "$redis_image" || fail "SANDBOX_REDIS_IMAGE must use an immutable sha256 digest."
valid_digest_image "$mysql_image" || fail "SANDBOX_MYSQL_IMAGE must use an immutable sha256 digest."
case "$backend_image" in ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:*) ;; *) fail "Backend image is not from the approved GHCR repository." ;; esac
case "$frontend_image" in ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:*) ;; *) fail "Frontend image is not from the approved GHCR repository." ;; esac
case "$redis_image" in redis@sha256:*|docker.io/library/redis@sha256:*) ;; *) fail "Redis image is not an approved official digest reference." ;; esac
case "$mysql_image" in mysql@sha256:*|docker.io/library/mysql@sha256:*) ;; *) fail "MySQL image is not an approved official digest reference." ;; esac

[ "$(env_value DJANGO_SETTINGS_MODULE)" = "config.settings.prod" ] || fail "DJANGO_SETTINGS_MODULE must be config.settings.prod."
[ "$(env_value DJANGO_DEBUG)" = "false" ] || fail "DJANGO_DEBUG must be false."
[ "$(env_value DB_ENGINE)" = "django.db.backends.mysql" ] || fail "DB_ENGINE must be django.db.backends.mysql."
[ "$(env_value INTEGRATION_ENCRYPTION_PROVIDER)" = "unconfigured-production" ] || fail "The production integration provider must remain disabled."
[ "$(env_value SANDBOX_ALLOW_REAL_PLATFORM)" = "false" ] || fail "Real platform access is forbidden in Sandbox."
[ "$(env_value SANDBOX_ALLOW_HIGH_RISK_AUTOMATION)" = "false" ] || fail "High-risk automation is forbidden in Sandbox."

case "$(env_value DB_NAME)" in *sandbox*) ;; *) fail "DB_NAME must identify a dedicated Sandbox database." ;; esac
case "$(env_value MYSQL_DATABASE)" in *sandbox*) ;; *) fail "MYSQL_DATABASE must identify a dedicated Sandbox database." ;; esac
[ "$(env_value DB_USER)" != "root" ] || fail "The application database user must not be root."
[ "$(env_value MYSQL_USER)" != "root" ] || fail "The MySQL user must not be root."
[ "$(env_value DB_PASSWORD)" = "$(env_value MYSQL_PASSWORD)" ] || fail "DB_PASSWORD and MYSQL_PASSWORD must match."
secret_key=$(env_value DJANGO_SECRET_KEY)
db_password=$(env_value DB_PASSWORD)
redis_password=$(env_value REDIS_PASSWORD)
root_password=$(env_value MYSQL_ROOT_PASSWORD)
[ "${#secret_key}" -ge 32 ] || fail "DJANGO_SECRET_KEY must contain at least 32 characters."
[ "${#db_password}" -ge 20 ] || fail "DB_PASSWORD must contain at least 20 characters."
[ "${#redis_password}" -ge 20 ] || fail "REDIS_PASSWORD must contain at least 20 characters."
[ "${#root_password}" -ge 24 ] || fail "MYSQL_ROOT_PASSWORD must contain at least 24 characters."
[ "$db_password" != "$redis_password" ] || fail "Database and Redis passwords must be different."
[ "$db_password" != "$root_password" ] || fail "Application and root database passwords must be different."

db_host=$(env_value DB_HOST)
db_bind_ip=$(env_value SANDBOX_DB_BIND_IP)
app_host_ip=$(env_value SANDBOX_APP_HOST_IP)
public_bind_ip=$(env_value SANDBOX_PUBLIC_BIND_IP)
[ "$db_host" = "10.20.40.119" ] || fail "Single-host DB_HOST must be exactly 10.20.40.119."
[ "$db_bind_ip" = "10.20.40.119" ] || fail "Single-host MySQL must bind only to 10.20.40.119."
[ "$app_host_ip" = "$db_bind_ip" ] || fail "Single-host SANDBOX_APP_HOST_IP must equal SANDBOX_DB_BIND_IP."
[ "$public_bind_ip" = "$db_bind_ip" ] || fail "Single-host HTTPS must bind to the ECS private address."
[ "$(env_value DB_PORT)" = "3307" ] || fail "Single-host DB_PORT must be 3307."
[ "$(env_value SANDBOX_DB_PORT)" = "3307" ] || fail "Single-host SANDBOX_DB_PORT must be 3307."
[ "$(env_value SANDBOX_HTTPS_PORT)" = "8543" ] || fail "Single-host HTTPS entry must be 8543."

app_subnet=$(env_value SANDBOX_APP_CONTAINER_SUBNET)
db_subnet=$(env_value SANDBOX_DB_CONTAINER_SUBNET)
valid_cidr "$app_subnet" || fail "SANDBOX_APP_CONTAINER_SUBNET must be a CIDR."
valid_cidr "$db_subnet" || fail "SANDBOX_DB_CONTAINER_SUBNET must be a CIDR."
[ "$app_subnet" != "$db_subnet" ] || fail "Application and database container networks must be different."

public_host=$(env_value SANDBOX_PUBLIC_HOST)
https_port=$(env_value SANDBOX_HTTPS_PORT)
case ",$(env_value DJANGO_ALLOWED_HOSTS)," in *",$public_host,"*) ;; *) fail "DJANGO_ALLOWED_HOSTS must include SANDBOX_PUBLIC_HOST." ;; esac
[ "$(env_value CORS_ALLOWED_ORIGINS)" = "https://$public_host:$https_port" ] || fail "CORS_ALLOWED_ORIGINS must contain only the exact Sandbox HTTPS origin."

manifest_file=$(env_value SANDBOX_ARTIFACT_MANIFEST_FILE)
case "$manifest_file" in /*) ;; *) fail "SANDBOX_ARTIFACT_MANIFEST_FILE must be an absolute path." ;; esac
[ -r "$manifest_file" ] || fail "Approved Sandbox artifact manifest is missing or unreadable: $manifest_file"
[ ! -L "$manifest_file" ] || fail "Artifact manifest must not be a symbolic link."
manifest_mode=$(stat -c '%a' "$manifest_file")
[ "$manifest_mode" = "400" ] || [ "$manifest_mode" = "600" ] || fail "Artifact manifest mode must be 400 or 600."
command -v jq >/dev/null 2>&1 || fail "jq is required to verify the approved artifact manifest."
[ "$(jq -er '.schema_version' "$manifest_file")" = "1" ] || fail "Unsupported artifact manifest schema."
[ "$(jq -er '.environment' "$manifest_file")" = "sandbox" ] || fail "Artifact manifest is not for Sandbox."
[ "$(jq -er '.git_sha' "$manifest_file")" = "$git_sha" ] || fail "Artifact manifest Git SHA does not match SANDBOX_RELEASE_GIT_SHA."
[ "$(jq -er '.backend_image' "$manifest_file")" = "$backend_image" ] || fail "Backend image does not match the approved artifact manifest."
[ "$(jq -er '.frontend_image' "$manifest_file")" = "$frontend_image" ] || fail "Frontend image does not match the approved artifact manifest."
manifest_migration_hash=$(jq -er '.migration_sha256' "$manifest_file")
printf '%s' "$manifest_migration_hash" | grep -Eq '^[0-9a-f]{64}$' || fail "Artifact manifest migration_sha256 is invalid."

network_policy_file=$(env_value SANDBOX_NETWORK_POLICY_FILE)
case "$network_policy_file" in /*) ;; *) fail "SANDBOX_NETWORK_POLICY_FILE must be an absolute path." ;; esac
[ -r "$network_policy_file" ] || fail "Sandbox network policy file is missing or unreadable: $network_policy_file"
[ "$(file_value "$network_policy_file" SANDBOX_NETWORK_APPLY)" = "YES" ] || fail "Sandbox network policy is not approved."
[ "$(file_value "$network_policy_file" SANDBOX_DEPLOYMENT_MODE)" = "single-host" ] || fail "Network policy mode must be single-host."
[ "$(file_value "$network_policy_file" SANDBOX_DB_HOST_IP)" = "$db_bind_ip" ] || fail "SANDBOX_DB_BIND_IP does not match the approved network policy."
[ "$(file_value "$network_policy_file" SANDBOX_APP_HOST_IP)" = "$app_host_ip" ] || fail "SANDBOX_APP_HOST_IP does not match the approved network policy."
[ "$(file_value "$network_policy_file" SANDBOX_APP_CONTAINER_SUBNET)" = "$app_subnet" ] || fail "Application subnet does not match the approved network policy."
[ "$(file_value "$network_policy_file" SANDBOX_DB_CONTAINER_SUBNET)" = "$db_subnet" ] || fail "Database subnet does not match the approved network policy."

tls_cert_path=$(env_value SANDBOX_TLS_CERT_PATH)
tls_key_path=$(env_value SANDBOX_TLS_KEY_PATH)
ca_cert_path=$(env_value SANDBOX_CA_CERT_PATH)
case "$tls_cert_path:$tls_key_path:$ca_cert_path" in /*:/*:/*) ;; *) fail "Sandbox TLS certificate, key, and CA paths must be absolute." ;; esac
[ -r "$tls_cert_path" ] && grep -q "BEGIN CERTIFICATE" "$tls_cert_path" || fail "Invalid TLS certificate: $tls_cert_path"
[ -r "$tls_key_path" ] && grep -Eq "BEGIN (RSA |EC )?PRIVATE KEY" "$tls_key_path" || fail "Invalid TLS private key: $tls_key_path"
[ -r "$ca_cert_path" ] && grep -q "BEGIN CERTIFICATE" "$ca_cert_path" || fail "Invalid Sandbox CA certificate: $ca_cert_path"
command -v openssl >/dev/null 2>&1 || fail "openssl is required."
openssl x509 -checkend 604800 -noout -in "$tls_cert_path" >/dev/null || fail "TLS certificate expires within seven days."
openssl verify -CAfile "$ca_cert_path" "$tls_cert_path" >/dev/null || fail "TLS certificate is not trusted by the configured Sandbox CA."
openssl x509 -checkhost "$public_host" -noout -in "$tls_cert_path" >/dev/null || fail "TLS certificate does not match SANDBOX_PUBLIC_HOST."
cert_key=$(openssl x509 -in "$tls_cert_path" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | openssl dgst -sha256)
private_key=$(openssl pkey -in "$tls_key_path" -pubout 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | openssl dgst -sha256)
[ -n "$cert_key" ] && [ "$cert_key" = "$private_key" ] || fail "TLS certificate and private key do not match."

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" pull mysql redis backend frontend
backend_revision=$(docker image inspect "$backend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
frontend_revision=$(docker image inspect "$frontend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[ "$backend_revision" = "$git_sha" ] || fail "Backend OCI revision does not match SANDBOX_RELEASE_GIT_SHA."
[ "$frontend_revision" = "$git_sha" ] || fail "Frontend OCI revision does not match SANDBOX_RELEASE_GIT_SHA."

# create first so both bridge networks exist before either host firewall policy is applied
docker compose --env-file "$env_file" -f "$compose_file" create mysql redis backend celery celery-beat frontend
[ -x "$network_dir/apply-db-policy.sh" ] || fail "Missing executable database network policy script."
[ -x "$network_dir/apply-app-policy.sh" ] || fail "Missing executable application network policy script."
run_privileged "$network_dir/apply-db-policy.sh" "$network_policy_file"
run_privileged "$network_dir/apply-app-policy.sh" "$network_policy_file"

docker compose --env-file "$env_file" -f "$compose_file" up -d --wait --wait-timeout 180 mysql redis
docker compose --env-file "$env_file" -f "$compose_file" run --rm migrate
docker compose --env-file "$env_file" -f "$compose_file" up -d --wait --wait-timeout 180 backend celery celery-beat frontend
[ -x "$network_verify" ] || fail "Missing executable network verification script."
run_privileged "$network_verify" db "$network_policy_file"

[ -x "$app_verify" ] || fail "Missing application verification script."
SANDBOX_RUNTIME_ENV_FILE="$env_file" SANDBOX_RUNTIME_COMPOSE_FILE="$compose_file" "$app_verify"
docker compose --env-file "$env_file" -f "$compose_file" ps
echo "SANDBOX_SINGLE_HOST_INSTALL=PASS db_bind=${db_bind_ip}:${db_port} https=${public_bind_ip}:${https_port} app_network=$app_subnet db_network=$db_subnet"
echo "Collect app and db post-reboot evidence after reboot; run the independent Windows probe before generating Sandbox PASS evidence."
