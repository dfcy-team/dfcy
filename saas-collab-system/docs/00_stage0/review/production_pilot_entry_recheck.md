# 生产试点准入独立复审报告

## 1. 复审对象

- 复审分支：`feature/pilot-p1-remediation`
- 基线与当前 HEAD：`b1be1ac302eb31016af45fd8762b70f7770fd7d0`
- 复审日期：2026-07-21
- 复审范围：前端试点 Docker 构建、MySQL 8.4 RPA 持锁约束、HTTPS/TLS 与 Django 生产安全配置、测试证据、安全边界及正式准入门禁。
- 复审性质：独立重新执行检查，不直接采用整改报告结论，不修改业务功能或真实环境数据。

## 2. 复审结论

**CONDITIONAL_PASS**

原 3 项 P1 已在当前工作树的代码、迁移、部署模板和本地运行验证层面关闭，未发现新增 P0 或代码级 P1。但当前整改尚未形成不可变提交，远端不存在对应分支、PR 和 CI；数据库与应用虚拟机也尚未部署本次整改并完成受信任证书下的复验。因此仅允许进入提交、远端 CI 和受控虚拟机复验，不允许宣布生产试点正式准入。

## 3. 原 P1 关闭情况

| 原问题 | 是否关闭 | 独立复审证据 | 备注 |
|---|---|---|---|
| 前端 Docker 测试与生产构建环境耦合 | 是 | `docker build --no-cache` 在 `VITE_USE_MOCK=false` 构建参数下，测试层显式使用 Mock；153 tests passed，生产 build 成功 | 测试环境不再污染生产静态构建 |
| MySQL 条件唯一约束未落地 | 是 | MySQL 8.4 空库全量迁移通过；`held_lock_key` 为 stored generated column；`uniq_held_rpa_platform_account` 为唯一索引；专项 11 passed | held 锁数据库级唯一，历史非 held 记录可保留 |
| 试点仅 HTTP 且 Django 生产安全配置不完整 | 是 | `check --deploy` 为 0 issues；Nginx config 通过；HTTP 返回 308；HTTPS 返回 200 与 HSTS；Compose config 和安装脚本语法通过 | 证书/私钥只读挂载，安装前校验格式、有效期和匹配关系 |

## 4. 分支与变更范围

1. 当前分支与 `origin/main` 无领先或落后提交，整改尚未提交。
2. 变更集中于 `backend/apps/rpa/`、后端设置和测试、`deploy/pilot/`、测试/发布/审核文档。
3. 未修改 `frontend/src/`、`rpa-agent/` 或 `docs/04_rpa/` 业务内容。
4. 无关的 DOCX、`docs/00_stage0/architecture/` 和 `docs/04_rpa/协同开发下发/` 仍为未跟踪文件，不属于本次复审成果，后续提交必须排除。

## 5. 后端与数据库复审

| 检查 | 结果 |
|---|---|
| Django production `check --deploy` | PASS，0 issues |
| `makemigrations --check --dry-run` | PASS，No changes detected |
| SQLite 全量 pytest | PASS，399 passed |
| MySQL 8.4 空库全量迁移 | PASS，全部迁移成功，`rpa.0005` OK |
| MySQL 生成列检查 | PASS，`held_lock_key` 为 STORED GENERATED |
| MySQL 唯一索引检查 | PASS，tenant_id + held_lock_key，NON_UNIQUE=0 |
| MySQL RPA 稳定性专项 | PASS，11 passed |

MySQL 检查使用本地一次性容器、空数据库和测试凭据，不访问数据库虚拟机，不复制真实业务数据。

## 6. 前端构建与 HTTPS 复审

| 检查 | 结果 |
|---|---|
| 前端 Docker 无缓存构建 | PASS |
| 镜像内前端测试 | PASS，153 passed |
| 生产静态 build | PASS |
| Docker Compose config | PASS |
| Nginx config | PASS |
| HTTP 重定向 | PASS，308，保留 path/query |
| HTTPS 静态页面 | PASS，200 |
| HSTS | PASS，`max-age=31536000; includeSubDomains; preload` |
| TLS fixture | 本地自签测试证书，仅用于技术验证，已清理 |

## 7. 安全扫描

- 本次整改文件及可扫描源码中未发现真实 `.env`、私钥、证书包、SSH 密钥或 SQLite 数据库；未纳入复审的无关 DOCX 不作内容安全结论，提交时必须继续排除。
- 未发现私钥头、OpenAI/GitHub/AWS 类真实密钥特征。
- 未新增真实 BigSeller、Shopee、TikTok/TK、银行或支付连接。
- 未启用自动采购、自动改价、清仓、停售、归档、真实 RPA 或资金操作。
- 测试证书、测试数据库及容器均不包含真实业务数据；临时容器已在报告完成前清理。

## 8. P0

无。

## 9. P1

| 编号 | 未关闭门禁 | 影响 | 关闭标准 |
|---|---|---|---|
| PILOT-ENTRY-R1-P1-001 | 整改尚未提交、推送，无固定审核 HEAD、PR 和远端 CI | 当前证据无法与不可变 Git 提交绑定 | 仅提交本次允许文件，推送分支并创建 PR；全部必需 CI 成功且 HEAD 不变化 |
| PILOT-ENTRY-R1-P1-002 | 两台试点虚拟机尚未部署本次整改并复验 | 本地容器验证不能替代目标环境证书、MySQL 迁移和网络验证 | 合并后从最新 main 部署；以受信任证书验证 HTTPS/Cookie/HSTS，在数据库主机核验生成列/唯一索引及最小权限账户 |

## 10. P2

1. npm 仍报告 `glob`、`whatwg-encoding` 弃用提示以及 allow-scripts 观察项，不阻断本次构建。
2. Vite/Rollup 仍报告第三方依赖 PURE 注释位置提示，不阻断构建。
3. 本地 HTTPS 验证使用自签测试证书；正式试点必须使用批准、受信任且匹配主机名的证书，不能以 `curl -k` 作为验收证据。

## 11. 是否允许生产试点准入

- 允许提交整改分支、创建 PR、执行远端 CI：**允许**。
- 允许在合并后执行受控虚拟机重新部署和验收：**允许**。
- 当前是否允许宣布生产试点正式准入：**不允许**，须关闭上述 2 项门禁 P1。
- 是否允许真实平台接入或真实高风险自动化：**不允许**，仍须专项安全评审和独立审批。

## 12. 最终建议

原 3 项技术 P1 已关闭。下一步应排除所有无关未跟踪文件，提交并推送 `feature/pilot-p1-remediation`，等待远端 CI 成功；PR 合并到 main 后在数据库和应用虚拟机完成定向复验，再执行生产试点准入 R2 收尾核验。
