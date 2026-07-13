# 阶段3生产试点安装说明

## 1. 适用范围与安全边界

本说明用于受控内网的阶段3生产试点准备，基线为 `v0.4-phase3-complete`。它只部署 MySQL、Redis、Django 和 Celery 基础能力，不接入真实 BigSeller、Shopee、TikTok/TK、银行、支付或其他生产平台。

禁止事项：

- 不提交或复制真实 `.env.pilot` 到仓库。
- 不将 MySQL、Redis、Django 调试端口暴露到公网。
- 不启用自动采购、自动清仓、停售、归档、改价、真实 RPA 或资金操作。
- 不使用 SQLite 作为试点数据库。

真实平台接入、凭据托管、生产域名/TLS、反向代理、外网访问和高风险自动化均须另行评审。

## 2. 安装包

| 端 | 文件 | 用途 |
|---|---|---|
| 数据库端 | `deploy/pilot/database/docker-compose.pilot-db.yml` | MySQL 8.4、Redis 和私有 Docker 网络 |
| 数据库端 | `deploy/pilot/database/env.pilot.example` | 数据库和 Redis 占位变量 |
| 数据库端 | `deploy/pilot/database/install-db.sh` | 数据库端配置检查与启动脚本 |
| 应用层 | `deploy/pilot/application/docker-compose.pilot-app.yml` | Django、Celery、Celery beat 与迁移任务 |
| 应用层 | `deploy/pilot/application/env.pilot.example` | Django、MySQL、Redis 的占位变量 |
| 应用层 | `deploy/pilot/application/install-app.sh` | 应用构建、迁移与启动脚本 |

所有脚本均使用受控主机上的 `.env.pilot`。示例文件只能用于复制结构，示例值不能用于试点启动。

## 3. 试点前置条件

1. Linux 试点主机已安装 Docker Engine 和 Docker Compose v2。
2. 主机仅在私有网络中可访问，管理员访问采用受控 VPN、堡垒机或同等方案。
3. MySQL 和 Redis 无公网端口映射；应用模板也仅绑定 `127.0.0.1:8000`。
4. 已由批准的密钥托管系统生成 Django、MySQL、Redis 的独立试点凭据。
5. 试点数据库备份位置、保留周期、恢复责任人与回滚窗口已记录。
6. 不在试点环境配置任何真实平台凭据或真实平台回调。

## 4. 数据库端安装

在受控试点主机中，将仓库检出到受控路径后执行：

```bash
cd saas-collab-system/deploy/pilot/database
cp env.pilot.example .env.pilot
chmod 600 .env.pilot
# 从密钥托管系统填入唯一的 MYSQL_PASSWORD、MYSQL_ROOT_PASSWORD、REDIS_PASSWORD。
sh ./install-db.sh
```

核验：

```bash
docker compose --env-file .env.pilot -f docker-compose.pilot-db.yml ps
docker compose --env-file .env.pilot -f docker-compose.pilot-db.yml exec mysql \
  mysqladmin ping -h localhost -u root -p"$MYSQL_ROOT_PASSWORD"
docker compose --env-file .env.pilot -f docker-compose.pilot-db.yml exec redis \
  redis-cli -a "$REDIS_PASSWORD" ping
```

预期 MySQL 显示 healthy，Redis 返回 `PONG`。数据库只加入 `saas-pilot-network` 私有网络，未配置宿主机端口。

## 5. 应用层安装

数据库端健康后，在同一受控 Docker 主机执行：

```bash
cd saas-collab-system/deploy/pilot/application
cp env.pilot.example .env.pilot
chmod 600 .env.pilot
# 填入同一试点 MySQL/Redis 凭据与唯一 Django SECRET_KEY。
sh ./install-app.sh
```

脚本依次执行 Compose 配置检查、镜像构建、`python manage.py migrate --noinput`，再启动 backend、Celery worker 和 Celery beat。Django 生产设置会拒绝 SQLite、缺失的 `DJANGO_SECRET_KEY`、缺失的 `DJANGO_ALLOWED_HOSTS` 以及 `test-only` 加密提供方。

核验：

```bash
docker compose --env-file .env.pilot -f docker-compose.pilot-app.yml ps
docker compose --env-file .env.pilot -f docker-compose.pilot-app.yml logs --tail=100 backend
curl --fail http://127.0.0.1:8000/api/health/
```

应用模板使用 Gunicorn，且仅绑定回环地址。外部访问前必须单独配置并审核反向代理、TLS、受控域名、健康检查与日志采集；不得直接将 8000 端口公开。

## 6. 安装后验收

1. 运行 `docker compose ... ps`，数据库与应用服务状态正常。
2. 后端日志无迁移、数据库、Redis 或权限初始化错误。
3. 使用试点测试用户验证 tenant、data_scope、财务独立权限和外部供应商隔离。
4. 确认补货、生命周期、预警、RPA 和财务页面仍只显示建议/只读/人工确认边界。
5. 执行 `python manage.py sync_permissions --check`：

```bash
docker compose --env-file .env.pilot -f deploy/pilot/application/docker-compose.pilot-app.yml \
  run --rm backend python manage.py sync_permissions --check
```

6. 记录安装时间、操作者、镜像摘要、数据库备份位置和验证结果。

## 7. 备份、回滚与停止

试点前先做数据库逻辑备份并在受控备份位置加密保存。回滚只能回到已验证的 Git 标签和同一版本数据库迁移状态；恢复前须获得负责人的批准。

停止应用服务：

```bash
cd saas-collab-system/deploy/pilot/application
docker compose --env-file .env.pilot -f docker-compose.pilot-app.yml down
```

停止数据库服务不会自动删除卷：

```bash
cd saas-collab-system/deploy/pilot/database
docker compose --env-file .env.pilot -f docker-compose.pilot-db.yml down
```

不得使用 `down -v` 删除试点数据卷，除非完成批准的备份和销毁流程。

## 8. 试点放行边界

安装成功仅表示可以开始**受控试点准备**。真实平台接入、真实凭据下发、真实 RPA、自动采购、自动改价/清仓/停售/归档、付款、转账和提现仍然禁止，必须单独完成专项安全评审、试点审批、灰度计划和回滚演练。
