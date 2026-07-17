# UI-P6-ARCH-CONTRACT-R2 复审报告

## 1. 复审对象

- 任务：UI-P6 API接入与分析复盘合同 P1 整改独立复审。
- 分支：`feature/ui-p6-api-analytics-review`。
- 基线：本地 HEAD 与 `origin/main` 均为 `8c05228c77c262a9041e0f4c78d467819ba6efb2`。
- 复审日期：2026-07-17。
- 复审依据：R1报告、P1整改记录、总接口映射、阶段3最终API合同、UI-P6 API合同、UI-P6验收清单，以及现有后端 URL/serializer/permission/data_scope 和前端 API/页面消费代码。
- 性质：仅复审合同整改；未修改合同或业务代码，本报告是本次唯一新增输出。

## 2. 复审结论

**PASS**。

三项原 P1 均已在合同层关闭：路径已经唯一，analytics/finance 已形成逐端点 schema，permission-specific data_scope 已形成可实现、可测试的 exact permission 矩阵。未发现新增 P0/P1。

本结论仅允许进入 UI-P6 实施，不表示现有后端和前端已经完成合同适配，也不表示任何端点已经取得受控 Pilot 联调证据。

## 3. 原P1关闭情况

| 原P1编号 | 问题 | 是否关闭 | 证据 | 复审备注 |
|---|---|---|---|---|
| UI-P6-CONTRACT-P1-001 | 总映射保留旧路径，integrations PATCH 未唯一冻结 | 是 | `frontend_api_mapping.md`、`ui_p6_api_analysis_contract.md` 第2.2节、验收清单第3节 | 旧阶段3别名已退役；配置 PATCH 唯一为 `/api/internal/integrations/configs/{id}/`；各动作与同步资源路径唯一；UI-P6条目保持 pending/mock |
| UI-P6-CONTRACT-P1-002 | analytics/finance 请求、响应和质量字段未逐端点冻结 | 是 | `ui_p6_api_analysis_contract.md` 第1、3节；验收清单第4、5节 | overview/sales/inventory/metrics/aggregates 及 finance 三端点均有固定查询参数、分页、结果、质量和旧字段退役规则 |
| UI-P6-CONTRACT-P1-003 | permission-specific data_scope 缺少 scope key 和越权语义 | 是 | `ui_p6_api_analysis_contract.md` 第4节；验收清单第6节 | exact permission、模块 key、ALL/CUSTOM/OWN/DEPARTMENT、OR/AND及200/403/404行为均已冻结 |

## 4. 路径唯一性

静态扫描确认总映射不再把以下内容作为现行后端路径：补货 `suggestions`、生命周期 `history`、未区分 inventory/business 的 alerts、配置 `items/versions`、同步 `sync-tasks/sync-logs`。

integrations 合同与现有后端 URL 一致：

- `GET/POST /api/internal/integrations/configs/`
- `GET/PATCH /api/internal/integrations/configs/{id}/`
- `POST /api/internal/integrations/configs/{id}/disable/`
- `POST /api/internal/integrations/configs/{id}/verify/`
- `POST /api/internal/integrations/configs/{id}/rotate/`
- `GET/POST /api/internal/integrations/sync-jobs/`
- `POST /api/internal/integrations/sync-jobs/{id}/run-mock/`
- `POST /api/internal/integrations/sync-jobs/{id}/disable/`
- `GET /api/internal/integrations/sync-runs/`
- `GET /api/internal/integrations/sync-runs/{id}/`

合同明确不存在集合级 PATCH。总映射顶部 UI-P6 条目和详细映射均保持 `pending` 或 `mock`，没有把未完成的 UI-P6 适配误标为 `connected`。

## 5. 逐端点schema

analytics 已逐端点冻结：

- overview、sales、inventory 的允许查询参数和追加维度不同，结果字段、metrics/trend、归因或库存范围明确。
- metrics 和 aggregates 分别拥有固定列表/详情字段，不再依赖“至少提供”或“等价字段”。
- aggregate-mock 的请求字段和只生成 Mock 聚合结果的边界明确。
- 统一分页包含 `count/next/previous/results`，聚合页面追加 `api_status/quality`。
- 缺失数据固定为 `null + is_missing=true`，不得伪造为 0。

finance analytics 已逐端点冻结：

- overview、reconciliation、exceptions 的查询参数和结果字段分别定义。
- 三个端点均要求 `read_only=true`、`fund_action_available=false`。
- 旧 `currencies/statuses/exceptions/items` 顶层结构已明确退役。
- 账号只允许 `account_mask` 等脱敏字段。

错误合同覆盖 400、401、403、404、409、422；未知查询参数与超过100的分页大小必须返回400。当前后端 finance DTO、analytics serializer 与前端页面消费尚未完全符合新合同，但合同已明确由开发A修正 serializer/data_scope、开发B修正请求和字段解析，且完成联调前保持 pending，因此不构成合同层未关闭 P1。

## 6. permission-specific data_scope

合同明确后端按端点所需 exact permission 调用 permission-specific scope，不能使用用户全部角色 scope 的全局合并结果替代。

已冻结的模块 key：

- analytics：`analytics_dimensions`，允许 platform、store_id、country、product_id、sku_id、warehouse_id。
- lifecycle：`spu_ids`、`sku_ids`，高风险确认取 confirm 与 high_risk_confirm scope 交集。
- workflow：`approval_types`，UI-P6 清仓限定 `clearance`。
- integrations：`platforms`、`integration_config_ids`、`resource_types`。
- finance：`platforms`、`currencies`，仍先执行财务独立授权。
- reports：`report_types` 与来源模块 scope 交集，view/export/download 分别计算。

通用语义完整：ALL 仅放行当前 tenant；CUSTOM 记录间 OR、同记录不同 key AND；未冻结归属模型的 OWN/DEPARTMENT 返回 `403 DATA_SCOPE_UNSUPPORTED`；无、空或非法 scope 返回403；列表合法超范围返回200空分页；详情/动作超范围及跨tenant返回404；请求体主动提交越权维度返回403。

现有 analytics/lifecycle/reports 部分实现仍使用全局 scope，integrations/finance 仍主要按 tenant 过滤。这些差距已被合同和验收清单显式登记为后端实施与测试责任，没有被描述为已完成。

## 7. 验收可执行性

验收清单已转化为可执行断言：

- 精确 URL、HTTP 方法及集合级 PATCH 拒绝。
- 逐端点查询参数、分页上限、固定字段和缺失值行为。
- exact permission scope 的 ALL/CUSTOM/OWN/DEPARTMENT、OR/AND及200/403/404。
- tenant、财务独立权限、external/RPA拒绝、脱敏和高风险动作边界。
- Django check、migration检查、专项/全量pytest、npm测试/构建、Docker、安全扫描和浏览器认证态验收。

本次执行了文档、URL、serializer、permission/data_scope、前端API/字段消费和修改范围的静态检查。未执行 Django、pytest、npm、Docker或浏览器测试，因为本次只判断合同是否可进入实施且没有业务代码变更；这些命令必须在 UI-P6 实施及最终复审阶段实际执行并记录。

## 8. 安全与修改范围

本轮整改范围仅为 UI-P6 文档：总映射、API合同、验收清单、整改记录和R2提示。未发现 backend、frontend、rpa-agent 或 docs/04_rpa 修改。

未发现真实账号、密码、Token、Cookie、Session、API Key、API Secret、银行凭据、真实平台配置或真实业务数据。合同继续禁止真实平台接入、自动采购、自动清仓/停售/归档/改价、真实RPA和付款/转账/提现。

既有未跟踪 DOCX 为审核外文件，本次未读取、未修改、未纳入复审输出。

## 9. P0

无。

## 10. P1

无。三项原 P1 全部关闭。

## 11. P2

| 编号 | 观察项 | 后续要求 |
|---|---|---|
| UI-P6-CONTRACT-R2-P2-001 | 后端 analytics/finance DTO 尚未适配逐端点合同 | 开发A按合同补 serializer、分页、质量摘要、未知参数和错误状态测试；完成前保持 pending |
| UI-P6-CONTRACT-R2-P2-002 | analytics/lifecycle/reports 仍有全局 scope，integrations/finance 尚未完整执行 exact permission scope | 开发A实现统一 permission-specific scope 解析并覆盖tenant、200/403/404和动作越权测试 |
| UI-P6-CONTRACT-R2-P2-003 | 前端 date_range/store/warehouse 等参数、finance旧字段和 fallback 状态尚未适配合同 | 开发B实现请求适配、统一字段解析和 `fallback -> degraded` 映射，并补页面状态测试 |
| UI-P6-CONTRACT-R2-P2-004 | 浏览器认证态联调尚未执行 | 实施完成后在受控Pilot环境覆盖桌面、窄屏、空数据、断网及权限切换，不连接真实平台 |

上述均为合同通过后的实施项，有明确责任、验收门禁和 pending 状态，不阻断合同R2。

## 12. 是否允许进入UI-P6实施

**允许进入 UI-P6 实施。**

实施必须以 `docs/03_api/ui_p6_api_analysis_contract.md` 为唯一合同，按 `docs/05_test/ui_p6_api_analysis_acceptance.md` 完成后端、前端、系统、安全和浏览器验证。未取得实际联调证据的能力不得标记为 connected。

本结论不允许直接接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台，也不允许启用自动采购、清仓、停售、归档、改价、真实 RPA 或资金操作。
