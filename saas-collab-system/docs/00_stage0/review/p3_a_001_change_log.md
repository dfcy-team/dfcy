# P3-A-001 BI指标聚合模型与服务变更日志

## 1. 任务范围

本任务在现有 `backend/apps/reports/` 中实现阶段3 BI 指标聚合底座，仅提供 tenant 隔离的指标口径、来源数据、质量过滤、只读聚合和 Mock 计算能力。

## 2. 新增模型

- `MetricDefinition`：记录指标编码、公式、聚合方式、来源表、时间粒度、维度、权限、敏感性、缺失值规则、口径版本和状态。
- `MetricDataPoint`：记录 tenant、来源表、来源批次、来源记录、计算任务、维度、数值、质量状态和过期时间。
- `MetricAggregate`：记录口径版本、时间范围、维度、聚合值、有效/排除数量、质量状态、正式汇总标记、来源血缘和刷新时间。
- `MetricAggregateLineage`：完整记录每个聚合涉及的来源表、来源批次和计算任务；JSON 仅保存有界摘要，完整审计证据不截断。

## 3. 聚合与数据质量

- 聚合查询强制使用当前 tenant 和当前 tenant 的指标定义。
- 只纳入质量为 `passed`、数值非空且未过期的数据点。
- 跨 tenant、质量失败、缺失和过期数据不能进入正式汇总。
- 无有效数据的计算会保留 `no_valid_data` 质量记录，但 `is_formal=false`，默认聚合列表不展示。
- 来源事实以 tenant、口径、来源表和稳定来源记录 ID 幂等写入；跨批次重复投递更新原事实，不重复聚合。
- 相同 tenant、口径版本、时间范围、粒度和维度重复计算使用幂等更新。
- 输出包含有界的来源表、来源批次和计算任务摘要，以及数据点数量和首尾 ID，不保存无界数据点 ID 列表。
- 完整来源组合写入 `MetricAggregateLineage`，支持超过 100 个批次时继续追踪全部批次和计算任务。
- 指标定义保存缺失数据策略和最小质量通过率；聚合区分 `passed`、`degraded`、`no_valid_data`。
- 质量明细记录通过、缺失、失败、过期、零填充和排除数量；默认质量率 100%，部分失败不会自动成为正式汇总。
- 日/周/月聚合具有对应时间窗口上限，避免单次 Mock 请求扫描无界历史数据。
- 已创建口径只允许停用，不允许原地修改或重新激活；公式、来源或权限变化必须从最新 active 口径创建新版本。
- 版本创建锁定同 tenant、同指标的完整版本链，并停用全部旧 active 版本，保证只存在一个最新 active 版本。
- 初始口径创建、创建新版本和停用均为服务专用操作，必须具备 `analytics.manage`、同 tenant internal actor 和变更原因，并在同一事务写入 `OperationLog`。
- 模型、QuerySet、bulk 和 admin 均不能绕过口径生命周期审计。
- 不支持钻取维度的指标允许使用空 `allowed_dimensions`。
- 聚合快照禁止通过 `bulk_create` 绕过 tenant 和正式质量校验。
- 聚合快照的普通 create/save/update 与 bulk 写入均被禁止，只允许聚合服务持久化。
- 聚合记录来源 ID 水位并排除水位后的新增数据，不再锁定完整日/周/月事实范围。

## 4. 接口与权限

- `GET /api/internal/analytics/metrics/`
- `GET /api/internal/analytics/metrics/{id}/`
- `GET /api/internal/analytics/aggregates/`
- `GET /api/internal/analytics/aggregates/{id}/`
- `POST /api/internal/analytics/aggregate-mock/`

新增 `analytics.view`、`analytics.calculate` 和 `analytics.manage` 动作级权限。只读权限不能执行 Mock 聚合；只有具备 `analytics.manage` 的同 tenant internal 用户可以创建口径版本，且必须提供原因并在同一事务写入 `OperationLog`。external、supplier、RPA 和未授权 internal 用户不能访问。聚合查询与计算同时校验 tenant 和后端 `DataScope`。

列表接口返回 `items` 和分页元数据，`page_size` 最大为 100；聚合列表支持 `period_start`、`period_end`、粒度和正式质量状态过滤。

## 5. 安全与执行边界

- BI 指标仅用于分析，不提供业务执行接口。
- 未连接 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未写入真实凭据、真实平台 URL 或真实业务数据。
- 不创建采购订单，不改变商品状态，不触发 RPA，不执行任何资金动作。
- 测试数据仅使用 `demo`、`mock` 和占位值。

## 6. 测试结果

- P3-A-001 定向测试：`20 passed`。
- P3-A-001 与权限目录定向测试：`22 passed`。
- 全量 pytest：`170 passed`。
- Django check：通过，`0 issues`。
- 迁移一致性：通过，`No changes detected`。
- 全新临时数据库迁移：通过，包含 `reports.0001_initial`、`reports.0002_metricaggregatelineage_and_more` 和 `permissions.0003_seed_analytics_permissions`。
- 权限目录检查：通过，`Permission catalog is complete`。
- 安全文件扫描：通过，未发现禁止文件或高置信度凭据模式。
- `git diff --check`：通过。
