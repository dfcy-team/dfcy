# UI-P8-ARCH-CONTRACT-R2 独立合同复审报告

## 1. 复审对象与基线

- 复审分支：`feature/ui-p8-production-pilot-security-readiness`
- 当前 HEAD：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- `origin/main` 共同基线：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 原报告：`ui_p8_arch_contract_r1_recheck.md`
- 整改记录：`ui_p8_contract_r1_p1_fix_change_log.md`
- 复审范围：UI-P8 scope、API 合同、总映射、验收清单、进入说明及 UI-P7 复用边界。

本次只新增本复审报告，未修改合同或业务代码。工作区中的无关 DOCX 与 `docs/00_stage0/architecture/` 未纳入复审，后续提交仍须排除。

## 2. 复审结论

**CONDITIONAL_PASS**

未发现 P0。三项原 P1 均已形成明确整改方向，创建授权、跨资源证据、财务权限、action 路径、专用 cancel 权限、system 过期和不可变审计均比 R1 完整；但每项仍存在一个会影响唯一实现或越权测试的未闭合点，因此暂不能判定原 P1 全部关闭。

## 3. 原P1关闭情况

| 原P1编号 | 原问题 | 是否关闭 | 已完成 | 未闭合项 |
|---|---|---|---|---|
| UI-P8-ARCH-R1-P1-001 | 创建授权、跨资源证据和财务权限 data_scope 不精确 | 否 | 创建使用 plan + `pilot_environments`；证据逐类校验；财务固定叠加 `finance.view + finance_scope` | PATCH 可改变 environment/owner/finance_scope，但存量 action 只强制资源 ID scope，目标环境和 owner tenant 约束未唯一冻结 |
| UI-P8-ARCH-R1-P1-002 | 逐端点请求响应合同不完整 | 否 | 全路径、header、body、Detail/Summary、分页、幂等、版本和错误 code 已补齐 | 若干请求字段仍缺精确 cardinality、长度、非负范围和 nullable/required 规则，无法形成唯一 422 测试 |
| UI-P8-ARCH-R1-P1-003 | 过期、取消和职责分离未闭合 | 否 | 合法迁移矩阵、创建人自审限制、记录/批准分离、专用 cancel 和 system 过期已补齐 | entry decision 的 expires_at 校验缺失；draft 到期后的 submit/查询行为未定义，expired 仅允许由 submitted/approved 到达 |

## 4. 创建、跨资源与财务data_scope

已确认：

- 四类创建均以 exact plan permission 和 `pilot_environments` 授权，不依赖未来资源 ID。
- 详情和 action 以各自 exact permission 的资源 ID scope 为基础，view scope 不代替 action scope。
- entry decision 的五类引用分别要求来源 view permission、scope、tenant 和 environment 一致。
- `finance_boundary` 的创建、修改、提交、批准和拒绝固定叠加 `finance.view`，并以脱敏 `finance_scope.platforms/currencies` 逐值比对。
- ALL、CUSTOM、无 scope、未知 key、非法值以及列表/详情/请求体的 403/404 基本语义已冻结。

仍存在授权属性变更缺口：四类 draft PATCH 都允许修改创建字段，包括 `environment`；安全评审还允许修改 `owner_id` 和 `finance_scope`。第 3.3 节只要求 CUSTOM action 命中目标资源 ID，并规定“如同时包含 `pilot_environments`”才校验环境。因此仅获某资源 ID scope 的 plan 用户可能把 draft 移动到其无环境授权的目标环境。`owner_id` 也未冻结必须为同 tenant internal 用户、是否允许代他人指定，以及所需 permission/scope。

该问题使原 P1-001 未关闭。关闭标准：PATCH 修改 environment 时必须重新要求 plan scope 覆盖目标环境；当前环境和目标环境均应审计。owner_id 必须固定为同 tenant 可分配用户，并冻结“仅自己/可代分配”的权限规则；finance_scope 变化必须重新执行 `finance.view` 目标 scope 校验。

## 5. 逐端点请求响应合同

端点方法、完整路径和 exact permission 已唯一登记。submit、approve、reject、record-result、cancel 均有请求字段、成功 Detail 响应、状态迁移、幂等键和版本要求；HTTP 400/401/403/404/409/422 的主 code 无冲突。列表摘要和 entry evidence snapshot 也已结构化。

仍缺少以下能直接决定 422 的字段合同：

- `success_criteria` 每项长度已给出，但数组最小/最大项数、空值和重复语义未给出。
- verification 的 `result_summary/error_code/error_message` 与 performance 的 `result_summary` 缺少长度上限；请求中的 required/nullable 仅部分按结果状态说明。
- performance 的 `p50_ms/p95_ms` 没有非负范围和 `p50 <= p95` 约束。
- entry decision 的 `expires_at` 未冻结必须晚于当前时间、最大有效期或 PATCH 后校验。
- `owner_id` 的类型虽为正整数，但没有请求对象存在性、tenant 和用户类型校验错误语义。

这些字段直接位于 action 或创建/PATCH 合同，不能留给前后端各自决定，原 P1-002 尚未关闭。关闭标准：为上述字段补 required、nullable、长度/数量、数值关系和对应 422 code；未提供字段与显式 null 的语义必须区分。

## 6. 状态机、过期、取消与职责分离

已确认：

- 四类资源已有 from/action/to/exact permission/actor 矩阵，矩阵外迁移返回 409。
- 创建人不能批准自己的安全评审、验证、性能或准入决策；结果记录人不能是批准人。
- verification/performance cancel 使用专用 exact permission，submitted/approved 拒绝创建人取消。
- submitted/approved 安全评审和准入决策由 system 定时或惰性检查进入 expired，使用行锁、版本和不可变审计。
- 通用 PATCH、save、QuerySet、bulk、admin 和级联删除不得绕过状态机。

仍存在 draft 到期缺口：合同只允许 `submitted/approved -> expired`，但 draft 同样持有 `expires_at`。安全评审仅规定创建时有效期，准入决策甚至没有同等有效期范围；当 draft 已到期后执行 GET、PATCH 或 submit，合同没有规定保持 draft、返回 409/422，还是转 expired。惰性检查列出了 submit，却没有 draft 可达的 expire 迁移，产生不可达状态与并发歧义。

原 P1-003 尚未关闭。关闭标准：明确 draft 到期策略。建议 draft 到期后保持不可提交/不可修改并由 system `draft -> expired`，或者明确定义 draft 无业务到期、submit 必须提供新的未来有效期；两种方案只能保留一种，并同步迁移矩阵、错误 code、审计和并发测试。

## 7. 证据、审计与安全边界

- evidence snapshot 已冻结 source 类型、ID、version、status、digest、刷新和失效时间；来源变化使旧快照 stale。
- 成功、失败、权限、scope、422、幂等、版本、状态、过期和取消均要求不可变审计。
- 审计和终态证据禁止 update/delete/bulk 绕过，tenant 关联采用 PROTECT 或脱敏保留。
- 未发现真实平台、AI、银行、支付、主机命令、部署、恢复、流量切换或真实 RPA 执行授权。
- 未放行自动采购、库存修改、刊登、改价、清仓、停售、归档或资金动作。
- pending、Mock、HTTP 200 和 `go` 均未被解释为 connected 或已部署。

P2 观察：`scope_summary`、`target_alias`、`result_summary`、`review_reason`、`cancel_reason` 和错误说明为自由文本。合同禁止敏感字段名和 evidence 中的凭据，但尚未冻结自由文本的敏感模式拒绝/脱敏策略与受控 alias 注册校验。建议在实现前补充，防止凭据、完整内部地址或真实业务数据通过文本值进入审计。

## 8. P0

无。

## 9. P1

| 编号 | 问题 | 关闭标准 |
|---|---|---|
| UI-P8-ARCH-CONTRACT-R2-P1-001 | PATCH 修改环境、owner 和 finance_scope 时未完整执行目标授权属性校验 | 冻结目标环境 scope、owner 同 tenant/代分配权限、finance_scope 重算规则及 403/404/422 |
| UI-P8-ARCH-CONTRACT-R2-P1-002 | 若干创建和 record-result 字段的 cardinality、长度、范围、required/nullable 不完整 | 补逐字段约束、跨字段关系和唯一 422 预期 |
| UI-P8-ARCH-CONTRACT-R2-P1-003 | draft 到期与 entry decision 有效期规则未闭合 | 选择并冻结唯一 draft 到期策略，补迁移、错误、审计、惰性检查与并发测试 |

## 10. P2

| 编号 | 问题 | 建议 |
|---|---|---|
| UI-P8-ARCH-CONTRACT-R2-P2-001 | 自由文本和 target_alias 的敏感值防护未精确冻结 | 增加受控 alias 注册、敏感模式拒绝/脱敏、长度与审计测试 |

## 11. 是否允许进入UI-P8实现

**暂不允许。**

应先定向关闭本报告 3 项 P1，再执行独立 `UI-P8-ARCH-CONTRACT-R3`。R3 达到 PASS 且无未关闭 P0/P1 后，方可进入 UI-P8 后端、前端、Mock/sandbox 和测试实现。

即使后续合同 PASS，也不代表允许真实平台接入、生产部署、主机执行或高风险自动化。
