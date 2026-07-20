# UI-P8 生产试点运维与专项安全准入范围

## 1. 阶段定位

UI-P8 是 UI-P7 之后的受控扩展阶段。目标是把生产试点前必须具备的安全评审、验证证据、性能证据和人工 Go/No-Go 决策组织为可审计工作面。

UI-P8 只证明“是否具备进入受控生产试点的条件”，不执行生产部署，不连接真实平台，不读取或保存明文凭据，也不放行自动采购、改价、清仓、上下架、RPA 或资金操作。

## 2. 与 UI-P7 的边界

UI-P8 必须复用 UI-P7 已有能力，不创建同义资源：

- 复用 `/pilot/readiness` 展示基础准入门禁。
- 复用 `/pilot/topology` 展示脱敏双主机拓扑。
- 复用 `/pilot/capacity` 展示容量观测。
- 复用 `/pilot/recovery` 和 `/pilot/releases` 记录恢复、发布与回滚计划。
- 复用 `/system/security-operations` 展示凭据引用元数据。
- 复用 `/audit/operations` 查询审计记录。

UI-P8 新增的内容只负责汇总上述证据、登记专项评审、登记受控验证与性能结果，并形成有时效的人工准入结论。

## 3. 页面冻结

| 页面 | 路径 | 用途 | 初始能力状态 |
|---|---|---|---|
| 生产试点控制台 | `/pilot/control-room` | 汇总 readiness、容量、恢复、发布、安全、验证和性能证据 | `pending` |
| 专项安全评审 | `/pilot/security-reviews` | 登记评审范围、风险、证据、审批、拒绝和失效 | `pending` |
| 受控验证记录 | `/pilot/verification-runs` | 登记认证、权限、浏览器E2E、备份恢复和故障切换验证结果 | `pending` |
| 性能容量验证 | `/pilot/performance-runs` | 登记合成负载、阈值和脱敏指标结果 | `pending` |
| 试点准入决策 | `/pilot/entry-decisions` | 基于冻结证据快照形成限时人工 Go/No-Go 结论 | `pending` |

所有页面必须支持 loading、empty、401、403、404、409、422、stale、offline 和分页状态。未实现接口保持 `pending`，仅 Mock 数据保持 `mock`；只有真实受控 API 请求成功且响应声明可用状态时才允许显示 `sandbox`，不得显示 `connected`。

## 4. 用户与职责

| 角色 | 职责 | 禁止事项 |
|---|---|---|
| 试点操作员 | 在获授权环境内创建验证、性能和准入计划，补充 demo/合成证据 | 不能审批自己的计划，不能取消自己已提交或已批准的计划，不能执行主机命令 |
| 安全审核员 | 审核专项安全评审和敏感边界 | 不能查看明文凭据，不能直接修改平台配置 |
| 发布审核员 | 审核恢复、回滚、容量和 Go/No-Go 证据 | 不能由批准动作触发部署 |
| 财务审核员 | 仅审核涉及财务只读边界的专项项 | 不能付款、转账、提现或确认真实资金结果 |
| 审计员 | 只读查看证据、决策和不可变审计 | 不能修改、删除或补写历史审计 |

前端角色与按钮仅用于呈现。后端 tenant、permission、permission-specific data_scope、职责分离和状态机是最终可信边界。

创建动作按 `pilot_environments` scope 授权，不使用尚未产生的资源 ID。资源生成后，列表、详情和 action 再使用各 exact permission 的资源 ID scope。准入决策引用安全评审、验证、性能、恢复和发布证据时，必须逐类重新校验对应 view permission、scope、tenant 和 environment。涉及 `finance_boundary` 的规划和审核同时要求 `finance.view`。

## 5. 状态机冻结

### 5.1 专项安全评审

`draft -> submitted -> approved | rejected`，以及 `draft | submitted | approved -> expired`

- `draft` 可由创建人编辑非关键说明。
- `submitted` 后内容冻结，只能由具备 review 权限且不是创建人的审核员处理。
- `approved/rejected/expired` 为终态；重新评审必须创建新版本。
- 到期批准不得用于新的准入决策。
- `draft/submitted/approved` 到达 `expires_at` 后由 system 到期处理器转为 `expired`；读请求完成惰性过期后返回 expired/stale，PATCH/submit 等写动作完成过期审计后返回 409，过期 draft 不得修改或提交。

### 5.2 受控验证与性能记录

`draft -> submitted -> approved -> passed | failed | manual_required`

以及：`draft | submitted | approved -> cancelled`

- UI 只创建计划和记录外部受控测试结果，不提供执行命令端点。
- `passed/failed/manual_required/cancelled` 为终态。
- 结果必须带证据引用、摘要、执行环境别名、数据类别和记录人。
- 不允许把 `approved` 当作 `passed`，也不允许把 HTTP 200 自动解释为验证通过。
- 创建人不得批准自己的计划，结果记录人不得是批准人。取消固定要求专用 cancel permission；submitted/approved 计划不得由创建人取消，且必须写明原因。

### 5.3 试点准入决策

`draft -> submitted -> approved | rejected`，以及 `draft | submitted | approved -> expired`

- 决策值仅允许 `go` 或 `no_go`，并与审批状态分开保存。
- `go` 只表示允许进入限定范围的受控试点准备，不表示部署已经执行。
- 决策必须引用不可变证据快照及哈希，并设置有效期。
- 创建人不能批准自己的决策；批准后不得修改、删除或复用到其他 tenant/环境。
- `expires_at` 在创建和修改时必须位于未来 30 天内；`draft/submitted/approved` 到期后由 system 转为 `expired`，读请求返回 expired/stale，写动作返回 409；过期与人工 action 并发时只允许一个事务成功。

## 6. 高风险边界

UI-P8 页面和 API 一律禁止：

1. Web shell、Docker socket、SSH、SQL、Redis 命令或文件系统执行。
2. 保存或显示明文 Token、Cookie、Session、API Key/API Secret、私钥、银行密码或备份密钥。
3. 连接真实 BigSeller、Shopee、TikTok/TK、AI provider、银行或支付平台。
4. 执行部署、恢复、回滚、流量切换、网络策略或防火墙变更。
5. 自动采购、通知真实供应商、改库存、刊登、改价、清仓、停售、归档。
6. 触发真实 RPA、付款、转账、提现或财务自动确认。
7. 由预警、容量、分析、智能体或准入结论直接触发任何高风险动作。

## 7. 角色任务拆分

### 架构设计员

- UI-P8-ARCH-001 冻结生产试点页面与复用边界。
- UI-P8-ARCH-002 冻结专项安全评审、验证、性能和准入状态机。
- UI-P8-ARCH-003 冻结 API、permission、data_scope、审计和错误合同。
- UI-P8-ARCH-004 执行合同前审、实现复审和发布门禁。

### 开发A

- UI-P8-A-001 建设只读控制台聚合 API。
- UI-P8-A-002 建设专项安全评审记录和职责分离。
- UI-P8-A-003 建设验证与性能计划/结果记录，不建设执行器。
- UI-P8-A-004 建设限时准入决策、证据快照和不可变审计。
- UI-P8-A-005 补 tenant、data_scope、越权、失效、并发和绕过测试。

### 开发B

- UI-P8-B-001 建设试点控制台和证据状态展示。
- UI-P8-B-002 建设专项安全评审列表、详情和人工审核交互。
- UI-P8-B-003 建设验证与性能记录页面。
- UI-P8-B-004 建设人工准入决策页面和高风险边界提示。
- UI-P8-B-005 补真实组件状态、路由、权限和 Mock/API 测试。

### 测试人员

- UI-P8-QA-001 执行角色、tenant、data_scope 和职责分离矩阵。
- UI-P8-QA-002 执行状态机、防绕过、幂等、失效和不可变审计测试。
- UI-P8-QA-003 使用 demo/合成数据执行浏览器 E2E、构建和安全扫描。
- UI-P8-QA-004 核对页面不包含主机执行、明文凭据或真实平台入口。

## 8. 阶段完成标准

- 合同前审无未关闭 P0/P1 后方可实现。
- 实现复审无未关闭 P0/P1 且远端 CI 成功后方可合并。
- UI-P8 PASS 只允许进入受控生产试点审批准备，不自动允许真实平台接入或生产发布。
