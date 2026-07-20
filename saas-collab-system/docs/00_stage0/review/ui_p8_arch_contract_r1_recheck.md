# UI-P8-ARCH-CONTRACT-R1 独立合同前审报告

## 1. 审核对象与基线

- 审核分支：`feature/ui-p8-production-pilot-security-readiness`
- 审核 HEAD：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- `origin/main` 基线：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 审核对象：UI-P8 范围、任务拆分、API 合同、接口映射、验收清单、进入说明和合同冻结报告。
- 复用核对：UI-P7 已合并合同与代码仅作为 readiness、topology、capacity、recovery、releases、security operations 和 audit 的复用基线。

分支基于指定最新 `main`，本次 UI-P8 变更位于允许的 docs 范围。未发现 backend、frontend、rpa-agent 或 `docs/04_rpa/` 业务改动。工作区中的无关 DOCX 和 `docs/00_stage0/architecture/` 未纳入 UI-P8 合同范围，后续提交必须继续排除。

## 2. 审核结论

**CONDITIONAL_PASS**

未发现 P0。页面边界、UI-P7 复用、安全禁区、初始 capability 状态和总体验收框架合理，但权限/data_scope、逐端点请求响应和状态机职责分离仍有 3 项 P1 未闭合。按冻结规则，P1 关闭并通过 R2 前不得进入 UI-P8 业务实现。

## 3. 页面与复用

- 五个页面任务唯一：控制台负责汇总；安全评审、受控验证、性能验证和准入决策分别承载独立记录及人工流程。
- 已明确复用 `/pilot/readiness`、`/pilot/topology`、`/pilot/capacity`、`/pilot/recovery`、`/pilot/releases`、`/system/security-operations` 和 `/audit/operations`，未发现重复建设同义页面。
- 页面冻结了 loading、empty、401、403、404、409、422、stale、offline 和分页状态。
- 所有 UI-P8 新页面和端点均标记 `pending`；未以路径存在、Mock 或 HTTP 200 误标为 `connected`。

## 4. API合同

已冻结 `/api/internal/pilot/*` 的资源分区、统一成功/失败外壳、分页、筛选、排序、幂等、版本冲突以及 400/401/403/404/409/422 基本语义。未定义 start、execute、shell、deploy、restore、rollback 或 platform-connect 等执行端点。

但当前合同主要以“端点表 + 模块字段集合”描述，尚未逐端点冻结：

- POST、PATCH、submit、approve、reject、cancel、record-result 的精确请求体、必填/可选/禁止字段。
- action 响应体、状态迁移后的返回字段及错误 code。
- `review_reason`、`version`、结果字段、审批字段和 evidence 字段在各 action 中的确切归属。
- 控制台 `readiness_score` 范围、gate/blocker/warning/evidence_counts 的精确对象结构。
- 各列表 `results[]` 摘要结构与详情结构的差异。

该缺口会使前后端和测试产生不同实现，列为 P1-002。

## 5. tenant、权限与data_scope

合同明确 internal 边界、tenant 过滤、exact permission scope、`all` 语义，以及列表过滤、详情 404、请求体越 scope 403 的基本规则。view、plan、review、record 权限已分开，external 与 RPA 无访问路径。

仍存在以下阻断歧义：

1. 创建安全评审、验证、性能和准入决策时资源 ID 尚未产生，但 plan 权限只冻结了 `security_review_ids`、`verification_run_ids`、`performance_run_ids`、`entry_decision_ids`。合同没有说明创建动作应使用环境 scope、只能使用 `all`，还是采用其他创建授权，形成循环授权。
2. 准入决策可引用 UI-P8 证据及 UI-P7 recovery/release 计划，但未冻结创建/提交者附加这些引用时必须具备的 exact permission 和对应 scope 组合。
3. `finance_boundary` 只写“独立财务权限”，未冻结具体财务 permission code、检查端点、检查时机和 scope 语义。

上述问题合并列为 P1-001。建议沿用 UI-P7 的 `environment_ids + resource_ids` 模式：创建按 environment scope 授权，存量资源动作按资源 ID 和环境双重校验；跨资源证据逐类校验其 exact view permission/scope；财务边界冻结唯一财务 permission。

## 6. 状态机与职责分离

三类主流程已给出基本迁移，终态不可修改/删除，状态 action 带版本并以事务、行锁和幂等控制；通用 ORM 和批量入口禁止绕过。准入 `go` 与部署执行也已严格分离。

以下状态和职责规则尚未闭合：

- 范围文档要求试点操作员不能批准自己的计划，但 API 合同只对安全评审和准入决策明确禁止创建人自审；验证/性能仅禁止结果记录人与批准人为同一人。
- `cancel` 使用 plan permission，但未逐状态冻结谁可取消、批准后是否可由创建人单方取消、取消原因和并发行为。
- 安全评审和准入决策包含 `expired` 终态，却未定义触发来源、触发时间、允许的 from 状态、定时或惰性过期策略、责任主体和审计字段。
- 验收要求职责分离冲突返回 409，但各冲突场景尚未形成唯一迁移矩阵。

列为 P1-003。应补充逐资源合法迁移矩阵、actor separation matrix、过期规则以及 cancel/expire 的精确请求和审计合同。

## 7. 证据与不可变审计

- 准入提交会生成 evidence snapshot、hash 和 contract version；过期或 stale 证据不能产生 `ready` 或有效 `go`。
- 成功、失败、权限拒绝、data_scope 拒绝、校验、幂等和状态冲突均要求写不可变审计。
- 审计及终态证据禁止 update/delete/bulk_update/bulk_create，并对 tenant 关联使用保护语义。
- evidence 引用禁止携带认证信息、明文凭据、真实业务数据或完整内部地址。

P2 观察项：`evidence_refs` 仅冻结数量和敏感信息禁令，尚未冻结引用格式、证据类型/注册表、所有权校验、摘要算法和失效传播规则。建议在实现前补齐，以降低证据伪造和跨资源引用歧义。

## 8. 高风险与安全边界

未发现真实平台、AI、银行或支付连接授权，也未发现 Shell、Docker、SSH、SQL、Redis、部署、恢复、回滚、网络或流量执行端点。合同明确禁止明文凭据、真实平台 URL、完整内部地址和真实业务数据。

补货、采购、库存、刊登、改价、清仓、停售、归档、真实 RPA 和资金动作均未被放行。Mock、HTTP 200、`go` 或 API 路径存在不得解释为 `connected`、已部署或已上线。

## 9. 验收可执行性

验收清单覆盖 Django check、migration、专项/全量 pytest、npm ci、组件/全量前端测试、build、受限角色 JWT 浏览器 E2E、Docker Compose、RPA JSON、API 路径、密钥扫描、远端 CI 与 HEAD 一致性。

当前为文档合同前审，未运行尚不存在的 UI-P8 代码、迁移、测试、构建和 E2E；这些项目应在实现复审中实际执行并记录。P1-001 至 P1-003 未关闭前，部分权限、action、过期与职责分离测试无法形成唯一预期结果。

本次已执行 Git 基线、工作区范围、`git diff --check`、路径与合同静态核对。`git diff --check` 仅出现 Windows 换行提示，未发现 whitespace error。

## 10. P0

无。

## 11. P1

| 编号 | 问题 | 影响 | 关闭标准 |
|---|---|---|---|
| UI-P8-ARCH-R1-P1-001 | 创建授权、跨资源证据和财务权限的 permission-specific data_scope 未精确冻结 | 创建动作可能因资源 ID 尚不存在而无法授权，或被错误放宽；准入证据及财务边界可能越 scope | 冻结创建 scope、存量资源 scope、跨资源引用的 exact permission/scope 和唯一财务 permission，并补 403/404 语义与验收矩阵 |
| UI-P8-ARCH-R1-P1-002 | 逐端点请求、响应、字段校验和 action 合同不完整 | 前后端字段、状态返回和错误处理可能分叉 | 为每个端点冻结请求体、响应体、必填/可选/禁止字段、枚举、分页、action 结果与错误 code |
| UI-P8-ARCH-R1-P1-003 | 过期、取消和职责分离的状态机未完全闭合 | 可能出现创建人自批、批准后任意取消、过期状态不可达或并发结果不一致 | 补逐资源迁移矩阵、actor separation matrix、cancel/expire 触发和审计规则，并冻结冲突返回 |

## 12. P2

| 编号 | 问题 | 建议 |
|---|---|---|
| UI-P8-ARCH-R1-P2-001 | evidence 引用格式、类型注册、所有权、摘要和失效传播规则精度不足 | 冻结受控 evidence reference schema 和跨 tenant/资源拒绝规则 |

## 13. 是否允许进入UI-P8实现

**暂不允许。**

先定向关闭 3 项 P1，并执行 `UI-P8-ARCH-CONTRACT-R2` 独立合同复审。R2 达到 PASS 且无未关闭 P0/P1 后，方可进入 UI-P8 实现、Mock/sandbox、组件测试和后端专项测试。

即使 UI-P8 后续 PASS，也不代表允许真实平台接入、生产部署或高风险自动化；这些能力仍须单独安全评审和人工审批。
