#!/usr/bin/env bash
set -euo pipefail

release_dir=/home/dfcy01/releases/system-v2.44.34-build-20260823
bundle=/home/dfcy01/saas-collab-v2.44.34-images.tar
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

mkdir -p "$release_dir"
cd "$app_dir"
compose=(docker compose --project-name application --env-file "$env_file" "${compose_files[@]}")

test "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.33'
test "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = 'saas-collab-frontend:v2.44.33'
test "$(sha256sum "$bundle" | awk '{print $1}')" = 'cd0e12fba9a378c573b834f37450d2c7e3fc1146145054f82b91f45f90c49647'

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$release_dir/pre-switch-containers.txt"
celery_id=$(docker inspect application-celery-1 --format '{{.Id}}')
celery_beat_id=$(docker inspect application-celery-beat-1 --format '{{.Id}}')
redis_id=$(docker inspect application-redis-1 --format '{{.Id}}')

docker load -i "$bundle" > "$release_dir/docker-load.txt"
test "$(docker image inspect saas-collab-backend:v2.44.34 --format '{{.Id}}')" = 'sha256:e1813b5fad8b941c02cbf2a9e92f6cb06ed7612428e5e68eaa850ec4392a1162'
test "$(docker image inspect saas-collab-frontend:v2.44.34 --format '{{.Id}}')" = 'sha256:caa8e136ab8242c6850e53199dc7513470e454f2e982e3c7e8a727a2d9b15a10'
"${compose[@]}" config --quiet
"${compose[@]}" config --images > "$release_dir/compose-images.txt"
grep -Fxq 'saas-collab-backend:v2.44.34' "$release_dir/compose-images.txt"
grep -Fxq 'saas-collab-frontend:v2.44.34' "$release_dir/compose-images.txt"

db_host=$(docker exec application-backend-1 printenv DB_HOST)
db_port=$(docker exec application-backend-1 printenv DB_PORT)
db_user=$(docker exec application-backend-1 printenv DB_USER)
db_password=$(docker exec application-backend-1 printenv DB_PASSWORD)
db_name=$(docker exec application-backend-1 printenv DB_NAME)
MYSQL_PWD="$db_password" mysqldump --no-tablespaces --single-transaction --quick --skip-lock-tables \
  -h "$db_host" -P "$db_port" -u "$db_user" "$db_name" \
  | gzip -c > "$release_dir/pre-deploy-v2.44.34.sql.gz"
gzip -t "$release_dir/pre-deploy-v2.44.34.sql.gz"
sha256sum "$release_dir/pre-deploy-v2.44.34.sql.gz" > "$release_dir/pre-deploy-v2.44.34.sql.gz.sha256"

"${compose[@]}" run --rm --no-deps --entrypoint python backend manage.py migrate influencers 0011 --noinput | tee "$release_dir/migrate.txt"
"${compose[@]}" up -d --no-deps backend frontend

for attempt in $(seq 1 30); do
  backend_state=$(docker inspect application-backend-1 --format '{{.State.Status}}' 2>/dev/null || true)
  frontend_state=$(docker inspect application-frontend-1 --format '{{.State.Status}}' 2>/dev/null || true)
  [[ "$backend_state" == running && "$frontend_state" == running ]] && break
  sleep 2
done

test "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = 'saas-collab-frontend:v2.44.34'
test "$(docker inspect application-celery-1 --format '{{.Id}}')" = "$celery_id"
test "$(docker inspect application-celery-beat-1 --format '{{.Id}}')" = "$celery_beat_id"
test "$(docker inspect application-redis-1 --format '{{.Id}}')" = "$redis_id"

docker exec application-backend-1 python manage.py check | tee "$release_dir/django-check.txt"
docker exec application-backend-1 python manage.py showmigrations influencers --list | tee "$release_dir/influencer-migrations.txt"
grep -Fq '[X] 0011_tiktok_video_data_layer' "$release_dir/influencer-migrations.txt"
docker exec application-backend-1 python manage.py shell -c "from apps.influencers.models import Influencer; print('INFLUENCERS=' + str(Influencer.objects.count()))" | tee "$release_dir/data-smoke.txt"
docker exec application-frontend-1 nginx -t 2>&1 | tee "$release_dir/nginx-check.txt"

for path in / /products/master /products/details /influencers /influencers/outreach-tasks /influencers/sample-fulfillments /influencers/bd-performance; do
  code=$(curl -ksS -o /dev/null -w '%{http_code}' "https://192.168.174.131:8443$path")
  printf '%s %s\n' "$path" "$code" | tee -a "$release_dir/page-status.txt"
  test "$code" = 200
done

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$release_dir/post-switch-containers.txt"
docker inspect application-backend-1 application-frontend-1 --format '{{.Name}}|{{.Id}}|{{.Config.Image}}|{{.Image}}' > "$release_dir/runtime-images.txt"
docker logs --since 15m application-backend-1 2>&1 | tail -n 500 > "$release_dir/backend-last-15m.log"
! grep -Eiq 'Traceback|Internal Server Error|CRITICAL' "$release_dir/backend-last-15m.log"
sha256sum "$release_dir"/pre-deploy-v2.44.34.sql.gz "$bundle" > "$release_dir/artifacts.sha256"
echo 'DEPLOYMENT_VALIDATION=PASS'
