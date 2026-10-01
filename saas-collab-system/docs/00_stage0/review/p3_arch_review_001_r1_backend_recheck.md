# P3-ARCH-REVIEW-001-R1 开发A阶段3后端整改复审报告

## 1. 复审对象

- 审核对象：`origin/feature/phase3-a-analytics-alerts-config`
- 原审核提交：`711e037349b299601a1b540eebf64def10d4f73f`
- 最新审核提交：`638cfb400f613c97c087650199e339a6a3b5b0ec`
- 对比基线：`origin/main` / `28b3e068a852060092e7f0b3a56c26c2c1290407`
- GitHub PR：#12，base `main`，head 为审核分支，状态 OPEN、Draft、CLEAN；最新 HEAD 与本复审一致。

## 2. 分支与整改状态

分支包含阶段3规划基线，领先 `origin/main` 12 个提交、落后 0 个提交。原 P3-A-002 至 P3-A-008 的后端实现、迁移、测试、质量命令和 CI 配置均已推送；PR #12 仍保持 Draft，未被合并。2026-07-13 已对同一远端 HEAD 重新执行本报告第 10 节的本地核验，结果保持一致。

## 3. 原P1关闭复审

| 原P1 | 复审结果 | 证据 |
|---|---|---|
| P3-A-002 库存预警 | 已关闭 | `alerts` 模型、规则/去重/静默/处理接口和 `test_phase3_inventory_alerts.py` |
| P3-A-003 补货建议 | 已关闭 | `replenishment` 模型、建议计算、accept/reject 和 `test_phase3_replenishment.py` |
| P3-A-004 生命周期复盘 | 已关闭 | 生命周期 review/decision、确认/拒绝、审计和 `test_phase3_product_lifecycle.py` |
| P3-A-005 经营预警 | 已关闭 | business alert 规则、级别、负责人、去重、静默、关闭和测试 |
| P3-A-006 配置中心 | 已关闭 | tenant/系统范围、版本、审批、回滚、变更记录和 `test_phase3_config_center.py` |
| P3-A-007 报表与导出审计 | 已关闭 | report export 请求、权限、数据范围、占位引用和审计日志；`test_phase3_report_finance_exports.py` |
| P3-A-008 CI与数据质量 | 已关闭 | `.github/workflows/phase3-ci.yml`、质量命令、测试指南和远端阶段3 CI 成功 |
| 阶段3 API 分区缺失 | 部分关闭 | alerts、replenishment、lifecycle、config、finance analytics、report exports 已实现，但与开发B当前 API 合同存在路径不一致，见第 9 节 |

## 4. alerts 与 replenishment 复审

库存与经营预警具备 tenant 规则、唯一去重键、静默、负责人、处理/关闭记录和审计。补货建议包含可售/在途库存、日均销量、交期、数量、日期、置信度和原因，并只能 accept/reject 建议；未发现创建正式采购订单、真实供应商通知或真实 RPA 触发。所有 evaluate 接口均为 mock 输入边界。

## 5. lifecycle 与 config 复审

生命周期 API/RPA 仅作为输入，后端产生 review 建议；确认或拒绝须由具备权限的 internal 用户执行，并记录 decision/audit。未发现自动清仓、停售、归档、下架或改价。配置中心支持 tenant/系统范围、版本、生效、审批、回滚和变更记录；敏感配置以引用/摘要边界处理，未发现真实平台密钥、Token、Cookie 或 Session 存储/返回。

## 6. finance analytics 与 report exports 复审

财务 analytics 位于 `/api/finance/analytics/*`，使用独立财务权限和 tenant 查询；无付款、转账、提现或真实银行/支付接入。`/api/report/exports/*` 提供导出请求和审计占位，导出服务强制 tenant、请求人、数据范围、权限和占位引用，external/RPA 不具备内部导出权限。未生成真实敏感文件。

## 7. tenant、权限、data scope 与审计

- 新增核心模型带 tenant 外键、索引/唯一约束和同 tenant 校验。
- 查询以 `request.user.tenant` 过滤；alerts、replenishment、lifecycle、config、finance 和 reports 均使用对应 internal/finance 权限类。
- 最新修复 `7d9c257` 补强 evaluator 的 data scope 强制校验；全量测试覆盖 tenant、权限、数据范围和越权拒绝。
- 预警处理、生命周期确认、配置审批/回滚、财务查询及导出请求均有操作或专用审计记录。

## 8. 高风险与安全边界

静态新增差异扫描未发现真实平台 HTTP 客户端、真实账号、密钥、Token、Cookie、Session、API Key/API Secret、银行/支付接口、真实业务敏感数据或真实高风险自动化。CI 文档和工作流中的 `placeholder` 密码仅为显式示例值。所有高风险动作保持建议、只读、mock 或人工确认边界；RPA 不被预警直接触发。

## 9. 前后端 API 合同复审

开发A已实现以下分区：

- `/api/internal/alerts/inventory/`、`/api/internal/alerts/business/`
- `/api/internal/replenishment/recommendations/`
- `/api/internal/lifecycle/reviews/`、`/decisions/`
- `/api/internal/config/definitions/`、`/values/`、`/change-logs/`
- `/api/finance/analytics/overview/`、`/reconciliation/`、`/exceptions/`
- `/api/report/exports/`

但开发B当前分支仍调用以下不同路径：

- analytics：`/api/internal/analytics/overview/`、`/sales/`、`/inventory/` 未由开发A实现；当前仅有 metrics/aggregates/aggregate-mock。
- alerts：开发B使用 `/api/internal/alerts/`，后端分别使用 `inventory/` 和 `business/`。
- replenishment：开发B使用 `alerts/`、`suggestions/`，后端使用 `recommendations/`。
- lifecycle：开发B使用 `history/`，后端提供 `decisions/`，合同尚未对齐。
- config：开发B使用 `items/`、`versions/`，后端使用 `definitions/`、`values/`、`change-logs/`。

上述不一致会使开发B关闭 Mock 后发生 404 或字段不匹配，构成未关闭 P1。

## 10. 实际测试与 CI 证据

| 项目 | 结果 |
|---|---|
| `python manage.py check` | 2026-07-13 重新执行，通过 |
| `python manage.py makemigrations --check --dry-run` | 2026-07-13 重新执行，通过，无迁移漂移 |
| `python manage.py migrate --noinput` | 2026-07-13 在独立临时 SQLite 数据库通过 |
| `python manage.py check_phase3_data_quality` | 2026-07-13 迁移后通过 |
| `pytest -q` | 2026-07-13 重新执行，244 通过 |
| 远端 CI | 安全守卫、Django/pytest、阶段3质量门禁、前端构建、Docker、RPA 文档检查均 SUCCESS |
| 合并预检 | `git merge-tree --write-tree` 无冲突 |
| 初次质量命令 | 空临时数据库未迁移时因缺表失败；迁移后通过，不构成代码失败 |

## 11. P0

无。

## 12. P1

1. 开发A与开发B的阶段3 API 路径/资源命名未统一，analytics、alerts、replenishment、lifecycle 和 config 页面不能进入实际联调。

## 13. P2

1. 数据质量命令依赖已迁移数据库；应在运行说明中明确先执行迁移或由 CI 提供临时数据库，避免本地首次执行误报。
2. 补货、预警、生命周期和导出仍应在后续负载测试中补充性能基线，不影响当前安全边界。

## 14. 复审结论

**CONDITIONAL_PASS。** 原 P3-A-002 至 P3-A-008 的功能、权限、审计、CI和数据质量整改已关闭，无 P0；但开发A API 与开发B现有合同仍有 P1 路径不一致，阻断实际前后端联调。

## 15. 是否建议将 PR #12 转为 Ready

**暂不建议。** PR 应继续保持 Draft，待开发A/开发B统一接口合同、更新路径或映射并完成联调复审后再转 Ready。

## 16. 是否建议合并 PR #12

**暂不建议。** 在 P1 API 合同不一致关闭前，合并会使开发B的阶段3页面无法按当前合同接入实际后端。

## 17. 是否允许开发B进入实际 API 联调 R1

**不允许。** 开发B可继续维持 mock/pending；待合同对齐、开发A PR 合并 main、开发B同步最新 main 并完成实际请求/权限失败态验证后，再启动 R1 联调。
