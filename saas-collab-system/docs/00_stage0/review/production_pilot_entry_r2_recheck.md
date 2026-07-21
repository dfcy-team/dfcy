# 生产试点准入 R2 复审报告

## 1. 复审对象

- 任务：生产试点 P1 整改提交、远端 CI 与目标虚拟机复验
- 复审日期：2026-07-21
- 整改分支：`feature/pilot-p1-remediation`
- 整改提交：`fd0a77dbff53a73a69e511e59b73e43427ae06fb`
- 整改 PR：[#27](https://github.com/dfcy-team/dfcy/pull/27)
- 合并提交：`47df58bfc60caaf237bbcb54d6d1b9dae460b223`
- 部署基线：应用虚拟机 `main` 与 `origin/main` 均为上述合并提交
- 目标环境：Ubuntu 24.04 应用虚拟机、Ubuntu 24.04 数据库虚拟机、MySQL 8.4.10

本次复审仅核验已审核整改、部署模板、CI 和目标虚拟机运行结果，不接入真实外部平台，不执行真实高风险自动化，不输出环境密码或密钥。

## 2. 复审结论

**CONDITIONAL_PASS**

原 3 项技术 P1 已在固定 Git 提交、远端 CI 和目标虚拟机上关闭。应用服务已使用最新 `main` 完成重建，MySQL 迁移、HTTPS、HSTS、Secure Cookie 配置和服务健康检查通过，未发现新增代码级 P0/P1。

当前允许继续受控内网试点验证，但尚不建议宣布正式生产准入：目标主机使用本次复验生成的短期自签名证书，尚未替换为组织批准并由目标客户端信任的正式证书；两台主机均提示 1 项标准安全更新待处理；本轮未使用独立试点业务账号完成浏览器认证态 E2E。上述事项不得被当前技术复验替代。

## 3. 原 P1 关闭情况

| 原问题 | 是否关闭 | 固定证据 | 目标环境证据 |
|---|---|---|---|
| 前端 Docker 测试与生产构建环境耦合 | 是 | `Dockerfile.frontend` 在测试阶段固定 `VITE_USE_MOCK=true`，生产构建仍使用生产参数；PR #27 CI 全部成功 | 应用虚拟机重新构建，镜像内前端测试 `153 passed`，随后生产 build 成功 |
| MySQL 缺少 RPA 同账号 held 锁数据库级唯一保证 | 是 | `rpa.0005_mysql_compatible_account_lock` 与专项测试进入合并提交 | 迁移已应用；`held_lock_key` 为 `STORED GENERATED`；`uniq_held_rpa_platform_account` 为 `(tenant_id, held_lock_key)` 唯一索引 |
| 试点缺少 HTTPS/HSTS/Secure Cookie 安全配置 | 是 | Nginx、Django production 设置、Compose 与安装校验进入合并提交 | HTTP 返回 308；HTTPS 返回 200；HSTS 存在；`check --deploy` 0 issues；Secure Cookie、SSL redirect 与 HSTS 设置均启用 |

## 4. Git、PR 与 CI

1. PR #27 的审核 HEAD 为 `fd0a77dbff53a73a69e511e59b73e43427ae06fb`，最终已使用 merge commit 合并。
2. 合并后的 `origin/main` 为 `47df58bfc60caaf237bbcb54d6d1b9dae460b223`。
3. Phase 2 与 Phase 3 的 Django/pytest、前端构建、Docker Compose、RPA 文档与仓库安全门禁均为 `SUCCESS`。
4. 应用虚拟机拉取后 `git rev-parse HEAD` 与该 `origin/main` 一致，工作树无已跟踪文件修改。
5. 无关 DOCX、`docs/00_stage0/architecture/` 和 `docs/04_rpa/协同开发下发/` 未进入整改提交或 PR。

## 5. 应用虚拟机复验

| 检查项 | 结果 |
|---|---|
| 最新 main 部署 | PASS，HEAD 为 `47df58bfc60caaf237bbcb54d6d1b9dae460b223` |
| 前端 Docker 测试 | PASS，153 passed |
| 前端生产 build | PASS |
| 数据库迁移 | PASS，`rpa.0005` 已应用 |
| 服务状态 | PASS，backend、frontend、celery、celery-beat 均运行，Redis healthy |
| Django `check --deploy` | PASS，0 issues |
| 后端日志 | PASS，检查窗口内未发现 error、exception 或 traceback |
| Celery 日志 | PASS，检查窗口内未发现 error、exception 或 traceback |
| 内部健康接口 | PASS，统一响应结构返回 `status=ok` |
| HTTP 到 HTTPS | PASS，8080 返回 308 并保留请求路径 |
| HTTPS | PASS，8443 返回 200；使用证书文件校验，未使用 `curl -k` |
| HSTS | PASS，`max-age=31536000; includeSubDomains; preload` |
| Django 安全设置 | PASS，Session/CSRF Secure、SSL redirect、HSTS 均启用 |

用于本次内网复验的证书为目标主机本地生成的 30 天自签名证书，私钥权限为 `root:docker 640`，未进入镜像或 Git。该证书只能证明 TLS 部署链路可运行，不能作为正式生产信任体系的验收证据。

## 6. 数据库虚拟机复验

| 检查项 | 结果 |
|---|---|
| MySQL 服务 | PASS，MySQL 8.4.10，systemd 状态 active/running |
| MySQL 监听 | PASS，仅监听 `192.168.174.132:3306`；X Protocol 仅监听本机 |
| UFW | PASS，默认拒绝入站；3306 仅允许宿主机和应用虚拟机地址 |
| 应用连通性 | PASS，应用迁移、健康检查和运行查询均成功 |
| 应用账号权限 | PASS，仅有 `USAGE ON *.*` 与业务库级 DML/DDL 权限，无全局数据库权限 |
| RPA generated column | PASS，`held_lock_key` 为 stored generated column |
| RPA unique index | PASS，`tenant_id,held_lock_key`，`NON_UNIQUE=0` |
| MySQL 服务日志 | PASS，检查窗口内未发现 error、fatal、crash 或 corrupt |

数据库 root 账号使用独立密码认证，本次未获取或输出该密码。root 无密码命令因此未作为验收依据；数据库服务状态、网络边界、应用连接、应用账号 grants 与目标 schema 均通过非泄密方式完成核验。

## 7. 安全扫描与边界

- 未提交真实 `.env`、TLS 私钥、数据库密码、Token、Cookie、Session、API Key 或 API Secret。
- 未新增真实 BigSeller、Shopee、TikTok/TK、银行或支付平台连接。
- 未启用自动采购、自动改价、自动清仓、停售、归档、真实 RPA 或资金操作。
- 应用数据库账号未获得全局权限；数据库 3306 未暴露到非授权网段。
- 短期复验证书与 `.env.pilot` 只保留在目标应用主机，不进入仓库。

## 8. P0

无。

## 9. P1

| 编号 | 未关闭门禁 | 影响 | 关闭标准 |
|---|---|---|---|
| PILOT-ENTRY-R2-P1-001 | 正式客户端信任证书与认证态 E2E 尚未完成 | 当前只能证明受控内网 TLS 链路可运行，不能证明正式用户端证书信任、登录会话与角色工作流完整 | 下发组织批准且匹配正式试点域名的证书；从试点客户端验证证书链、登录、Secure Cookie、角色菜单、401/403 和退出流程 |
| PILOT-ENTRY-R2-P1-002 | 两台 Ubuntu 主机各有 1 项标准安全更新待安装 | 正式试点前仍存在可避免的主机补丁风险 | 评估更新影响，完成备份和维护窗口更新；必要时重启；复验 MySQL、Docker、HTTPS 与核心健康接口 |

## 10. P2

1. npm 依赖弃用、allow-scripts 与第三方 PURE 注释警告继续作为非阻断观察项。
2. 当前自签名证书有效期仅 30 天，正式证书接入后应建立到期监控和轮换演练。
3. 建议把目标虚拟机部署复验命令固化为不包含凭据的运维验收脚本，并将输出归档到受控发布记录。

## 11. 准入建议

- 允许继续受控内网试点和界面/业务验证：**允许**。
- 允许使用当前自签名证书宣布正式生产准入：**不允许**。
- 允许直接接入真实平台或开启高风险自动化：**不允许**。
- 正式生产试点放行：关闭第 9 节两项 P1 后，执行定向 R3 复审。

## 12. 最终建议

PR、CI 和目标虚拟机复验流程已完成，原 3 项技术 P1 已关闭。当前结论保持 `CONDITIONAL_PASS`：可以继续受控内网验证，但需完成正式证书、认证态 E2E 和主机安全更新后，才建议宣布生产试点正式准入。
