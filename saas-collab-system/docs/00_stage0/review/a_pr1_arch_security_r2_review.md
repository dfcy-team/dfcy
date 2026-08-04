# A-PR1 架构与安全 R2 复审报告

## 1. 复审结论

**PASS**

复审对象为整改实现固定提交 `91243e3`。R1 的四项 P1 均已关闭，未发现新增 P0 或 P1。该结论只表示 A1 授权基础整改通过，不表示真实 Shopee/TikTok Shop 已连接，也不自动放行 PR-A2。

## 2. P1 关闭矩阵

| P1 编号 | 结论 | 复审证据 |
|---|---|---|
| A-PR1-R1-P1-001 | CLOSED | 授权创建与归属/身份/state/reference/scope/actor 写入受服务上下文保护；QuerySet delete、bulk、跨 tenant、实例删除与 Admin 路径均有负向测试；配置引用只允许轮换服务写入 |
| A-PR1-R1-P1-002 | CLOSED | 移除关键字猜测，改为显式 Mock provenance；`0007/0008/0009` 分离结构、全量预检转换和条件删列；混合未知记录零写入失败，修正后可重跑；兼容旧版 `0007` 已删列环境 |
| A-PR1-R1-P1-003 | CLOSED | `MarketplaceStoreAuthorizationSerializer` 不再返回 `merchant_subject_id`、`shop_cipher`；列表、详情、序列化文本和审计文本均有不泄漏断言 |
| A-PR1-R1-P1-004 | CLOSED | 配置和门店轮换审计包含 old/new 引用链、版本与撤销结果；撤销失败不更新当前引用并追加失败审计；MySQL 并发轮换验证一个成功、一个版本冲突 |

R1 的 P2 观察项同时关闭：进入 `error` 状态必须提供受控大写错误码，空值、小写和带连字符值均被拒绝。

## 3. 验证证据

| 检查 | 结果 |
|---|---|
| Django `check` | PASS，0 issue |
| 迁移一致性 | PASS，No changes detected |
| A1 定向测试 | PASS，78 passed；SQLite 跳过 1 条 MySQL-only 锁测试 |
| 后端本地全量 | PASS，439 passed / 1 MySQL-only skipped |
| MySQL 并发轮换 | PASS，1 passed |
| MySQL 8.4.10 全新迁移 | PASS，36.24 秒；三项授权迁移完成，旧敏感列为 0 |
| MySQL 安全 Mock 迁移 | PASS，Platform/API 各完成 1 条转换 |
| MySQL 未知混合批次 | 预期阻断；Platform/API 引用写入均为 0，`0008` 登记数为 0 |
| MySQL 失败修正重跑 | PASS，修正显式 provenance 后完成转换和删列 |
| 最终 Local Sandbox integration | PASS，MySQL 后端 440 passed、前端 160 passed、生产构建成功 |
| 独立 R2 重跑 | PASS，已验证代码 HEAD `fc5cfd7` 再次完成本地 439 passed / 1 MySQL-only skipped，并完成 MySQL integration 440 passed、前端 160 passed 与生产构建 |
| 前端本地测试 | PASS，160 passed；本机低可用内存下使用单 worker |
| 前端生产构建 | PASS，1955 modules，无 chunk size warning；仅上游 PURE 注释提示 |
| CI guard / 高置信凭据扫描 | PASS |
| Git 制品检查 | PASS，未跟踪 dist、node_modules、cache、pyc 或 `.env.local` |

## 4. 安全复核

- 未实现 OAuth、callback、Token refresh、webhook 或真实平台 HTTP/SDK 调用。
- 未提交真实账号、密码、Token、Cookie、Session、API Key、API Secret、私钥或平台选择器。
- 未提交真实店铺、商家主体、订单、库存、供应商、财务或银行数据。
- 轮换与迁移测试仅使用 `synthetic-*`、approved Mock provenance 和本机临时数据库。
- 所有能力仍为 `pending/mock`，没有标记 `connected`，没有 Production 执行许可。

## 5. 残余观察项

| 等级 | 项目 | 处理 |
|---|---|---|
| P2 | production 依赖树仍有 PostCSS high advisory 1 项 | 既有依赖风险，需独立前端依赖升级与 160 项回归；不由 A1 安全整改扩范围处理 |
| P2 | MySQL 对 finance 条件唯一约束发出既有 warning | 与 integrations A1 无关，保留给 finance 数据一致性专项 |
| P2 | 本机前端默认并发在低可用内存时 OOM | Sandbox 默认并发通过；本机以单 worker 通过，建议后续记录 CI worker/memory 基线 |

## 6. PR-A2 进入门禁

截至本报告生成时：

- PR #37：`OPEN`、`Draft`、未合并，门禁未满足。
- PR #39：`OPEN`、`Draft`；最新远端 HEAD 为 `fc5cfd7`，与 R2 已验证代码版本一致，全部远端 CI 已成功。
- R2：对固定整改提交 `91243e3` 为 PASS，并已在报告 HEAD `fc5cfd7` 独立重跑确认。

因此当前**仍不得进入 PR-A2**。剩余门禁为：PR #37 完成独立批准并合并，A1 分支同步最新 `main`、调整 stacked PR 基线并再次取得最新 HEAD 全部 CI 成功；满足后才可开始 PR-A2。
