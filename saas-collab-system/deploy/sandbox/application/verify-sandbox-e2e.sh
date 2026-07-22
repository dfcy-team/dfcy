#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.sandbox"
compose_file="$script_dir/docker-compose.sandbox-app.yml"

fail() {
  echo "Sandbox JWT/API verification failed: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

command -v curl >/dev/null 2>&1 || fail "curl is required."
command -v jq >/dev/null 2>&1 || fail "jq is required."
[ -n "${SANDBOX_E2E_USERNAME:-}" ] || fail "Set SANDBOX_E2E_USERNAME for an approved short-lived internal user."
[ -n "${SANDBOX_E2E_PASSWORD_FILE:-}" ] || fail "Set SANDBOX_E2E_PASSWORD_FILE to an absolute, mode 600 secret file."
case "$SANDBOX_E2E_PASSWORD_FILE" in /*) ;; *) fail "SANDBOX_E2E_PASSWORD_FILE must be absolute." ;; esac
[ -r "$SANDBOX_E2E_PASSWORD_FILE" ] || fail "Password file is not readable."
mode=$(stat -c '%a' "$SANDBOX_E2E_PASSWORD_FILE")
[ "$mode" = "600" ] || [ "$mode" = "400" ] || fail "Password file mode must be 600 or 400."
password=$(cat "$SANDBOX_E2E_PASSWORD_FILE")
[ -n "$password" ] || fail "Password file is empty."

probe_code=$(env_value SANDBOX_E2E_SCOPE_PROBE_CODE)
printf '%s' "$probe_code" | grep -Eq '^[a-z0-9][a-z0-9-]{1,63}$' || fail "SANDBOX_E2E_SCOPE_PROBE_CODE is invalid."
[ "$probe_code" != "sandbox" ] || fail "Scope probe must differ from sandbox."
probe_result=$(docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python manage.py shell <<'PY'
import os
from apps.pilot.models import PilotEnvironment

code = os.environ["SANDBOX_E2E_SCOPE_PROBE_CODE"]
probe, created = PilotEnvironment.objects.get_or_create(
    code=code,
    defaults={"name": "Sandbox Scope Probe", "status": "controlled"},
)
if probe.name != "Sandbox Scope Probe" or probe.status != "controlled":
    raise SystemExit("Existing scope probe has unexpected attributes.")
print(f"SCOPE_PROBE_CREATED={1 if created else 0}")
PY
)
probe_created=$(printf '%s\n' "$probe_result" | sed -n 's/.*SCOPE_PROBE_CREATED=//p' | tail -n 1)

public_host=$(env_value SANDBOX_PUBLIC_HOST)
https_port=$(env_value SANDBOX_HTTPS_PORT)
ca_cert_path=$(env_value SANDBOX_CA_CERT_PATH)
base_url="https://$public_host:$https_port"
tmp_dir=$(mktemp -d)

cleanup() {
  rm -rf "$tmp_dir"
  unset password access login_payload
  if [ "$probe_created" = "1" ]; then
    docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python manage.py shell <<'PY' >/dev/null 2>&1 || true
import os
from apps.pilot.models import PilotEnvironment

PilotEnvironment.objects.filter(
    code=os.environ["SANDBOX_E2E_SCOPE_PROBE_CODE"],
    name="Sandbox Scope Probe",
).delete()
PY
  fi
}
trap cleanup EXIT HUP INT TERM

login_payload=$(jq -n --arg username "$SANDBOX_E2E_USERNAME" --arg password "$password" '{username:$username,password:$password}')
login_status=$(printf '%s' "$login_payload" | curl --silent --show-error --cacert "$ca_cert_path" \
  --resolve "$public_host:$https_port:127.0.0.1" \
  -H 'Content-Type: application/json' -o "$tmp_dir/login.json" -w '%{http_code}' \
  --data-binary @- "$base_url/api/internal/auth/login/")
[ "$login_status" = "200" ] || fail "Login returned HTTP $login_status."
access=$(jq -er '.access // .data.access // empty' "$tmp_dir/login.json") || fail "Login response does not contain an access token."
printf 'header = "Authorization: Bearer %s"\n' "$access" > "$tmp_dir/auth.conf"
chmod 600 "$tmp_dir/auth.conf"

me_status=$(curl --silent --show-error --cacert "$ca_cert_path" \
  --resolve "$public_host:$https_port:127.0.0.1" \
  --config "$tmp_dir/auth.conf" -o "$tmp_dir/me.json" -w '%{http_code}' \
  "$base_url/api/internal/auth/me/")
[ "$me_status" = "200" ] || fail "auth/me returned HTTP $me_status."
jq -e '
  .success == true and
  .data.user_type == "internal" and
  .data.is_superuser == false and
  (.data.tenant_id != null) and
  ((.data.permissions | sort) == ["pilot.readiness.view"]) and
  (.data.data_scope | length == 1) and
  .data.data_scope[0].scope_type == "custom" and
  .data.data_scope[0].config == {"environment_ids":["sandbox"]}
' "$tmp_dir/me.json" >/dev/null || fail "E2E user must be non-superuser with only pilot.readiness.view and sandbox-only custom scope."

readiness_status=$(curl --silent --show-error --cacert "$ca_cert_path" \
  --resolve "$public_host:$https_port:127.0.0.1" \
  --config "$tmp_dir/auth.conf" -o "$tmp_dir/readiness.json" -w '%{http_code}' \
  "$base_url/api/internal/pilot/readiness/?environment_id=sandbox")
[ "$readiness_status" = "200" ] || fail "Sandbox readiness returned HTTP $readiness_status."
jq -e '.success == true and .data.environment_id == "sandbox" and .data.api_status == "sandbox"' "$tmp_dir/readiness.json" >/dev/null || fail "Sandbox readiness identity is invalid."

wrong_status=$(curl --silent --show-error --cacert "$ca_cert_path" \
  --resolve "$public_host:$https_port:127.0.0.1" \
  --config "$tmp_dir/auth.conf" -o "$tmp_dir/wrong-environment.json" -w '%{http_code}' \
  "$base_url/api/internal/pilot/readiness/?environment_id=$probe_code")
[ "$wrong_status" = "403" ] || fail "Registered out-of-scope environment was not rejected with 403; HTTP $wrong_status."

"$script_dir/write-artifact-manifest.sh" pass
echo "SANDBOX_JWT_API_E2E=PASS"
echo "Verified: minimal_user=true login=200 me=200 sandbox_readiness=200 out_of_scope=403"
