#!/usr/bin/env bash
set -euo pipefail

release_dir=/home/dfcy01/releases/system-v2.44.37-build-20260823
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
  -f /home/dfcy01/releases/system-v2.44.34-build-20260823/docker-compose.yml
  -f /home/dfcy01/releases/system-v2.44.35-build-20260823/docker-compose.yml
  -f "$release_dir/docker-compose.yml"
)

mkdir -p "$release_dir"
cd "$app_dir"
compose=(docker compose --project-name application --env-file "$env_file" "${compose_files[@]}")

test "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = 'saas-collab-frontend:v2.44.35'
test "$(docker inspect application-celery-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-celery-beat-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'

backend_id=$(docker inspect application-backend-1 --format '{{.Id}}')
celery_id=$(docker inspect application-celery-1 --format '{{.Id}}')
celery_beat_id=$(docker inspect application-celery-beat-1 --format '{{.Id}}')
redis_id=$(docker inspect application-redis-1 --format '{{.Id}}')

"${compose[@]}" config --quiet
"${compose[@]}" config --images > "$release_dir/compose-images.txt"
grep -Fxq 'saas-collab-frontend:v2.44.37' "$release_dir/compose-images.txt"
"${compose[@]}" up -d --no-deps frontend

for attempt in $(seq 1 30); do
  frontend_state=$(docker inspect application-frontend-1 --format '{{.State.Status}}' 2>/dev/null || true)
  [[ "$frontend_state" == running ]] && break
  sleep 2
done

test "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = 'saas-collab-frontend:v2.44.37'
test "$(docker inspect application-backend-1 --format '{{.Id}}')" = "$backend_id"
test "$(docker inspect application-celery-1 --format '{{.Id}}')" = "$celery_id"
test "$(docker inspect application-celery-beat-1 --format '{{.Id}}')" = "$celery_beat_id"
test "$(docker inspect application-redis-1 --format '{{.Id}}')" = "$redis_id"

docker exec application-frontend-1 nginx -t 2>&1 | tee "$release_dir/nginx-check.txt"
for path in / /products/master /products/details /influencers/bd-performance /system/roles; do
  code=$(curl -ksS -o /dev/null -w '%{http_code}' "https://192.168.174.131:8443$path")
  printf '%s %s\n' "$path" "$code" | tee -a "$release_dir/page-status.txt"
  test "$code" = 200
done

main_asset=$(docker exec application-frontend-1 sh -c \
  "sed -n 's/.*src=\"\\/\\(assets\\/index-[^\"]*\\.js\\)\".*/\\1/p' /usr/share/nginx/html/index.html")
test -n "$main_asset"
for label in 工作台 产品开发 全球刊登 经营分析 经营决策 销售管理 达人管理 流程协同 业务协同 RPA协同 API数据接入 财务中心 报表中心 基础档案 系统治理 治理与试点 BD绩效; do
  docker exec application-frontend-1 grep -Fq "$label" "/usr/share/nginx/html/$main_asset"
done

layout_css=$(docker exec application-frontend-1 sh -c "ls /usr/share/nginx/html/assets/MainLayout-*.css | head -n 1")
role_asset=$(docker exec application-frontend-1 sh -c "ls /usr/share/nginx/html/assets/RolePermissionMatrix-*.js | head -n 1")
test -n "$layout_css"
test -n "$role_asset"
docker exec application-frontend-1 grep -Fq 'background:#173550' "$layout_css"
docker exec application-frontend-1 grep -Fq -- '--el-menu-text-color: #dce8f2' "$layout_css"
docker exec application-frontend-1 grep -Fq 'background:#2f6f9f' "$layout_css"
docker exec application-frontend-1 grep -Fq '其他操作权限' "$role_asset"
docker exec application-frontend-1 grep -Fq '目录未返回' "$role_asset"

docker inspect application-frontend-1 --format '{{.Name}}|{{.Id}}|{{.Config.Image}}|{{.Image}}' > "$release_dir/runtime-image.txt"
docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$release_dir/post-switch-containers.txt"
docker logs --since 15m application-frontend-1 2>&1 | tail -n 500 > "$release_dir/frontend-last-15m.log"
! grep -Eiq 'emerg|alert|crit' "$release_dir/frontend-last-15m.log"
echo 'DEPLOYMENT_VALIDATION=PASS'
