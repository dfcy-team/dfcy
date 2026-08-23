#!/usr/bin/env bash
set -euo pipefail

release_dir=/home/dfcy01/releases/system-v2.44.34-build-20260823
app_dir=/opt/saas-collab/dfcy/saas-collab-system/deploy/pilot/application
env_file="$app_dir/.env.pilot"
base_compose="$app_dir/docker-compose.pilot-app.yml"
compose_files=(
  -f "$base_compose"
  -f /home/dfcy01/releases/system-v2.44.24-build-20260814/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.26-build-20260815/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.28-build-20260815/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.29-build-20260815/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.30-build-20260815/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.31-build-20260815/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.32-build-20260817/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.33-build-20260821/docker-compose.yml
  -f "$release_dir/docker-compose.yml"
)

cd "$app_dir"
compose=(docker compose --project-name application --env-file "$env_file" "${compose_files[@]}")

test "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = 'saas-collab-frontend:v2.44.34'
test "$(docker inspect application-celery-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.8'
test "$(docker inspect application-celery-beat-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.8'
redis_id=$(docker inspect application-redis-1 --format '{{.Id}}')

"${compose[@]}" config --quiet
"${compose[@]}" up -d --no-deps celery celery-beat

for attempt in $(seq 1 30); do
  celery_state=$(docker inspect application-celery-1 --format '{{.State.Status}}' 2>/dev/null || true)
  beat_state=$(docker inspect application-celery-beat-1 --format '{{.State.Status}}' 2>/dev/null || true)
  [[ "$celery_state" == running && "$beat_state" == running ]] && break
  sleep 2
done

test "$(docker inspect application-celery-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-celery-beat-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-redis-1 --format '{{.Id}}')" = "$redis_id"

docker exec application-celery-1 celery -A config inspect registered --timeout=10 \
  | tee "$release_dir/celery-registered.txt"
grep -Fq 'influencers.refresh_affiliate_order_attributions' "$release_dir/celery-registered.txt"
grep -Fq 'influencers.mark_overdue_sample_fulfillments' "$release_dir/celery-registered.txt"

docker logs --since 10m application-celery-1 2>&1 | tail -n 500 > "$release_dir/celery-last-10m.log"
docker logs --since 10m application-celery-beat-1 2>&1 | tail -n 500 > "$release_dir/celery-beat-last-10m.log"
! grep -Eiq 'Traceback|CRITICAL|Received unregistered task' "$release_dir/celery-last-10m.log"
! grep -Eiq 'Traceback|CRITICAL' "$release_dir/celery-beat-last-10m.log"

docker inspect application-celery-1 application-celery-beat-1 \
  --format '{{.Name}}|{{.Id}}|{{.Config.Image}}|{{.Image}}' \
  > "$release_dir/celery-runtime-images.txt"
echo 'CELERY_DEPLOYMENT_VALIDATION=PASS'
