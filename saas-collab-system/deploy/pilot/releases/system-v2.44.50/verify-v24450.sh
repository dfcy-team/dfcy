#!/usr/bin/env bash
set -euo pipefail

# Read-only post-switch verification. It prints only statuses, IDs and paths;
# it never prints token, key, certificate or database values.

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
app_dir=${PILOT_APP_DIR:-/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application}
env_file=${PILOT_ENV_FILE:-$app_dir/.env.pilot}
base_compose=${PILOT_BASE_COMPOSE_FILE:-$app_dir/docker-compose.pilot-app.yml}
release_chain_root=${PILOT_RELEASE_CHAIN_ROOT:-/home/dfcy01/releases}
evidence_dir=${PILOT_RELEASE_EVIDENCE_DIR:-$release_dir}

fail() {
  echo "V2.44.50 verification failed: $*" >&2
  exit 1
}

candidate=$(tr -d '[:space:]' < "$release_dir/candidate-commit.txt")
printf '%s' "$candidate" | grep -Eq '^[0-9a-f]{40}$' || fail "candidate commit is invalid."
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
compose=(docker compose --project-name application --env-file "$env_file")
for chain_file in "${compose_chain[@]}"; do
  compose+=( -f "$chain_file" )
done
compose+=( -f "$release_dir/docker-compose.yml" )

check_image() {
  container=$1
  expected=$2
  image=$(docker inspect "$container" --format '{{.Config.Image}}' 2>/dev/null) || fail "missing runtime container: $container"
  [ "$image" = "$expected" ] || fail "$container image is not $expected."
  version=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')
  revision=$(docker image inspect "$image" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')
  [ "$version" = "2.44.50" ] || fail "$container image version label is not 2.44.50."
  [ "$revision" = "$candidate" ] || fail "$container image revision label does not match candidate."
}

check_image application-backend-1 saas-collab-backend:v2.44.50
check_image application-celery-1 saas-collab-backend:v2.44.50
check_image application-celery-beat-1 saas-collab-backend:v2.44.50
check_image application-frontend-1 saas-collab-frontend:v2.44.50
check_image application-custody-sidecar-1 saas-collab-custody:v2.44.50

sidecar_id=$("${compose[@]}" ps -q custody-sidecar)
[ -n "$sidecar_id" ] || fail "custody-sidecar is absent."
health=$(docker inspect "$sidecar_id" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')
[ "$health" = healthy ] || fail "custody-sidecar health is $health."
readonly_root=$(docker inspect "$sidecar_id" --format '{{.HostConfig.ReadonlyRootfs}}')
[ "$readonly_root" = true ] || fail "custody-sidecar root filesystem is writable."
security_opts=$(docker inspect "$sidecar_id" --format '{{json .HostConfig.SecurityOpt}}')
printf '%s' "$security_opts" | grep -Fq 'no-new-privileges:true' || fail "sidecar no-new-privileges is missing."
cap_drop=$(docker inspect "$sidecar_id" --format '{{json .HostConfig.CapDrop}}')
printf '%s' "$cap_drop" | grep -Fq 'ALL' || fail "sidecar capability drop is missing."
port_bindings=$(docker inspect "$sidecar_id" --format '{{json .HostConfig.PortBindings}}')
case "$port_bindings" in
  '{}'|'null'|'') ;;
  *) fail "custody-sidecar publishes a host port." ;;
esac

sidecar_mounts=$(docker inspect "$sidecar_id" --format '{{range .Mounts}}{{println .Destination}}{{end}}')
for destination in /run/secrets/custody-master.key /run/secrets/custody-tls.key /var/lib/saas-collab-custody; do
  printf '%s\n' "$sidecar_mounts" | grep -Fxq "$destination" || fail "sidecar mount missing: $destination"
done
for container in application-backend-1 application-celery-1 application-celery-beat-1; do
  mounts=$(docker inspect "$container" --format '{{range .Mounts}}{{println .Destination}}{{end}}')
  printf '%s\n' "$mounts" | grep -Fxq /run/secrets/custody-service.token || fail "$container service token mount missing."
  printf '%s\n' "$mounts" | grep -Fxq /run/secrets/custody-ca.pem || fail "$container CA mount missing."
  for forbidden in /run/secrets/custody-master.key /run/secrets/custody-tls.key /var/lib/saas-collab-custody; do
    if printf '%s\n' "$mounts" | grep -Fxq "$forbidden"; then
      fail "$container received forbidden custody mount: $forbidden"
    fi
  done
done

for container in application-backend-1 application-celery-1 application-celery-beat-1; do
  runtime_env=$(docker inspect "$container" --format '{{range .Config.Env}}{{println .}}{{end}}')
  printf '%s\n' "$runtime_env" | grep -Fxq 'LIVE_CUSTODY_BACKEND=http' || fail "$container HTTP custody backend is not enabled."
  printf '%s\n' "$runtime_env" | grep -Fxq 'LIVE_CUSTODY_SERVICE_URL=https://custody-sidecar:8443' || fail "$container custody URL is unexpected."
  printf '%s\n' "$runtime_env" | grep -Fxq 'PLATFORM_NETWORK_MODE=' || fail "$container platform network was not closed."
  printf '%s\n' "$runtime_env" | grep -Fxq 'LIVE_PLATFORM_SECURITY_APPROVED=false' || fail "$container live platform approval is enabled."
done
backend_mounts=$(docker inspect application-backend-1 --format '{{range .Mounts}}{{println .Destination}}{{end}}')
frontend_mounts=$(docker inspect application-frontend-1 --format '{{range .Mounts}}{{println .Destination}}{{end}}')
printf '%s\n' "$backend_mounts" | grep -Fxq /app/media || fail "backend product-media mount is missing."
printf '%s\n' "$frontend_mounts" | grep -Fxq /usr/share/nginx/html/media || fail "frontend product-media mount is missing."

sidecar_probe=$(cat <<'PY'
import json
import pathlib
import ssl
import urllib.request

base = "https://custody-sidecar:8443"
token = pathlib.Path("/run/secrets/custody-service.token").read_text().strip()
context = ssl.create_default_context(cafile="/run/secrets/custody-ca.pem")

def call(path, payload):
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, context=context, timeout=5) as response:
        return json.loads(response.read())

health = urllib.request.urlopen(base + "/healthz", context=context, timeout=5).read()
assert health == b'{"status":"ok"}'
secret = "v24450-synthetic-sidecar-check"
stored = call("/tokens", {"partner_key": secret, "credential_type": "pilot-verification"})
credential_id = stored["credential_id"]
token_id = stored["token_id"]
assert call("/secrets/resolve", {"reference_id": credential_id})["value"] == secret
assert call("/tokens/revoke", {"credential_id": credential_id, "token_id": token_id})["status"] == "revoked"
records = list(pathlib.Path("/var/lib/saas-collab-custody").glob("cred_*.json"))
for record in records:
    text = record.read_text()
    assert secret not in text
    assert "credentials_encrypted" in text
print("SIDECAR_HEALTH=PASS")
print("SIDECAR_ENCRYPTED_PERSISTENCE=PASS")
PY
)
printf '%s\n' "$sidecar_probe" | "${compose[@]}" exec -T custody-sidecar python -

business_probe=$(cat <<'PY'
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
import django
django.setup()
from apps.integrations.capability import approved_custody_configured, live_mode_allowed
from apps.integrations.custody import get_custody_backend, reset_custody_backend_cache

assert approved_custody_configured() is True
assert live_mode_allowed() is False
reset_custody_backend_cache()
backend = get_custody_backend()
secret = "v24450-synthetic-business-check"
reference = backend.store_secrets(partner_key=secret, credential_type="pilot-verification")
assert backend.retrieve_secret(reference["credential_id"]) == secret
assert backend.revoke(reference["credential_id"], reference["token_id"])["status"] == "revoked"
print("BUSINESS_HTTP_CUSTODY=PASS")
print("APPROVED_CUSTODY_CONFIGURED=TRUE")
print("LIVE_MODE_ALLOWED=FALSE")
PY
)
printf '%s\n' "$business_probe" | "${compose[@]}" exec -T backend python -

"${compose[@]}" exec -T backend python manage.py check >/dev/null
"${compose[@]}" exec -T backend python manage.py makemigrations --check --dry-run >/dev/null

https_port=$(env_value PILOT_HTTPS_PORT)
https_port=${https_port:-8443}
page_status=$(curl -ksS -o /dev/null -w '%{http_code}' "https://127.0.0.1:${https_port}/integrations/configs")
[ "$page_status" = 200 ] || fail "/integrations/configs returned HTTP $page_status."

for container in application-backend-1 application-celery-1 application-celery-beat-1 application-custody-sidecar-1; do
  recent_logs=$(docker logs --since 15m "$container" 2>&1 || true)
  if printf '%s\n' "$recent_logs" | grep -Eiq 'Traceback|Internal Server Error|CRITICAL'; then
    fail "$container has a recent critical error."
  fi
done

# Run the authoritative Linux-image tests, including the production MySQL
# driver check that may be unavailable on a Windows development host.
"${compose[@]}" run --rm --no-deps \
  -e DJANGO_SETTINGS_MODULE=config.settings.dev \
  -e DB_ENGINE=django.db.backends.sqlite3 \
  -e DB_NAME=/tmp/v24450-tests.sqlite3 \
  -e DB_USER= -e DB_PASSWORD= -e DB_HOST= -e DB_PORT= \
  --entrypoint pytest backend -q \
  tests/test_custody_security_gate.py tests/test_integration_credential_maintenance.py tests/test_database_settings.py
# Keep the authoritative sidecar gate non-root and independent of the
# inherited root-owned /app/pytest.ini.  /app remains on PYTHONPATH because
# the test imports the package copied into the image.
"${compose[@]}" run --rm --no-deps -w /tmp -e PYTHONPATH=/app \
  --entrypoint pytest custody-sidecar -c /dev/null /app/tests/test_custody_service.py

if [ -f "$evidence_dir/pre-deploy-migrations.txt" ]; then
  "${compose[@]}" exec -T backend python manage.py showmigrations integrations > "$evidence_dir/post-deploy-migrations.txt"
  cmp -s "$evidence_dir/pre-deploy-migrations.txt" "$evidence_dir/post-deploy-migrations.txt" || fail "integration migration state changed."
fi

echo "V2.44.50 VERIFY=PASS candidate=$candidate database_migration=none sidecar=healthy external_platform_live=closed"
