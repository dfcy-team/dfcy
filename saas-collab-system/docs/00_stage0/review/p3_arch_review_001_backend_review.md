# P3-ARCH-REVIEW-001 开发A阶段3后端预合并审核报告

## 1. 审核对象

- 审核分支：`origin/feature/phase3-a-analytics-alerts-config`
- 审核提交：`fe17a2acb1d3287464ab12d607bffd218ff6abf4`
- 对比基线：`origin/main` / `28b3e068a852060092e7f0b3a56c26c2c1290407`
- 分支状态：领先基线 1 个提交、落后 0 个提交，包含阶段3规划基线。

## 2. 修改范围

本次变更新增 `reports` 应用、指标聚合模型/服务/内部接口、权限种子、迁移和测试，并补充后端说明及开发A变更日志。未修改 `frontend/`、`rpa-agent/`、`docs/04_rpa/`、环境文件或真实平台配置。

## 3. 架构与安全审核

- `MetricDefinition`、`MetricDataPoint`、`MetricAggregate` 和指标血缘均带 tenant 外键、唯一约束及 tenant 一致性校验。
- 内部接口位于 `/api/internal/analytics/*`；查询以当前用户 tenant 过滤，并使用 `analytics.view`、`analytics.calculate` 与数据范围过滤。
- external 与 RPA 用户被内部 analytics 权限类拒绝；财务敏感指标仍要求独立的 `finance.view` 权限。
- 指标定义强制 `allows_automated_decision=False`，聚合接口仅为 `aggregate-mock`，没有生成采购单、改价、清仓、付款或其他高风险执行接口。
- 新增代码未发现真实平台 HTTP 客户端、真实凭据、真实平台接入或 RPA 自动化；生产凭据存储的未配置默认值仍保持禁用。
- 规划中的 `/api/internal/analytics/overview/`、`sales/`、`inventory/` 等接口尚未实现；前端规划将其标为 `mock/pending`，未误标为 connected。

## 4. 实际核验

在独立 detached worktree 执行：

| 项目 | 结果 |
|---|---|
| `python manage.py check` | 通过 |
| `python manage.py makemigrations --check --dry-run` | 通过，无迁移漂移 |
| `pytest tests/test_phase3_bi_metrics.py -q` | 20 通过 |
| `pytest -q` | 170 通过 |
| `git merge-tree --write-tree origin/main <branch>` | 无冲突 |
| 新增差异凭据扫描 | 未发现真实凭据模式 |

## 5. P0 / P1 / P2

### P0

无。

### P1

1. 开发A远端分支尚未创建 GitHub PR，因此没有可审计的 PR CI 记录，也不能进入正式合并流程。

### P2

1. 本次仅完成 P3-A-001 的 BI 指标聚合基础；预警、补货建议、生命周期、配置中心、导出审计和数据质量等后续 P3-A 任务仍需按规划分批交付，不作为本次单提交的越界项。

## 6. 审核结论

**CONDITIONAL_PASS**。代码范围、tenant/权限边界、Mock 安全边界和实际测试均通过；待开发A基于当前提交创建 PR 并完成远端 CI 后，可进行该 PR 的合并复核。当前不建议绕过 PR 直接合并分支。
