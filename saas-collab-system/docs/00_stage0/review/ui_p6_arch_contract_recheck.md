# UI-P6-ARCH-CONTRACT-R1 合同前审报告

## 1. 审核对象

- UI-P6 页面范围、API、权限、tenant/data_scope、状态与验收合同。
- 最新 main 中 analytics、finance、lifecycle、workflow、integrations、reports 的 URL、权限、serializer、前端路由、API 封装和页面消费结构。
- 本次为独立合同前审，只生成本报告，不修改合同或业务代码。

## 2. 分支与基线

- 当前分支：`feature/ui-p6-api-analytics-review`。
- 当前 HEAD：`8c05228c77c262a9041e0f4c78d467819ba6efb2`。
- `origin/main`：`8c05228c77c262a9041e0f4c78d467819ba6efb2`。
- 分支基于最新 main；UI-P6 变更范围为允许的 docs 文档。
- 既有 `docs/00_stage0/architecture/` 和 `docs/01_architecture/` 下无关 DOCX 仍为未跟踪文件，本次未读取、未修改、未纳入审核变更。

## 3. 页面合同

页面范围覆盖角色工作台、经营总览、销售归因、库存分析、财务只读、生命周期复盘、清仓申请、API 接入中心、平台准入和报表导出，与 UI-P6 规划目标一致。

`/analytics/overview` 和 `/lifecycle/clearance-requests` 尚未出现在当前前端 router/menu；这是合同通过后的预期实施项。现有 `/analytics/sales`、`/analytics/inventory`、`/finance/analytics`、`/lifecycle/*`、`/integrations/*` 和 `/reports/exports` 页面已存在，但不能据此视为 UI-P6 已完成。

页面合同包含 loading、empty、error、401、403、404、409、422、degraded 和 offline，并明确筛选、分页、刷新、数据质量和窄屏验收，覆盖面完整。

## 4. API合同

主合同中的 analytics、finance analytics、lifecycle、workflow、integrations 和 report URL 与后端 URL 基本一致，未新增同义后端资源。

但存在两类阻断性不一致：

1. `frontend_api_mapping.md` 下方仍把阶段3描述为“开发A接口尚未合并”，并保留 `/api/internal/replenishment/suggestions/`、`/api/internal/lifecycle/history/`、`/api/internal/alerts/`、`/api/internal/config/items/` 和 `versions/` 等旧路径。它们与顶部 UI-P6 口径及当前后端 `recommendations/`、`decisions/`、分资源 alerts 和 config 最终路径冲突。
2. `ui_p6_api_analysis_contract.md` 将配置维护写成 `POST/PATCH configs/`，而后端实际合同是 `POST /api/internal/integrations/configs/` 和 `PATCH /api/internal/integrations/configs/{id}/`。当前写法可能使前端向集合路径发送 PATCH 并得到 405。

此外，请求/响应字段尚未按端点冻结。合同使用“通用查询参数”“至少提供”和“等价字段”，无法形成唯一 serializer 和页面字段映射。当前 `Phase3AnalyticsPage` 消费 `quality/metrics/trend/results|items`，analytics 聚合端点返回相近结构，但 finance analytics 当前分别返回 `currencies`、`statuses`、`exceptions`；关闭 Mock 后财务页会得到空指标、空趋势和空列表。该差异不能留给实施阶段临时解释。

## 5. 路由与动作权限

合同要求所有非公开路由登记 `routeCapabilities` 且默认拒绝，与当前 `canAccessPath()` fail-closed 实现一致。详情路径按最长资源路径继承权限的原则明确。

动作权限覆盖：

- `analytics.calculate`
- `products.lifecycle.evaluate/confirm/high_risk_confirm`
- `workflow.approvals.view/submit/review`
- `integrations.view/manage/rotate/run`
- `reports.view/export/download`
- `finance.view`

合同明确财务只读页不能以 `finance.view` 执行导入、对账、异常处理或资金动作。前端隐藏和处理器二次拒绝不替代后端授权，方向正确。

## 6. tenant与data_scope

tenant 隔离原则完整，清仓审批已明确 `approval_types=clearance`。然而 permission-specific data_scope 尚未冻结为可执行矩阵：

- analytics 当前使用用户全局 `get_user_data_scope()` 和 `analytics_dimensions`，不是 `analytics.view` 或 `analytics.calculate` 对应的 permission-specific scope。
- lifecycle 当前使用用户全局 scope 的 `sku_ids/spu_ids`，不是 view/evaluate/confirm 各权限独立 scope。
- integrations 查询当前只按 tenant 过滤，没有定义 platform/config/job 等 scope key。
- finance analytics 当前只按 tenant 和 `finance.view` 过滤，没有定义财务数据范围 key 或“仅 tenant 即为全部”的明确例外。
- reports 会保存 scope 快照并按源资源过滤，但合同未冻结 `report_type`、资源 ID 和维度 scope 的组合规则。

仅写“permission-specific data_scope”不足以让后端、前端和测试人员得到同一结果。必须为每个权限明确允许的 scope type、config key、无 scope 时的拒绝语义、ALL 语义以及详情越权返回 403/404 的约定。

## 7. 财务与敏感字段

财务独立授权、只读分析、账号掩码和禁止资金动作均已明确。现有 finance analytics 通过 `IsFinanceViewer`、tenant 过滤和审计日志保护，并返回 `account_details="***"` 等安全占位。

integrations serializer 只回显指纹、版本和掩码，credentials 为 write-only；production active 和 production verify 均受阻断。报表导出具备权限、范围快照、脱敏、行数限制和下载审计合同。

未发现真实 Token、Cookie、Session、API Key、API Secret、私钥、银行凭据或真实平台配置。

## 8. 清仓与高风险边界

清仓申请复用 `approval_type=clearance`，创建端点明确为 Mock。审批通过只形成审批结论，不改变商品、价格、库存、刊登、采购或 RPA 状态。

生命周期普通确认与 `products.lifecycle.high_risk_confirm` 已分离；现有后端也会对清仓、停售、归档追加高风险权限。合同明确指标、库存风险、补货建议、生命周期建议和预警不能直接触发采购、清仓、改价、RPA 或资金动作，边界通过。

## 9. 接入状态与数据质量

合同状态限定为 `mock/pending/sandbox/connected/degraded/disabled`，并禁止用 HTTP 200、配置 active、凭据指纹或一次 Mock 成功证明真实平台已连接，原则正确。

当前前端仍使用 `fallback` 表示网络降级，`Phase3AnalyticsPage` 和状态标签也识别 `fallback` 而非 `degraded`；实施时必须统一迁移或明确兼容映射。新页面和 UI-P6 映射目前保持 pending/mock，未发现 UI-P6 新条目误标 connected。

数据质量合同要求口径版本、更新时间、质量状态、缺失值和来源摘要，但字段名称仍允许“等价字段”，且未为 finance、analytics overview/sales/inventory 分别冻结结构，属于 API 字段 P1 的一部分。

## 10. 验收合同

验收清单覆盖页面状态、API路径、统一响应、分页、tenant、data_scope、财务权限、敏感字段、高风险动作、后端 check/migration/pytest、前端测试/build、Docker、浏览器和安全扫描。

本次仅执行静态合同、URL、权限、字段、范围和安全扫描；未执行 Django、pytest、npm 或 Docker 命令，因为没有业务代码变更，且前审目标是判定合同能否进入实施。后续合同 R2 通过后，实施验收必须按清单实际执行并记录结果。

## 11. 修改范围

UI-P6 当前变更仅涉及：

- `docs/00_stage0/frontend_api_mapping.md`
- `docs/00_stage0/review/ui_p6_*.md`
- `docs/01_architecture/ui_p6_api_analysis_scope.md`
- `docs/03_api/ui_p6_api_analysis_contract.md`
- `docs/05_test/ui_p6_api_analysis_acceptance.md`
- `docs/06_release/ui_p6_entry_notes.md`

未修改 backend、frontend、rpa-agent、docs/04_rpa、环境文件、依赖或部署配置。

## 12. P0

无。

## 13. P1

| 编号 | 问题 | 证据 | 验收标准 |
|---|---|---|---|
| UI-P6-CONTRACT-P1-001 | 总接口映射保留旧路径/旧状态，且 integrations PATCH 路径未唯一冻结 | `frontend_api_mapping.md` 阶段3旧表；`ui_p6_api_analysis_contract.md` 配置维护行；当前 backend URL | 删除、归档或明确废止旧条目；所有 UI-P6 方法使用完整唯一路径，PATCH 指向 `configs/{id}/` |
| UI-P6-CONTRACT-P1-002 | 分析与财务端点的请求、响应和数据质量字段未按端点冻结，Mock 与真实 finance analytics 结构不一致 | 合同“通用/至少/等价字段”；`Phase3AnalyticsPage.vue`；`finance/views.py` | 为 overview/sales/inventory、finance overview/reconciliation/exceptions 分别定义查询参数、分页和精确 data schema；明确前端 adapter，关闭 Mock 后不出现空页面 |
| UI-P6-CONTRACT-P1-003 | permission-specific data_scope 只写原则，未定义模块 scope key 和现有实现整改边界 | analytics/lifecycle 使用全局 scope；integrations/finance 仅 tenant；合同与验收清单 | 冻结每个权限的 scope type/config key、ALL/无scope语义、列表/详情/动作行为及 403/404 规则，并列出后端整改和测试责任 |

## 14. P2

| 编号 | 观察项 | 建议 |
|---|---|---|
| UI-P6-CONTRACT-P2-001 | 当前前端降级状态名为 `fallback`，合同使用 `degraded` | 实施时统一状态名或冻结双向映射，并补状态组件测试 |
| UI-P6-CONTRACT-P2-002 | `/analytics/overview`、`/lifecycle/clearance-requests` 尚未有前端路由和页面 | 合同 R2 通过后按 fail-closed 规则实施，不提前标 connected |
| UI-P6-CONTRACT-P2-003 | 浏览器认证态 E2E 尚未执行 | UI-P6 实施完成后在受控 Pilot 环境覆盖桌面、窄屏、断网和权限切换 |

## 15. 审核结论

**CONDITIONAL_PASS**。

无 P0，但存在 3 项未关闭 P1。合同的范围和安全方向正确，尚未达到可直接实施的唯一、精确和可测试程度。

## 16. 是否允许进入UI-P6实施

**暂不允许进入 UI-P6 业务实现。**

应先定向关闭 UI-P6-CONTRACT-P1-001 至 P1-003，并执行 `UI-P6-ARCH-CONTRACT-R2`。R2 结论为 PASS 后，方可开始页面、API adapter 和最小后端 data_scope 整改；真实平台接入和高风险自动化仍不允许。
