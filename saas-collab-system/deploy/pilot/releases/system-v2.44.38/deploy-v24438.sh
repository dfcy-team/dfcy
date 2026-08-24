#!/usr/bin/env bash
set -euo pipefail

release_dir=/home/dfcy01/releases/system-v2.44.38-build-20260824
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
  -f /home/dfcy01/releases/system-v2.44.37-build-20260823/docker-compose.yml
  -f "$release_dir/docker-compose.yml"
)

mkdir -p "$release_dir"
cd "$app_dir"
compose=(docker compose --project-name application --env-file "$env_file" "${compose_files[@]}")

test "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-celery-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-celery-beat-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.34'
test "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = 'saas-collab-frontend:v2.44.37'
docker image inspect saas-collab-backend:v2.44.38 >/dev/null
docker image inspect saas-collab-frontend:v2.44.38 >/dev/null

backend_old_id=$(docker inspect application-backend-1 --format '{{.Id}}')
celery_old_id=$(docker inspect application-celery-1 --format '{{.Id}}')
celery_beat_old_id=$(docker inspect application-celery-beat-1 --format '{{.Id}}')
frontend_old_id=$(docker inspect application-frontend-1 --format '{{.Id}}')
redis_id=$(docker inspect application-redis-1 --format '{{.Id}}')

docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$release_dir/pre-switch-containers.txt"
"${compose[@]}" config --quiet
"${compose[@]}" config --images > "$release_dir/compose-images.txt"
grep -Fxq 'saas-collab-backend:v2.44.38' "$release_dir/compose-images.txt"
grep -Fxq 'saas-collab-frontend:v2.44.38' "$release_dir/compose-images.txt"

"${compose[@]}" run --rm --no-deps --entrypoint python backend manage.py check | tee "$release_dir/django-check.txt"
"${compose[@]}" run --rm --no-deps --entrypoint python backend manage.py makemigrations --check --dry-run | tee "$release_dir/makemigrations-check.txt"
"${compose[@]}" run --rm --no-deps --entrypoint python backend manage.py showmigrations integrations permissions reports commerce | tee "$release_dir/pre-migration-state.txt"
for target in 'integrations 0016' 'commerce 0001' 'permissions 0031' 'reports 0006'; do
  read -r app migration <<< "$target"
  "${compose[@]}" run --rm --no-deps --entrypoint python backend manage.py migrate "$app" "$migration" --plan
done | tee "$release_dir/migrate-plan.txt"
"${compose[@]}" run --rm --no-deps \
  -e DJANGO_SETTINGS_MODULE=config.settings.dev \
  -e DB_ENGINE=django.db.backends.sqlite3 \
  -e DB_NAME=/tmp/v24438-test.sqlite3 \
  -e DB_USER= \
  -e DB_PASSWORD= \
  -e DB_HOST= \
  -e DB_PORT= \
  --entrypoint pytest backend -q --nomigrations \
  tests/test_commerce_fact_contract.py \
  tests/test_commerce_models.py \
  tests/test_sales_management.py | tee "$release_dir/backend-targeted-tests.txt"

if [[ "${PRECHECK_ONLY:-0}" == "1" ]]; then
  echo 'PREDEPLOY_VALIDATION=PASS'
  exit 0
fi

db_host=$(docker exec application-backend-1 printenv DB_HOST)
db_port=$(docker exec application-backend-1 printenv DB_PORT)
db_user=$(docker exec application-backend-1 printenv DB_USER)
db_password=$(docker exec application-backend-1 printenv DB_PASSWORD)
db_name=$(docker exec application-backend-1 printenv DB_NAME)
MYSQL_PWD="$db_password" mysqldump --no-tablespaces --single-transaction --quick --skip-lock-tables \
  -h "$db_host" -P "$db_port" -u "$db_user" "$db_name" \
  | gzip -c > "$release_dir/pre-deploy-v2.44.38.sql.gz"
gzip -t "$release_dir/pre-deploy-v2.44.38.sql.gz"
sha256sum "$release_dir/pre-deploy-v2.44.38.sql.gz" > "$release_dir/pre-deploy-v2.44.38.sql.gz.sha256"

for target in 'integrations 0016' 'commerce 0001' 'permissions 0031' 'reports 0006'; do
  read -r app migration <<< "$target"
  "${compose[@]}" run --rm --no-deps --entrypoint python backend manage.py migrate "$app" "$migration" --noinput
done | tee "$release_dir/migrate.txt"
"${compose[@]}" up -d --no-deps backend celery celery-beat frontend

for attempt in $(seq 1 45); do
  backend_state=$(docker inspect application-backend-1 --format '{{.State.Status}}' 2>/dev/null || true)
  celery_state=$(docker inspect application-celery-1 --format '{{.State.Status}}' 2>/dev/null || true)
  celery_beat_state=$(docker inspect application-celery-beat-1 --format '{{.State.Status}}' 2>/dev/null || true)
  frontend_state=$(docker inspect application-frontend-1 --format '{{.State.Status}}' 2>/dev/null || true)
  [[ "$backend_state" == running && "$celery_state" == running && "$celery_beat_state" == running && "$frontend_state" == running ]] && break
  sleep 2
done

test "$(docker inspect application-backend-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.38'
test "$(docker inspect application-celery-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.38'
test "$(docker inspect application-celery-beat-1 --format '{{.Config.Image}}')" = 'saas-collab-backend:v2.44.38'
test "$(docker inspect application-frontend-1 --format '{{.Config.Image}}')" = 'saas-collab-frontend:v2.44.38'
test "$(docker inspect application-redis-1 --format '{{.Id}}')" = "$redis_id"
test "$(docker inspect application-backend-1 --format '{{.Id}}')" != "$backend_old_id"
test "$(docker inspect application-celery-1 --format '{{.Id}}')" != "$celery_old_id"
test "$(docker inspect application-celery-beat-1 --format '{{.Id}}')" != "$celery_beat_old_id"
test "$(docker inspect application-frontend-1 --format '{{.Id}}')" != "$frontend_old_id"

docker exec application-backend-1 python manage.py check | tee "$release_dir/post-django-check.txt"
docker exec application-backend-1 python manage.py showmigrations integrations permissions reports commerce | tee "$release_dir/post-migration-state.txt"
grep -Fq '[X] 0016_commerce_platform_and_resource_choices' "$release_dir/post-migration-state.txt"
grep -Fq '[X] 0031_seed_integration_custody_permissions' "$release_dir/post-migration-state.txt"
grep -Fq '[X] 0006_sales_details_export' "$release_dir/post-migration-state.txt"
grep -Fq '[X] 0001_fact_tables_v1' "$release_dir/post-migration-state.txt"
docker exec application-frontend-1 nginx -t 2>&1 | tee "$release_dir/nginx-check.txt"

for path in / /products/master /products/details /sales-management/overview /sales-management/orders /sales-management/returns /sales-management/store-sales /sales-management/sku-sales /sales-management/exports /sales-management/data-quality /system/roles; do
  code=$(curl -ksS -o /dev/null -w '%{http_code}' "https://192.168.174.131:8443$path")
  printf '%s %s\n' "$path" "$code" | tee -a "$release_dir/page-status.txt"
  test "$code" = 200
done

main_asset=$(docker exec application-frontend-1 sh -c \
  "sed -n 's/.*src=\"\\/\(assets\\/index-[^\"]*\\.js\)\".*/\1/p' /usr/share/nginx/html/index.html")
test -n "$main_asset"
for label in 工作台 产品开发 全球刊登 经营分析 经营决策 销售管理 达人管理 流程协同 业务协同 RPA协同 API数据接入 财务中心 报表中心 基础档案 系统治理 治理与试点; do
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

docker inspect application-backend-1 application-celery-1 application-celery-beat-1 application-frontend-1 \
  --format '{{.Name}}|{{.Id}}|{{.Config.Image}}|{{.Image}}' > "$release_dir/runtime-images.txt"
docker ps --format '{{.Names}}|{{.Image}}|{{.ID}}|{{.Status}}' > "$release_dir/post-switch-containers.txt"
docker logs --since 15m application-backend-1 2>&1 | tail -n 500 > "$release_dir/backend-last-15m.log"
docker logs --since 15m application-frontend-1 2>&1 | tail -n 500 > "$release_dir/frontend-last-15m.log"
! grep -Eiq 'Traceback|Internal Server Error|CRITICAL' "$release_dir/backend-last-15m.log"
! grep -Eiq 'emerg|alert|crit' "$release_dir/frontend-last-15m.log"
sha256sum "$release_dir/pre-deploy-v2.44.38.sql.gz" > "$release_dir/artifacts.sha256"
echo 'DEPLOYMENT_VALIDATION=PASS'
