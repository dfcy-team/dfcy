# 阶段3生产试点安装说明

## 1. 适用范围与安全边界

本说明用于受控内网的阶段3生产试点准备，基线为 `v0.4-phase3-complete` 加已审核的试点安装包。推荐拓扑为数据库主机运行原生 MySQL 8.4，应用主机通过 Docker 运行 Redis、Django、Celery 和前端 Nginx；不接入真实 BigSeller、Shopee、TikTok/TK、银行、支付或其他生产平台。

禁止事项：

- 不提交或复制真实 `.env.pilot` 到仓库。
- 不将 MySQL、Redis、Django 调试端口暴露到公网。
- 不启用自动采购、自动清仓、停售、归档、改价、真实 RPA 或资金操作。
- 不使用 SQLite 作为试点数据库。

真实平台接入、凭据托管、生产域名/TLS、反向代理、外网访问和高风险自动化均须另行评审。

## 2. 安装包

| 端 | 文件 | 用途 |
|---|---|---|
| 数据库端 | Ubuntu/MySQL 原生服务 | 独立数据库虚拟机上的 MySQL 8.4 |
| 数据库端（可选） | `deploy/pilot/database/` | 仅供单机 Docker 试验，不用于当前两机部署 |
| 应用层 | `deploy/pilot/application/docker-compose.pilot-app.yml` | Redis、Django、Celery、前端 Nginx 与迁移任务 |
| 应用层 | `deploy/pilot/application/env.pilot.example` | Django、MySQL、Redis 的占位变量 |
| 应用层 | `deploy/pilot/application/install-app.sh` | 应用构建、迁移与启动脚本 |
| 应用层 | `deploy/pilot/application/Dockerfile.frontend` | Vue 构建与 Nginx 运行镜像 |

所有脚本均使用受控主机上的 `.env.pilot`。示例文件只能用于复制结构，示例值不能用于试点启动。

## 3. 试点前置条件

1. 数据库主机已安装 MySQL 8.4；应用主机已安装 Docker Engine 和 Docker Compose v2。
2. 两台主机仅在 VMware 私有/NAT 网络中互通，数据库 IP 已固定。
3. MySQL 3306 仅允许应用主机 IP；Redis 不映射宿主机端口；Django 8000 仅绑定回环地址。
4. 已由批准的密钥托管系统生成 Django、MySQL、Redis 的独立试点凭据。
5. 试点数据库备份位置、保留周期、恢复责任人与回滚窗口已记录。
6. 不在试点环境配置任何真实平台凭据或真实平台回调。

## 4. 数据库端准备

在数据库主机确认服务、监听和业务账户：

```bash
sudo systemctl status mysql --no-pager
sudo ss -lntp | grep 3306
mysql -uroot -p -e "SHOW DATABASES;"
```

应用主机执行连接核验，密码仅在交互提示中输入：

```bash
mysql -h DATABASE_HOST_IP -P 3306 -u saas_collab_pilot_user -p saas_collab_pilot
```

数据库账户只授权给应用主机 IP，不允许 root 远程登录，也不允许公网访问 3306。

## 5. 应用层安装

数据库端健康后，在应用主机执行：

```bash
cd saas-collab-system/deploy/pilot/application
cp env.pilot.example .env.pilot
chmod 600 .env.pilot
# 填入数据库主机 IP、MySQL 应用账户、唯一 Django/Redis 密钥和应用主机 IP。
sh ./install-app.sh
```

脚本拒绝保留 `change-me` 占位值，依次执行 Compose 配置检查、后端和前端镜像构建、启动 Redis、数据库迁移，再启动 backend、Celery worker/beat 和前端 Nginx。Django 生产设置会拒绝 SQLite、缺失的 `DJANGO_SECRET_KEY`、缺失的 `DJANGO_ALLOWED_HOSTS` 以及 `test-only` 加密提供方。

核验：

```bash
docker compose --env-file .env.pilot -f docker-compose.pilot-app.yml ps
docker compose --env-file .env.pilot -f docker-compose.pilot-app.yml logs --tail=100 backend
curl --fail http://127.0.0.1:8000/api/health/
curl --fail http://127.0.0.1:8080/
```

应用模板使用 Gunicorn，后端仅绑定回环地址；前端 Nginx 默认绑定应用主机 `8080`，供受控内网试点访问。公网域名、TLS 和外部访问仍须单独评审。

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

当前两机部署的 MySQL 是数据库主机上的原生服务，不随应用 Compose 停止。不得使用 `down -v` 删除 Redis 数据卷，除非完成批准的备份和销毁流程。

## 8. 试点放行边界

安装成功仅表示可以开始**受控试点准备**。真实平台接入、真实凭据下发、真实 RPA、自动采购、自动改价/清仓/停售/归档、付款、转账和提现仍然禁止，必须单独完成专项安全评审、试点审批、灰度计划和回滚演练。
