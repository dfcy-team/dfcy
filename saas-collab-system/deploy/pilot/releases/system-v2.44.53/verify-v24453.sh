#!/usr/bin/env bash
set -euo pipefail

release_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
candidate=37eaa4a3344be9d3a3c6897e6e4936972a429c40
fail() { echo "V2.44.53 verification failed: $*" >&2; exit 1; }

for container in application-backend-1 application-celery-1 application-celery-beat-1; do
  [ "$(docker inspect "$container" --format '{{.Config.Image}}')" = saas-collab-backend:v2.44.53 ] || fail "$container image mismatch"
done
[ "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = saas-collab-frontend:v2.44.53 ] || fail "frontend image mismatch"
[ "$(docker image inspect saas-collab-backend:v2.44.53 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$candidate" ] || fail "backend revision mismatch"
[ "$(docker image inspect saas-collab-frontend:v2.44.53 --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" = "$candidate" ] || fail "frontend revision mismatch"

pre_custody=$(sed -n 's/^application-custody-sidecar-1|//p' "$release_dir/pre-switch-container-ids.txt")
pre_redis=$(sed -n 's/^application-redis-1|//p' "$release_dir/pre-switch-container-ids.txt")
[ "$(docker inspect application-custody-sidecar-1 --format '{{.Id}}')" = "$pre_custody" ] || fail "custody sidecar was recreated"
[ "$(docker inspect application-redis-1 --format '{{.Id}}')" = "$pre_redis" ] || fail "redis was recreated"
[ "$(docker inspect application-custody-sidecar-1 --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}')" = healthy ] || fail "custody sidecar is not healthy"

docker exec application-backend-1 python manage.py check > "$release_dir/post-django-check.txt" 2>&1 || fail "Django check failed"
docker exec application-backend-1 python manage.py makemigrations --check --dry-run > "$release_dir/post-makemigrations-check.txt" 2>&1 || fail "migration consistency failed"
docker exec application-backend-1 python manage.py showmigrations influencers > "$release_dir/post-influencer-migrations.txt" 2>&1 || fail "influencer migrations could not be read"

https_port=$(sed -n 's/^PILOT_HTTPS_PORT=//p' /opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application/.env.pilot | tail -n 1 | tr -d '\r')
https_port=${https_port:-8443}
for path in / /influencers /influencers/outreach-tasks /influencers/bd-performance /products/master /master-data/products /system/users; do
  code=$(curl -ksS -o /dev/null -w '%{http_code}' "https://127.0.0.1:${https_port}${path}" || true)
  [ "$code" = 200 ] || fail "$path returned HTTP $code"
  printf 'GET %s %s\n' "$path" "$code" >> "$release_dir/page-status.txt"
done
api_code=$(curl -ksS -o /dev/null -w '%{http_code}' "https://127.0.0.1:${https_port}/api/internal/influencers/" || true)
[ "$api_code" = 401 ] || fail "unauthenticated influencer API returned HTTP $api_code"
printf 'GET /api/internal/influencers/ %s\n' "$api_code" >> "$release_dir/page-status.txt"

for container in application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1 application-custody-sidecar-1; do
  if docker logs --since 10m "$container" 2>&1 | grep -Eiq 'Traceback|Internal Server Error|CRITICAL'; then fail "$container has a recent critical error"; fi
done
docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$release_dir/post-switch-containers.txt"
printf 'VERIFY=PASS\nVERSION=2.44.53\nDATABASE_MIGRATION=NONE\nCUSTODY_RECREATED=false\nREDIS_RECREATED=false\n' > "$release_dir/verification-status.txt"
chmod 600 "$release_dir/verification-status.txt" "$release_dir/post-switch-containers.txt"
echo "V2.44.53 VERIFY=PASS candidate=$candidate migration=NONE"
