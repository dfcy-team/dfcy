# 阶段3生产试点安装包

本目录是阶段3生产试点的安装模板，不是正式生产发布包。当前推荐拓扑是两台 Ubuntu Server 虚拟机：数据库主机运行原生 MySQL 8.4，应用主机运行 Docker 化的 Redis、Django、Celery 与前端 Nginx。

- `database/`：保留的单机 Docker MySQL 模板；两机部署不使用该目录启动数据库。
- `application/`：应用主机上的 Redis、Django、Celery worker/beat 与前端 Nginx 模板。

先在数据库主机完成原生 MySQL 安装、业务库和最小权限账户配置，再在应用主机配置 `.env.pilot`、受控 TLS 证书与私钥并启动应用栈。HTTP 端口仅执行 HTTPS 重定向，试点访问统一使用 HTTPS。真实 `.env.pilot`、证书私钥只能由密钥托管系统或受控运维主机生成，绝不能提交到 Git。

生产应用账户只拥有业务库运行所需权限，不授予 `CREATE DATABASE`。需要在 MySQL 上执行 Django 测试时，应创建独立、短期的测试库和测试账户，测试后按审批流程销毁，不能扩大生产应用账户权限。

本安装包不启用真实平台接入、真实 RPA、自动采购、自动改价、自动清仓、自动资金操作。

## Sandbox 同摘要晋级

Pilot 不在目标主机执行后端或前端构建，也不接受 `:pilot` 等可变标签。`application/.env.pilot` 必须填写 Sandbox 制品清单中的固定 Git SHA、后端/前端 `@sha256` 镜像、审批清单路径和 `verification_status=pass` 的 Sandbox E2E 证据路径。两份 JSON 均须位于受控绝对路径、不是符号链接且权限为 `0400` 或 `0600`。

`application/install-app.sh` 会逐项核验制品清单哈希、Git SHA、OCI revision、镜像摘要和迁移摘要；任一不一致即停止。只有通过 Sandbox JWT/API、运行网络及独立网络隔离验收的同一制品才可申请进入受控 Pilot。
