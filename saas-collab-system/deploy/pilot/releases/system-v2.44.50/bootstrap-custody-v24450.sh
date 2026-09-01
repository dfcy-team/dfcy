#!/usr/bin/env bash
set -euo pipefail

# Run once on the application VM as the owner of the release controls (root
# is required because this prepares ownership for the non-root sidecar).  This
# script never creates or prints a secret; all secret material must already be
# present at the paths supplied by .env.pilot.

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=${PILOT_APP_DIR:-/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application}
env_file=${PILOT_ENV_FILE:-$app_dir/.env.pilot}

fail() {
  echo "V2.44.50 custody bootstrap blocked: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

absolute() {
  case "$1" in
    /*) ;;
    *) fail "$2 must be an absolute path." ;;
  esac
}

[ "$(id -u)" = 0 ] || fail "run as root to prepare the sidecar identity."
[ -f "$env_file" ] || fail "missing pilot environment file."

sidecar_uid=$(env_value PILOT_CUSTODY_SIDECAR_UID)
sidecar_gid=$(env_value PILOT_CUSTODY_SIDECAR_GID)
sidecar_uid=${sidecar_uid:-1000}
sidecar_gid=${sidecar_gid:-1000}
printf '%s' "$sidecar_uid" | grep -Eq '^[1-9][0-9]{0,8}$' || fail "sidecar UID must be non-root numeric."
printf '%s' "$sidecar_gid" | grep -Eq '^[1-9][0-9]{0,8}$' || fail "sidecar GID must be non-root numeric."

master_key_path=$(env_value PILOT_CUSTODY_MASTER_KEY_PATH)
data_path=$(env_value PILOT_CUSTODY_DATA_PATH)
service_token_path=$(env_value PILOT_CUSTODY_SERVICE_TOKEN_PATH)
ca_path=$(env_value PILOT_CUSTODY_CA_PATH)
tls_cert_path=$(env_value PILOT_CUSTODY_TLS_CERT_PATH)
tls_key_path=$(env_value PILOT_CUSTODY_TLS_KEY_PATH)

for pair in \
  "master key:$master_key_path" \
  "data directory:$data_path" \
  "service token:$service_token_path" \
  "CA bundle:$ca_path" \
  "TLS certificate:$tls_cert_path" \
  "TLS private key:$tls_key_path"; do
  label=${pair%%:*}
  value=${pair#*:}
  [ -n "$value" ] || fail "$label path is required."
  absolute "$value" "$label path"
done

for path in "$master_key_path" "$service_token_path" "$ca_path" "$tls_cert_path" "$tls_key_path"; do
  [ -f "$path" ] || fail "required credential/TLS file is missing."
  [ ! -L "$path" ] || fail "credential/TLS files must not be symbolic links."
done

[ ! -e "$data_path" ] || [ -d "$data_path" ] || fail "custody data path is not a directory."
[ ! -L "$data_path" ] || fail "custody data path must not be a symbolic link."
install -d -m 700 -o "$sidecar_uid" -g "$sidecar_gid" "$data_path"

# Existing encrypted records are owned by the sidecar identity and remain
# private.  A symlink in this dedicated directory is a hard failure rather
# than something to follow during permission repair.
if find "$data_path" -xdev -type l -print -quit | grep -q .; then
  fail "custody data directory contains a symbolic link."
fi
find "$data_path" -xdev -type d -exec chown "$sidecar_uid:$sidecar_gid" {} + -exec chmod 700 {} +
find "$data_path" -xdev -type f -exec chown "$sidecar_uid:$sidecar_gid" {} + -exec chmod 600 {} +

# Secret and private-key files are owner-read-only.  The sidecar runs with the
# same non-root numeric identity, while the business containers receive only
# their own read-only service-token/CA mounts from the compose override.
for path in "$master_key_path" "$service_token_path" "$ca_path" "$tls_cert_path" "$tls_key_path"; do
  chown "$sidecar_uid:$sidecar_gid" "$path"
  chmod 400 "$path"
done

chmod 700 "$data_path"
echo "V2.44.50 CUSTODY_BOOTSTRAP=PASS sidecar_uid=$sidecar_uid sidecar_gid=$sidecar_gid"
