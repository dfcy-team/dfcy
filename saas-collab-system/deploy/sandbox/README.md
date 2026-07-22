# Sandbox 部署包

本目录提供独立于开发环境和 `controlled-pilot` 的受控 Sandbox 部署基线。Sandbox 用于业务功能联调、权限回归、浏览器 E2E、故障与回滚演练，不是生产环境，也不授权真实平台连接或高风险自动化。

## 目录

- `database/`：独立 MySQL 8.4 Sandbox 数据库容器模板。
- `application/`：Redis、Django、Celery、前端 Nginx 和验证脚本。
- `network/`：应用容器出站、客户端入口和数据库来源限制。
- `tests/`：不启动服务的安装门禁负向测试。

## 环境隔离

- 环境编码固定为 `sandbox`。
- 数据库、Redis 数据卷、Docker 网络、端口、TLS 证书和账号不得与 Pilot/Production 共用。
- 只允许合成、脱敏或审批后的测试数据。
- `INTEGRATION_ENCRYPTION_PROVIDER` 固定为 `unconfigured-production`。
- `SANDBOX_ALLOW_REAL_PLATFORM` 和 `SANDBOX_ALLOW_HIGH_RISK_AUTOMATION` 必须为 `false`。
- 应用、前端、Redis 和 MySQL 镜像必须使用审批清单中的 `@sha256` 引用。

## 推荐执行顺序

1. 在最新 `main` 手动运行 `Sandbox immutable artifacts` 工作流，下载并审批制品清单。
2. 两台主机安装 `iptables-persistent`；复制 `network/env.network.example` 到 `/etc/saas-collab/sandbox-network.env`，复核后设置 `SANDBOX_NETWORK_APPLY=YES`。
3. 在数据库主机复制 `database/env.sandbox.example` 为 `database/.env.sandbox`，注入随机密码、MySQL 摘要和网络策略路径。
4. 执行 `sh database/install-db.sh`。
5. 将下载的 `sandbox-artifact-manifest.json` 放入受控路径并设为 `0600`；在应用主机复制 `application/env.sandbox.example` 为 `application/.env.sandbox`，填入清单路径、Git SHA、镜像摘要、TLS 和数据库地址。
6. 执行 `sh application/install-app.sh`。脚本只拉取固定摘要，不在目标主机构建代码。
7. 在应用主机创建 mode `0700` 的 `/var/lib/saas-collab/evidence` 与 `/var/lib/saas-collab/network`；在数据库主机创建 mode `0700` 的 `/var/lib/saas-collab/network`。
8. 重启应用与数据库主机后，分别执行 `sudo network/collect-network-evidence.sh app /etc/saas-collab/sandbox-network.env post-reboot` 和 `sudo network/collect-network-evidence.sh db /etc/saas-collab/sandbox-network.env post-reboot`。
9. 在数据库主机执行 `sudo network/verify-db-source-rejection.sh begin`；随后在第三台未授权主机安装 `netcat-openbsd`，使用单独的策略副本设置 `SANDBOX_UNAPPROVED_SOURCE_PROBE=YES` 并执行 `network/probe-db-source-denied.sh`；最后回到数据库主机执行 `sudo network/verify-db-source-rejection.sh complete`，证明对应 MySQL `REJECT` 计数器实际增长。
10. 将数据库主机和第三台探针主机生成的三份证据安全复制到应用主机 `.env.sandbox` 指定的受控 evidence 路径，权限设为 `0400`。
11. 为短期非超级 internal 测试账号仅授予 `pilot.readiness.view` 和 `environment_ids=["sandbox"]` 的 custom scope，使用 mode 600 密码文件执行 `verify-sandbox-e2e.sh`。脚本只有在五份网络证据均有效时才生成 Sandbox PASS evidence；完成后删除账号和密码文件。
12. 归档 PASS evidence 与其引用的网络证据；完成验收清单后才可申请晋级受控 Pilot。

主机前置工具：Docker Compose、OpenSSL、curl、jq、iptables、`iptables-persistent`/`netfilter-persistent`。应用和数据库主机的网络策略必须分别执行并在重启后复验。

真实 `.env.sandbox`、TLS 私钥、数据库备份和验证 Token 不得提交到 Git。Sandbox PASS 也不自动允许真实平台接入或生产发布。

## 网络证据文件

以下文件必须由独立 Linux Sandbox 主机实际生成，不能以本地静态检查替代：

- `/var/lib/saas-collab/network/app-runtime-network-evidence.json`：数据库正向连通与公共出站拒绝。
- `/var/lib/saas-collab/network/app-post-reboot-evidence.json`：应用主机重启后规则哈希、策略哈希和 boot ID。
- `/var/lib/saas-collab/network/db-post-reboot-evidence.json`：数据库主机重启后规则哈希、策略哈希和 boot ID。
- `unapproved-db-source-evidence.json`：第三台未授权来源连接数据库被拒绝。
- `db-unapproved-source-reject-evidence.json`：数据库主机对应 `REJECT` 规则计数器在探针窗口内增长。

证据文件权限必须为 `0400`，只归档脱敏结果，不包含密码、Token、Cookie、Session 或私钥。
