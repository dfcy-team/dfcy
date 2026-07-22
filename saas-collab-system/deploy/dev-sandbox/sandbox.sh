#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ENV_FILE="$SCRIPT_DIR/.env.local"
ENV_EXAMPLE="$SCRIPT_DIR/env.local.example"
LOCAL_COMPOSE="$SCRIPT_DIR/docker-compose.local.yml"
RC_COMPOSE="$SCRIPT_DIR/docker-compose.rc.yml"
ACTION=${1:-start}
PROFILE=${2:-core}
CONFIRM=${3:-}

case "$PROFILE" in
  core|sales-inventory-finance-reconciliation|creator-management|procurement|integration) ;;
  *) echo "Unsupported profile: $PROFILE" >&2; exit 2 ;;
esac

random_hex() {
  openssl rand -hex "$1"
}

init_env() {
  if [ -f "$ENV_FILE" ]; then
    echo "LOCAL_SANDBOX_INIT=SKIP reason=env-exists"
    return
  fi
  command -v openssl >/dev/null 2>&1 || { echo "openssl is required" >&2; exit 1; }
  umask 077
  sed \
    -e "s/__GENERATE_DJANGO_SECRET__/$(random_hex 48)/" \
    -e "s/__GENERATE_DB_PASSWORD__/$(random_hex 24)/" \
    -e "s/__GENERATE_MYSQL_ROOT_PASSWORD__/$(random_hex 24)/" \
    -e "s/__GENERATE_DEMO_PASSWORD__/$(random_hex 20)/" \
    "$ENV_EXAMPLE" > "$ENV_FILE"
  chmod 600 "$ENV_FILE"
  echo "LOCAL_SANDBOX_INIT=PASS env=.env.local secrets=generated-not-displayed"
}

compose() {
  docker compose --env-file "$ENV_FILE" -f "$LOCAL_COMPOSE" "$@"
}

rc_compose() {
  docker compose --env-file "$ENV_FILE" -f "$RC_COMPOSE" "$@"
}

env_value() {
  key=$1
  fallback=$2
  value=$(sed -n "s/^${key}=//p" "$ENV_FILE" | head -n 1)
  printf '%s' "${value:-$fallback}"
}

wait_backend() {
  port=$(env_value LOCAL_SANDBOX_BACKEND_PORT 8000)
  attempt=0
  until curl -fsS -H 'Host: localhost' "http://127.0.0.1:${port}/api/internal/health/" >/dev/null; do
    attempt=$((attempt + 1))
    [ "$attempt" -lt 60 ] || { echo "Backend health timeout" >&2; exit 1; }
    sleep 2
  done
}

start_local() {
  init_env
  export LOCAL_SANDBOX_MODULE="$PROFILE"
  if ! compose --profile "$PROFILE" up -d --build; then
    echo "Local Sandbox build/start failed. Inspect Compose logs; for fetch failures check registry/package mirror access or Docker proxy settings." >&2
    exit 1
  fi
  wait_backend
  compose --profile "$PROFILE" --profile tooling run --rm fixture-check
  compose --profile "$PROFILE" --profile tooling run --rm seed
  echo "LOCAL_SANDBOX_START=PASS profile=$PROFILE"
}

verify_local() {
  start_local
  compose --profile "$PROFILE" config --quiet
  compose --profile "$PROFILE" exec -T backend python manage.py check
  compose --profile "$PROFILE" exec -T backend python manage.py makemigrations --check --dry-run
  compose --profile "$PROFILE" exec -T backend python manage.py sync_permissions --check
  compose --profile "$PROFILE" --profile tooling run --rm test-db-prepare

  case "$PROFILE" in
    core)
      set -- tests/test_auth_api.py tests/test_common_responses.py tests/test_permission_catalog.py tests/test_local_sandbox_seed.py ;;
    sales-inventory-finance-reconciliation)
      set -- tests/test_phase2_finance_reconciliation.py tests/test_phase3_bi_metrics.py tests/test_phase3_inventory_alerts.py tests/test_phase3_replenishment.py tests/test_local_sandbox_seed.py ;;
    creator-management)
      set -- tests/test_auth_api.py tests/test_local_sandbox_seed.py ;;
    procurement)
      set -- tests/test_purchasing_suppliers_api.py tests/test_phase2_supplier_performance.py tests/test_local_sandbox_seed.py ;;
    integration)
      set -- ;;
  esac
  compose --profile "$PROFILE" exec -T backend pytest -q "$@"
  if [ "$PROFILE" = "sales-inventory-finance-reconciliation" ] || [ "$PROFILE" = "integration" ]; then
    compose --profile "$PROFILE" exec -T backend python manage.py check_phase3_data_quality
  fi
  compose --profile "$PROFILE" exec -T -e VITE_USE_MOCK=true frontend npm test
  compose --profile "$PROFILE" exec -T frontend npm run build

  frontend_port=$(env_value LOCAL_SANDBOX_FRONTEND_PORT 5173)
  curl -fsS "http://127.0.0.1:${frontend_port}/" >/dev/null
  if [ "$PROFILE" = "creator-management" ] || [ "$PROFILE" = "integration" ]; then
    mock_port=$(env_value LOCAL_SANDBOX_CREATOR_MOCK_PORT 8091)
    curl -fsS "http://127.0.0.1:${mock_port}/mock/creator-management/creators/" | grep '"success": true' >/dev/null
    status=$(curl -sS -o /dev/null -w '%{http_code}' -X POST "http://127.0.0.1:${mock_port}/mock/creator-management/creators/")
    [ "$status" = "405" ] || { echo "Creator mock accepted a write request" >&2; exit 1; }
  fi
  echo "LOCAL_SANDBOX_VERIFY=PASS profile=$PROFILE"
}

verify_rc() {
  init_env
  docker run --rm -v "$SCRIPT_DIR:/sandbox:ro" python:3.12-alpine \
    python /sandbox/validate_rc_manifest.py --env-file /sandbox/.env.local
  rc_compose --profile release-candidate config --quiet
  if grep -Eq '^[[:space:]]*build[[:space:]]*:' "$RC_COMPOSE"; then
    echo "Release-candidate Compose must not contain build" >&2
    exit 1
  fi
  echo "LOCAL_SANDBOX_RC_VERIFY=PASS"
}

command -v docker >/dev/null 2>&1 || { echo "Docker CLI is required" >&2; exit 1; }
docker compose version >/dev/null

case "$ACTION" in
  init) init_env ;;
  start) start_local ;;
  verify) verify_local ;;
  status) init_env; compose --profile "$PROFILE" ps ;;
    stop) init_env; compose --profile "$PROFILE" down --remove-orphans ;;
  reset)
    [ "$CONFIRM" = "--confirm-reset" ] || { echo "reset requires --confirm-reset" >&2; exit 2; }
    init_env
      compose --profile "$PROFILE" down --volumes --remove-orphans
    start_local ;;
  verify-rc) verify_rc ;;
  start-rc)
    verify_rc
    rc_compose --profile release-candidate up -d
    echo "LOCAL_SANDBOX_RC_START=PASS" ;;
  *) echo "Unsupported action: $ACTION" >&2; exit 2 ;;
esac
