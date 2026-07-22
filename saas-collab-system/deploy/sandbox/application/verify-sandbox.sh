#!/usr/bin/env sh
set -eu

script_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
env_file="$script_dir/.env.sandbox"
compose_file="$script_dir/docker-compose.sandbox-app.yml"
network_verify="$script_dir/../network/verify-network-policy.sh"
runtime_network_probe="$script_dir/probe-runtime-network.sh"

fail() {
  echo "Sandbox verification failed: $*" >&2
  exit 1
}

env_value() {
  sed -n "s/^$1=//p" "$env_file" | tail -n 1 | tr -d '\r'
}

run_privileged() {
  if [ "$(id -u)" -eq 0 ]; then "$@"; else sudo "$@"; fi
}

[ -f "$env_file" ] || fail "Missing $env_file."
[ "$(env_value SANDBOX_ENVIRONMENT_CODE)" = "sandbox" ] || fail "Environment code is not sandbox."
[ "$(env_value SANDBOX_ALLOW_REAL_PLATFORM)" = "false" ] || fail "Real platform gate is open."
[ "$(env_value SANDBOX_ALLOW_HIGH_RISK_AUTOMATION)" = "false" ] || fail "High-risk automation gate is open."
[ "$(env_value DJANGO_SETTINGS_MODULE)" = "config.settings.prod" ] || fail "Production settings are not selected."
[ "$(env_value DB_ENGINE)" = "django.db.backends.mysql" ] || fail "MySQL is not selected."

docker compose --env-file "$env_file" -f "$compose_file" config --quiet
running=$(docker compose --env-file "$env_file" -f "$compose_file" ps --services --status running)
for service in redis backend celery celery-beat frontend; do
  echo "$running" | grep -qx "$service" || fail "$service is not running."
done

docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python manage.py check --deploy
docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python manage.py makemigrations --check --dry-run
docker compose --env-file "$env_file" -f "$compose_file" exec -T backend python manage.py shell <<'PY'
from django.conf import settings
from apps.pilot.models import PilotEnvironment
import os

assert settings.DEBUG is False
assert settings.DATABASES["default"]["ENGINE"] == "django.db.backends.mysql"
assert settings.SESSION_COOKIE_SECURE is True
assert settings.CSRF_COOKIE_SECURE is True
assert settings.SECURE_SSL_REDIRECT is True
assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
expected_origin = f"https://{os.environ['SANDBOX_PUBLIC_HOST']}:{os.environ['SANDBOX_HTTPS_PORT']}"
assert settings.CORS_ALLOWED_ORIGINS == [expected_origin]
assert set(settings.ALLOWED_HOSTS) <= {os.environ["SANDBOX_PUBLIC_HOST"], "backend", "localhost", "127.0.0.1"}
environment = PilotEnvironment.objects.get(code="sandbox")
assert environment.name == "Sandbox"
assert environment.status == "controlled"
print("SANDBOX_RUNTIME_SETTINGS=PASS")
PY

policy_file=$(env_value SANDBOX_NETWORK_POLICY_FILE)
[ -x "$network_verify" ] || fail "Network verification script is missing."
run_privileged "$network_verify" app "$policy_file"
[ -x "$runtime_network_probe" ] || fail "Runtime network probe script is missing."
run_privileged "$runtime_network_probe" "$env_file"

command -v curl >/dev/null 2>&1 || fail "curl is required for HTTPS verification."
public_host=$(env_value SANDBOX_PUBLIC_HOST)
https_port=$(env_value SANDBOX_HTTPS_PORT)
ca_cert_path=$(env_value SANDBOX_CA_CERT_PATH)
health_response=$(curl --fail --silent --show-error \
  --cacert "$ca_cert_path" \
  --resolve "$public_host:$https_port:127.0.0.1" \
  "https://$public_host:$https_port/api/internal/health/")
echo "$health_response" | grep -Eq '"success"[[:space:]]*:[[:space:]]*true' || fail "Health response does not use the success envelope."

echo "SANDBOX_VERIFY=PASS"
"$script_dir/write-artifact-manifest.sh" runtime-verified
