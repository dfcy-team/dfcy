# 生产试点验证 P1 整改报告

## 1. 整改对象

- 分支：`feature/pilot-p1-remediation`
- 基线：`b1be1ac302eb31016af45fd8762b70f7770fd7d0`
- 日期：2026-07-21
- 性质：定向修复虚拟机试点验证发现的 3 项 P1，不接入真实平台，不启用高风险自动化。

## 2. P1 关闭情况

| 编号 | 问题 | 整改结果 | 主要证据 |
|---|---|---|---|
| PILOT-P1-001 | 前端 Docker 测试与生产构建共用 `VITE_USE_MOCK=false`，测试阶段失败 | 已关闭 | Dockerfile 将测试固定为 `VITE_USE_MOCK=true`，生产构建仍使用构建参数 `false`；Docker 实测 153 tests passed 且 build 成功 |
| PILOT-P1-002 | MySQL 不支持条件唯一约束，RPA 同账号 held 锁缺少数据库级唯一保障 | 已关闭 | `held_lock_key` stored generated column + `(tenant, held_lock_key)` unique constraint；MySQL 8.4 迁移、索引检查及专项 11 tests passed |
| PILOT-P1-003 | 试点仅提供 HTTP，Django 生产安全配置缺少 HTTPS、HSTS 和 Secure Cookie | 已关闭 | Nginx TLS、HTTP 308、HSTS、可信代理头；Django `check --deploy` 0 issues；HTTPS 容器实测 200 |

## 3. 前端构建整改

`Dockerfile.frontend` 将测试环境与生产构建环境显式分离：测试命令只在 Mock 模式运行，随后使用 `VITE_USE_MOCK=false` 的生产构建参数生成静态资源。该修正不改变运行时 API 合同，也不将未联调接口误标为 connected。

## 4. MySQL 锁约束整改

`RPAAccountLock` 新增仅在 `lock_status=held` 时生成值的 `held_lock_key`。released、expired 等非持锁状态生成 `NULL`，MySQL 允许唯一索引包含多条 `NULL`，因此同时满足：

1. 同 tenant、platform、account_alias 只能存在一条 held 锁。
2. 历史 released/expired 锁可保留。
3. SQLite 与 MySQL 均可执行迁移及回滚。

迁移会先按数据库实际结构检查旧条件约束是否存在，避免 MySQL 因旧约束从未创建而失败。

## 5. HTTPS 与生产安全整改

- HTTP `8080` 仅返回到 HTTPS 的 `308` 重定向。
- HTTPS `8443` 使用运维下发的证书与私钥，文件只读挂载，不进入镜像或 Git。
- Nginx 设置 TLS 1.2/1.3、HSTS，并向 Django 固定传递 `X-Forwarded-Proto=https`。
- Django 生产配置启用 SSL redirect、Secure session/CSRF Cookie、HSTS 和可信代理协议头。
- 安装脚本拒绝缺失、相对路径、不可读、格式错误或 24 小时内过期的证书。

## 6. 实际验证结果

| 验证项 | 结果 |
|---|---|
| Django `check --deploy` | 通过，0 issues |
| migration consistency | 通过，No changes detected |
| SQLite 迁移前进/回滚 | 通过 |
| MySQL 8.4 全量迁移 | 通过，`rpa.0005` OK |
| MySQL 生成列/唯一索引检查 | 通过，stored generated column 与 unique index 均存在 |
| MySQL RPA 稳定性专项 | 11 passed |
| 后端定向测试 | 15 passed |
| 后端全量测试 | 399 passed |
| 前端本地测试 | 153 passed |
| 前端生产 build | 通过 |
| 前端 Docker build | 通过，镜像内 153 tests passed 后 build 成功 |
| Compose config | 通过 |
| Nginx config | 通过 |
| HTTP/HTTPS 运行验证 | HTTP 308；HTTPS 200；HSTS 存在 |
| 私钥/API Key 特征扫描 | 未发现真实凭据 |
| 远端 CI | 未执行，待分支提交并创建 PR 后核验 |

## 7. 安全边界

- 未提交真实 `.env`、TLS 私钥、账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- MySQL 验证使用本地一次性容器与纯测试凭据，未访问虚拟机试点库。
- 生产应用数据库账户不得授予 `CREATE DATABASE`；数据库测试使用独立短期测试账户。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未启用自动采购、自动改价、自动清仓、真实 RPA 或资金操作。

## 8. 结论与后续验收

3 项 P1 的代码和部署模板整改已完成，本地验证通过。建议提交分支并由架构员执行独立复审；合并后在应用虚拟机重新部署，使用受信任试点证书核验 HTTPS、Cookie、HSTS，并在数据库虚拟机核验迁移和唯一索引。远端 CI 与虚拟机复验通过前，不应视为生产试点正式放行。
