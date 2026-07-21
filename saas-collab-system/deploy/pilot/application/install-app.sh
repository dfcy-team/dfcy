#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.pilot"
compose_file="$script_dir/docker-compose.pilot-app.yml"

if [ ! -f "$env_file" ]; then
  echo "Missing $env_file. Copy env.pilot.example and obtain real values from the approved secret store." >&2
  exit 1
fi

if grep -Eq 'change-me|example\.internal' "$env_file"; then
  echo "Placeholder values remain in $env_file. Set host addresses and approved secrets before installation." >&2
  exit 1
fi

chmod 600 "$env_file"

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

tls_cert_path=$(env_value PILOT_TLS_CERT_PATH)
tls_key_path=$(env_value PILOT_TLS_KEY_PATH)
if [ -z "$tls_cert_path" ] || [ -z "$tls_key_path" ]; then
  echo "PILOT_TLS_CERT_PATH and PILOT_TLS_KEY_PATH are required." >&2
  exit 1
fi
case "$tls_cert_path:$tls_key_path" in
  /*:/*) ;;
  *) echo "Pilot TLS certificate and key paths must be absolute." >&2; exit 1 ;;
esac
if [ ! -r "$tls_cert_path" ] || ! grep -q "BEGIN CERTIFICATE" "$tls_cert_path"; then
  echo "Pilot TLS certificate is missing, unreadable, or invalid: $tls_cert_path" >&2
  exit 1
fi
if [ ! -r "$tls_key_path" ] || ! grep -Eq "BEGIN (RSA |EC )?PRIVATE KEY" "$tls_key_path"; then
  echo "Pilot TLS private key is missing, unreadable, or invalid: $tls_key_path" >&2
  exit 1
fi
if ! command -v openssl >/dev/null 2>&1; then
  echo "openssl is required to validate the pilot TLS certificate." >&2
  exit 1
fi
if ! openssl x509 -checkend 86400 -noout -in "$tls_cert_path" >/dev/null; then
  echo "Pilot TLS certificate is invalid or expires within 24 hours." >&2
  exit 1
fi
if ! openssl pkey -check -noout -in "$tls_key_path" >/dev/null 2>&1; then
  echo "Pilot TLS private key cannot be parsed." >&2
  exit 1
fi
cert_public_key=$(openssl x509 -in "$tls_cert_path" -pubkey -noout | openssl pkey -pubin -outform DER 2>/dev/null | openssl dgst -sha256)
key_public_key=$(openssl pkey -in "$tls_key_path" -pubout 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | openssl dgst -sha256)
if [ -z "$cert_public_key" ] || [ "$cert_public_key" != "$key_public_key" ]; then
  echo "Pilot TLS certificate and private key do not match." >&2
  exit 1
fi

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
docker compose --env-file "$env_file" -f "$compose_file" build backend frontend
docker compose --env-file "$env_file" -f "$compose_file" up -d redis
docker compose --env-file "$env_file" -f "$compose_file" run --rm migrate
docker compose --env-file "$env_file" -f "$compose_file" up -d backend celery celery-beat frontend
docker compose --env-file "$env_file" -f "$compose_file" ps
