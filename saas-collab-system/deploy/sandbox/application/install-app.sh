#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.sandbox"
compose_file="$script_dir/docker-compose.sandbox-app.yml"
network_script="$script_dir/../network/apply-app-policy.sh"

fail() {
  echo "Sandbox install blocked: $*" >&2
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

contains_csv_value() {
  values=$1
  wanted=$2
  case ",$values," in
    *",$wanted,"*) return 0 ;;
    *) return 1 ;;
  esac
}

csv_values_are_allowed() {
  values=$1
  allowed=$2
  old_ifs=$IFS
  IFS=,
  for value in $values; do
    case ",$allowed," in
      *",$value,"*) ;;
      *) IFS=$old_ifs; return 1 ;;
    esac
  done
  IFS=$old_ifs
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

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || fail "sudo is required to apply the Sandbox network policy."
    sudo "$@"
  fi
}

[ -f "$env_file" ] || fail "Missing $env_file. Copy env.sandbox.example and inject approved Sandbox-only secrets."
grep -Eq 'change-me|example\.(internal|com)|not-a-real' "$env_file" && fail "Placeholder values remain in $env_file."
chmod 600 "$env_file"

[ "$(env_value SANDBOX_ENVIRONMENT_CODE)" = "sandbox" ] || fail "SANDBOX_ENVIRONMENT_CODE must be sandbox."
git_sha=$(env_value SANDBOX_RELEASE_GIT_SHA)
printf '%s' "$git_sha" | grep -Eq '^[0-9a-f]{40}$' || fail "SANDBOX_RELEASE_GIT_SHA must be a full 40-character commit SHA."

backend_image=$(env_value SANDBOX_BACKEND_IMAGE)
frontend_image=$(env_value SANDBOX_FRONTEND_IMAGE)
redis_image=$(env_value SANDBOX_REDIS_IMAGE)
valid_digest_image "$backend_image" || fail "SANDBOX_BACKEND_IMAGE must use an immutable sha256 digest."
valid_digest_image "$frontend_image" || fail "SANDBOX_FRONTEND_IMAGE must use an immutable sha256 digest."
valid_digest_image "$redis_image" || fail "SANDBOX_REDIS_IMAGE must use an immutable sha256 digest."
case "$backend_image" in ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:*) ;; *) fail "Backend image is not from the approved GHCR repository." ;; esac
case "$frontend_image" in ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:*) ;; *) fail "Frontend image is not from the approved GHCR repository." ;; esac
case "$redis_image" in redis@sha256:*|docker.io/library/redis@sha256:*) ;; *) fail "Redis image is not an approved official digest reference." ;; esac

[ "$(env_value DJANGO_SETTINGS_MODULE)" = "config.settings.prod" ] || fail "DJANGO_SETTINGS_MODULE must be config.settings.prod."
[ "$(env_value DJANGO_DEBUG)" = "false" ] || fail "DJANGO_DEBUG must be false."
[ "$(env_value DB_ENGINE)" = "django.db.backends.mysql" ] || fail "DB_ENGINE must be django.db.backends.mysql."
[ "$(env_value INTEGRATION_ENCRYPTION_PROVIDER)" = "unconfigured-production" ] || fail "The production integration provider must remain disabled."
[ "$(env_value SANDBOX_ALLOW_REAL_PLATFORM)" = "false" ] || fail "Real platform access is forbidden in Sandbox."
[ "$(env_value SANDBOX_ALLOW_HIGH_RISK_AUTOMATION)" = "false" ] || fail "High-risk automation is forbidden in Sandbox."

case "$(env_value DB_NAME)" in
  *sandbox*) ;;
  *) fail "DB_NAME must identify a dedicated Sandbox database." ;;
esac
[ "$(env_value DB_USER)" != "root" ] || fail "The application database user must not be root."
db_host=$(env_value DB_HOST)
is_private_ipv4 "$db_host" || fail "DB_HOST must be a private IPv4 address."

secret_key=$(env_value DJANGO_SECRET_KEY)
db_password=$(env_value DB_PASSWORD)
redis_password=$(env_value REDIS_PASSWORD)
[ "${#secret_key}" -ge 32 ] || fail "DJANGO_SECRET_KEY must contain at least 32 characters."
[ "${#db_password}" -ge 20 ] || fail "DB_PASSWORD must contain at least 20 characters."
[ "${#redis_password}" -ge 20 ] || fail "REDIS_PASSWORD must contain at least 20 characters."
[ "$db_password" != "$redis_password" ] || fail "Database and Redis passwords must be different."

public_host=$(env_value SANDBOX_PUBLIC_HOST)
https_port=$(env_value SANDBOX_HTTPS_PORT)
contains_csv_value "$(env_value DJANGO_ALLOWED_HOSTS)" "$public_host" || fail "DJANGO_ALLOWED_HOSTS must include SANDBOX_PUBLIC_HOST."
contains_csv_value "$(env_value DJANGO_ALLOWED_HOSTS)" "backend" || fail "DJANGO_ALLOWED_HOSTS must include backend."
contains_csv_value "$(env_value DJANGO_ALLOWED_HOSTS)" "localhost" || fail "DJANGO_ALLOWED_HOSTS must include localhost for internal health checks."
csv_values_are_allowed "$(env_value DJANGO_ALLOWED_HOSTS)" "$public_host,backend,localhost,127.0.0.1" || fail "DJANGO_ALLOWED_HOSTS contains an unapproved host or wildcard."
[ "$(env_value CORS_ALLOWED_ORIGINS)" = "https://$public_host:$https_port" ] || fail "CORS_ALLOWED_ORIGINS must contain only the exact Sandbox HTTPS origin."

manifest_file=$(env_value SANDBOX_ARTIFACT_MANIFEST_FILE)
case "$manifest_file" in
  /*) ;;
  *) fail "SANDBOX_ARTIFACT_MANIFEST_FILE must be an absolute path." ;;
esac
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
case "$network_policy_file" in
  /*) ;;
  *) fail "SANDBOX_NETWORK_POLICY_FILE must be an absolute path." ;;
esac
[ -r "$network_policy_file" ] || fail "Sandbox network policy file is missing or unreadable: $network_policy_file"
[ "$(file_value "$network_policy_file" SANDBOX_NETWORK_APPLY)" = "YES" ] || fail "Sandbox network policy is not approved for application."
[ "$(file_value "$network_policy_file" SANDBOX_DB_HOST_IP)" = "$db_host" ] || fail "DB_HOST does not match the approved Sandbox network policy."

tls_cert_path=$(env_value SANDBOX_TLS_CERT_PATH)
tls_key_path=$(env_value SANDBOX_TLS_KEY_PATH)
ca_cert_path=$(env_value SANDBOX_CA_CERT_PATH)
case "$tls_cert_path:$tls_key_path:$ca_cert_path" in
  /*:/*:/*) ;;
  *) fail "Sandbox TLS certificate, key, and CA paths must be absolute." ;;
esac
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
docker compose --env-file "$env_file" -f "$compose_file" pull redis backend frontend

backend_revision=$(docker image inspect "$backend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
frontend_revision=$(docker image inspect "$frontend_image" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')
[ "$backend_revision" = "$git_sha" ] || fail "Backend OCI revision does not match SANDBOX_RELEASE_GIT_SHA."
[ "$frontend_revision" = "$git_sha" ] || fail "Frontend OCI revision does not match SANDBOX_RELEASE_GIT_SHA."

docker compose --env-file "$env_file" -f "$compose_file" create redis backend celery celery-beat frontend
[ -x "$network_script" ] || fail "Missing executable network policy script: $network_script"
run_privileged "$network_script" "$network_policy_file"

docker compose --env-file "$env_file" -f "$compose_file" up -d --wait --wait-timeout 180 redis
docker compose --env-file "$env_file" -f "$compose_file" run --rm migrate
"$script_dir/register-sandbox-environment.sh"
docker compose --env-file "$env_file" -f "$compose_file" up -d --wait --wait-timeout 180 backend celery celery-beat frontend
docker compose --env-file "$env_file" -f "$compose_file" ps

"$script_dir/verify-sandbox.sh"
echo "Sandbox application installed. Run verify-sandbox-e2e.sh with an approved short-lived account."
