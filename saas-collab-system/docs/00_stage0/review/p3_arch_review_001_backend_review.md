# P3-ARCH-REVIEW-001 开发A阶段3后端成果审核报告

## 1. 审核对象

- 审核对象：`origin/feature/phase3-a-analytics-alerts-config`
- 审核提交：`711e037349b299601a1b540eebf64def10d4f73f`
- 对比基线：`origin/main` / `28b3e068a852060092e7f0b3a56c26c2c1290407`
- 审核性质：只读差异与独立 worktree 实测；未修改开发A代码，未合并开发分支。

## 2. 分支与基线

该分支包含阶段3规划基线，相对 `origin/main` 领先 2 个提交、落后 0 个提交。GitHub PR #12 已创建，base 为 `main`、head 为当前分支，状态 OPEN、非 Draft、CLEAN；其 HEAD 与本报告审核提交一致，已列出的安全守卫、Django/pytest、前端构建、Docker 配置和 RPA 文档检查均为 SUCCESS。

## 3. 修改范围

修改集中于 `backend/`、`backend/tests/` 与 `docs/00_stage0/review/`：新增 `reports` 应用、指标聚合模型/服务/内部接口、权限种子、迁移和测试。未修改 `frontend/`、`rpa-agent/`、`docs/04_rpa/`、`.env`、证书、数据库文件、运行产物或真实平台配置。

## 4. BI指标聚合审核

**通过（P3-A-001）。**

- `MetricDefinition`、`MetricDataPoint`、`MetricAggregate` 与 `MetricAggregateLineage` 已实现，指标编码、公式、来源表、时间粒度、维度、权限码、缺失数据策略、质量阈值和版本均在模型中集中管理。
- 所有核心模型带 tenant 外键、tenant 约束和一致性校验；查询使用当前用户 tenant，并按 `analytics.view`、`analytics.calculate`、指标权限码与 data scope 过滤维度。
- 财务指标要求独立 `finance.view` 权限；external 与 RPA 用户不能访问内部 analytics 接口。
- 支持时间范围、日/周/月粒度、维度哈希、数据血缘、质量状态、异常/缺失数据排除和零填充策略。
- `allows_automated_decision=False` 受模型与数据库约束保护；聚合结果仅用于分析，`aggregate-mock` 不触发采购、RPA、财务或其他业务动作。
- 本次新增快照一致性修复：聚合在事务中锁定并验证最新有效指标定义，物化单一有界数据点快照后再计算数值、质量与血缘；过期版本对象不能绕过版本状态参与聚合。

## 5. 库存预警审核

**未在本分支交付（P3-A-002）。** 未发现缺货/超储风险、库存覆盖天数、安全库存、阈值、去重或静默周期的后端模型、服务、接口和测试。

## 6. 补货建议审核

**未在本分支交付（P3-A-003）。** 未发现建议补货量、日期、置信度、原因、可售/在途库存、日均销量或采购交期计算服务。未发现自动创建采购订单、自动通知供应商或自动触发 RPA 的实现；规划边界仍要求建议经授权人员确认。

## 7. 生命周期复盘审核

**未在本分支交付（P3-A-004）。** 未发现生命周期复盘模型、状态建议、人工确认、状态审计或非法流转拦截的阶段3新增实现。未发现自动改价、下架、清仓、停售或归档代码。

## 8. 经营预警审核

**未在本分支交付（P3-A-005）。** 未发现预警类型、级别、规则、负责人、处理状态、关闭条件、去重或静默周期的新增规则引擎。未发现预警直接触发真实 RPA、付款、转账或提现的实现。

## 9. 配置中心审核

**未在本分支交付（P3-A-006）。** 未发现 tenant/系统级配置、版本、生效时间、权限、审计、回滚或默认值的阶段3新增后端实现。未发现保存或返回真实平台密钥、Cookie、Session 或明文 Token 的代码。

## 10. 报表与导出审核

**部分基础已交付，其余未交付（P3-A-007）。** `/api/internal/analytics/*` 提供 tenant 过滤、权限过滤、分页、时间范围与统一响应的指标查询；`/api/report/*` 导出、导出权限、审计、大数据量限制、财务脱敏和 external/RPA 导出拦截尚未在本分支实现。未生成真实敏感数据测试文件。

## 11. CI与数据质量

| 核验项目 | 结果 |
|---|---|
| `python manage.py check` | 已执行，通过 |
| `python manage.py makemigrations --check --dry-run` | 已执行，通过，无迁移漂移 |
| `pytest tests/test_phase3_bi_metrics.py -q` | 已执行，20 通过 |
| `pytest -q` | 已执行，172 通过 |
| tenant/权限/数据质量测试 | 已包含在阶段3指标测试中并通过 |
| 远端 CI | 已执行，安全守卫、Django/pytest、前端构建、Docker 配置和 RPA 文档检查均为 SUCCESS |
| Docker config | 已由 PR #12 远端 CI 执行并通过 |
| RPA JSON/文档检查 | 已由 PR #12 远端 CI 执行并通过 |

## 12. tenant与权限

BI新增模型、服务和 API 均具备 tenant 隔离意识。内部接口限定 internal 用户；指标与维度受权限和 data scope 控制，财务指标另需财务权限。当前分支没有供应商、external、RPA 或财务执行接口的越界新增。

## 13. 安全扫描

对 `origin/main...origin/feature/phase3-a-analytics-alerts-config` 新增差异执行凭据与平台调用扫描：未发现真实 `.env`、Token、Cookie、Session、API Key/API Secret、私钥、真实平台 HTTP 调用、真实银行/支付连接、真实订单/供应商/财务数据或运行产物。测试中的 `demo`、`mock`、`not-a-real-secret` 示例不构成真实凭据。

## 14. P0

无。

## 15. P1

1. P3-A-002 至 P3-A-008 未交付：库存预警、补货建议、生命周期复盘、经营预警、配置中心、报表/导出审计和阶段3专项 CI/数据质量能力均缺少后端实现与测试证据。
2. 阶段3 API 契约中的 `/api/internal/alerts/*`、`/api/internal/replenishment/*`、`/api/internal/lifecycle/*`、`/api/internal/config/*`、`/api/finance/analytics/*` 和 `/api/report/*` 未实现；当前仅提供 `/api/internal/analytics/metrics/`、`/aggregates/`、`/aggregate-mock/`，不足以支持开发B阶段3页面的实际接口联调。

## 16. P2

1. 指标聚合的聚合上限和快照一致性实现已具备单元测试；仍建议在数据量接近上限时补充性能基线与数据库监控证据。

## 17. 整改建议

1. 开发A应继续交付 P3-A-002 至 P3-A-008，并为每个 API 分区补充 tenant、权限、数据范围、审计、数据质量和安全测试。
2. 补货、生命周期、预警、财务和配置能力必须保持建议/只读/人工确认边界，不得自动采购、清仓、停售、归档、改价、付款、转账、提现或触发真实 RPA。
3. 在前端将接口标记为 connected 前，后端需实现规划路径，并提供统一响应、权限失败态和实际联调证据。

## 18. 审核结论

**CONDITIONAL_PASS。** P3-A-001 BI指标聚合基础及本次快照一致性修复满足 tenant、权限、安全、测试和远端 CI 要求，且无 P0；但 P3-A-002 至 P3-A-008 和阶段3规划 API 分区尚未交付，存在阻断开发B实际接口联调的 P1，不能视为阶段3后端整体完成。

## 19. 是否建议合并开发A PR

**不建议以“阶段3后端整体先行合并”口径合并 PR #12。** 当前 HEAD 为 `711e037`，PR 为非 Draft、CLEAN 且远端 CI 成功，代码可作为严格限定的 P3-A-001 独立成果另行决策；但在本任务的整体后端准入范围内，必须先关闭上述 P1。若 PR HEAD、CI 或文件范围变化，必须重新复审。

## 20. 开发A合并后开发B实际联调接口清单

若仅合并 PR #12，开发B可实际使用的后端接口仅为：

- `GET /api/internal/analytics/metrics/`
- `GET /api/internal/analytics/metrics/{id}/`
- `GET /api/internal/analytics/aggregates/`
- `GET /api/internal/analytics/aggregates/{id}/`
- `POST /api/internal/analytics/aggregate-mock/`

开发B阶段3页面目前规划但仍不能切换为 connected 的接口包括：

- `/api/internal/analytics/overview/`、`/sales/`、`/inventory/`
- `/api/internal/alerts/*`
- `/api/internal/replenishment/*`
- `/api/internal/lifecycle/*`
- `/api/internal/config/*`
- `/api/finance/analytics/*`
- `/api/report/*`

## 21. 是否允许进入开发B R1 联调阶段

**不允许进入实际接口联调 R1。** 开发B可继续维持 Mock/pending 页面和接口契约核验，但必须等待上述后端规划接口实现、合并 main 并通过权限/数据范围测试后，才能把阶段3页面切换为实际联调或 connected。
