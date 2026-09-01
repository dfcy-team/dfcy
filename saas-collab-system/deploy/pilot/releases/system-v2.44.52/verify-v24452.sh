#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
# shellcheck source=lib-v24452.sh
. "$release_dir/lib-v24452.sh"

fail() {
  echo "V2.44.52 verification failed: $*" >&2
  exit 1
}

ensure_evidence_dir
read_candidate_file
load_compose_chain

check_running_image application-backend-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-celery-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-celery-beat-1 saas-collab-backend:v2.44.52 2.44.52 "$candidate"
check_running_image application-frontend-1 saas-collab-frontend:v2.44.52 2.44.52 "$candidate"
check_running_image application-custody-sidecar-1 saas-collab-custody:v2.44.50 2.44.50

sidecar_id=$("${compose[@]}" ps -q custody-sidecar 2>/dev/null || true)
[ -n "$sidecar_id" ] || fail "custody-sidecar is absent."
sidecar_health=$(docker inspect "$sidecar_id" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')
[ "$sidecar_health" = healthy ] || fail "custody sidecar health is $sidecar_health."
sidecar_ports=$(docker inspect "$sidecar_id" --format '{{json .HostConfig.PortBindings}}')
case "$sidecar_ports" in '{}'|'null'|'') ;; *) fail "custody sidecar publishes a host port." ;; esac
readonly_root=$(docker inspect "$sidecar_id" --format '{{.HostConfig.ReadonlyRootfs}}')
[ "$readonly_root" = true ] || fail "custody sidecar root filesystem is writable."
security_opts=$(docker inspect "$sidecar_id" --format '{{json .HostConfig.SecurityOpt}}')
printf '%s' "$security_opts" | grep -Fq 'no-new-privileges:true' || fail "custody sidecar no-new-privileges is missing."
cap_drop=$(docker inspect "$sidecar_id" --format '{{json .HostConfig.CapDrop}}')
printf '%s' "$cap_drop" | grep -Fq 'ALL' || fail "custody sidecar capability drop is missing."

for container in application-backend-1 application-celery-1 application-celery-beat-1; do
  mounts=$(docker inspect "$container" --format '{{range .Mounts}}{{println .Destination}}{{end}}')
  printf '%s\n' "$mounts" | grep -Fxq /run/secrets/custody-service.token || fail "$container lacks the custody service-token mount."
  printf '%s\n' "$mounts" | grep -Fxq /run/secrets/custody-ca.pem || fail "$container lacks the custody CA mount."
  for forbidden in /run/secrets/custody-master.key /run/secrets/custody-tls.key /var/lib/saas-collab-custody; do
    if printf '%s\n' "$mounts" | grep -Fxq "$forbidden"; then
      fail "$container received forbidden custody mount: $forbidden"
    fi
  done
done
sidecar_mounts=$(docker inspect "$sidecar_id" --format '{{range .Mounts}}{{println .Destination}}{{end}}')
for required in /run/secrets/custody-master.key /run/secrets/custody-tls.key /var/lib/saas-collab-custody; do
  printf '%s\n' "$sidecar_mounts" | grep -Fxq "$required" || fail "custody sidecar mount is missing: $required"
done

# The migration service is profile-gated and must not remain running after the
# one explicit migration invocation.
if [ -n "$(docker ps -q --filter name=application-migrate-1 2>/dev/null || true)" ]; then
  fail "migration service is unexpectedly running."
fi

"${compose[@]}" exec -T backend python manage.py check > "$evidence_dir/post-django-check.txt" 2>&1 \
  || fail "Django system check failed."
"${compose[@]}" exec -T backend python manage.py makemigrations --check --dry-run > "$evidence_dir/post-makemigrations-check.txt" 2>&1 \
  || fail "Django makemigrations check failed."
"${compose[@]}" exec -T backend python manage.py showmigrations masterdata > "$evidence_dir/post-migrations-masterdata.txt" 2>&1 \
  || fail "post-deploy migration state could not be read."
grep -Eq '^\[[Xx]\][[:space:]]+0009_warehouse_service_platform' "$evidence_dir/post-migrations-masterdata.txt" \
  || fail "masterdata.0009_warehouse_service_platform is not applied."

# Verify the data-side effects without returning credentials, tokens, names,
# or row contents to the host.
"${compose[@]}" exec -T backend python - > "$evidence_dir/post-masterdata-probe.txt" 2>&1 <<'PY'
import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
import django

django.setup()
from apps.masterdata.models import PlatformMaster, WarehouseMaster

myjf = list(
    PlatformMaster.objects.filter(code__iexact="myjf").values_list("code", "platform_type")
)
assert all(platform_type == "warehouse_third_party" for _, platform_type in myjf)
expected = {
    "owned": "warehouse_owned",
    "third_party": "warehouse_third_party",
    "platform": "warehouse_platform",
}
for warehouse in WarehouseMaster.objects.select_related("service_platform").all():
    if warehouse.service_platform_id:
        assert warehouse.service_platform.platform_type == expected[warehouse.warehouse_type]
print(f"MYJF_CLASSIFICATION_ROWS={len(myjf)}")
print(f"WAREHOUSE_SERVICE_BINDINGS={WarehouseMaster.objects.filter(service_platform_id__isnull=False).count()}")
print("MASTERDATA_0009_RUNTIME_PROBE=PASS")
PY

https_port=$(env_value PILOT_HTTPS_PORT)
https_port=${https_port:-8443}
root_status=$(curl -ksS -o /dev/null -w '%{http_code}' "https://127.0.0.1:${https_port}/" || true)
[ "$root_status" = 200 ] || fail "application root returned HTTP $root_status."
printf 'GET / %s\n' "$root_status" > "$evidence_dir/page-status.txt"

for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1 application-custody-sidecar-1; do
  if docker logs --since 10m "$container" 2>&1 | grep -Eiq 'Traceback|Internal Server Error|CRITICAL'; then
    fail "$container has a recent critical error."
  fi
done

docker inspect application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1 application-custody-sidecar-1 \
  --format '{{.Name}}|{{.Id}}|{{.Config.Image}}|{{.Image}}|{{.State.Status}}' > "$evidence_dir/runtime-images.txt"
printf 'VERIFY=PASS\nVERSION=%s\nCUSTODY_VERSION=2.44.50\nDATABASE_MIGRATION=masterdata.0009_warehouse_service_platform\n' "$version" \
  > "$evidence_dir/verification-status.txt"
chmod 600 "$evidence_dir/verification-status.txt" "$evidence_dir/runtime-images.txt"
echo "V2.44.52 VERIFY=PASS candidate=$candidate migration=masterdata.0009_warehouse_service_platform custody=2.44.50:healthy"
