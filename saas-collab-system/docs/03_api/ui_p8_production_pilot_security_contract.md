# UI-P8 生产试点运维与专项安全准入 API 合同

## 1. 合同原则

- API 前缀固定为 `/api/internal/pilot/*`，仅允许获授权的 `internal` 用户访问。
- 所有查询和写入先按当前认证用户 tenant 隔离，再执行当前 exact permission 的 data_scope。
- API 只登记计划、证据、人工评审和准入结论，不执行主机、平台、RPA、部署、恢复、网络或资金动作。
- 财务边界固定使用独立权限 `finance.view`；只读取脱敏状态，不返回财务明细、账户或流水。
- 所有 UI-P8 新端点初始为 `pending`。路径存在、Mock 或 HTTP 200 均不能单独作为 `connected` 证据。
- 请求和响应拒绝未知字段；禁止字段出现时返回 `422 FORBIDDEN_FIELD`，不得静默忽略。

## 2. 公共类型、响应、分页与错误

### 2.1 公共类型

| 类型 | 合同 |
|---|---|
| `id` | 正整数 |
| `version` | 从 1 开始的正整数 |
| `datetime` | ISO 8601 UTC，响应统一带 `Z` |
| `reason` | 去除首尾空白后 1 至 1000 字符 |
| `review_reason/cancel_reason` | 与 `reason` 相同，均为必填非空审计原因 |
| `environment` | `sandbox/pilot`，必须是当前 tenant 已登记受控环境 |
| `evidence_refs` | 1 至 50 个唯一字符串，每项 1 至 200 字符；仅允许受控内部引用，不接受凭据化 URL、文件正文或完整内部地址 |
| `Idempotency-Key` | 创建和所有 action 必填，1 至 160 个可打印 ASCII 字符 |

创建、PATCH 和 action 请求必须使用 `Content-Type: application/json`。创建及 action 返回后端生成的当前详情对象；不返回空对象作为成功占位。

请求字段规则：

- 端点 body 中列出的字段默认全部 required，只有明确标注 `optional` 或 `nullable` 的字段例外。
- PATCH 固定要求 `version`，并至少提供一个该端点列出的 mutable 字段；字段省略表示保持原值，显式 null 仅允许用于标注 nullable 的字段。
- action body 字段不得省略或额外增加；reason 类字段不允许 null、空白或仅空格。
- 数组不得包含 null、空字符串或重复值；对象拒绝未知 key。
- 所有字符串先去除首尾空白再执行长度和格式校验。

### 2.2 成功与分页

成功响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

列表分页：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {
    "count": 0,
    "next": null,
    "previous": null,
    "results": []
  }
}
```

- `page` 为从 1 开始的正整数，不设固定最大页码。
- `page_size` 默认 20，允许 1 至 100。
- 非列表接口不得返回伪分页字段。
- 错误响应固定为 `success=false`、`data=null`。

### 2.3 错误

| HTTP | code | 语义 |
|---|---|---|
| 400 | `REQUEST_INVALID` | JSON、查询、排序、日期或请求结构错误 |
| 401 | `AUTH_REQUIRED` | 未认证或会话失效 |
| 403 | `PERMISSION_DENIED` | 用户类型、exact permission 或财务权限不足 |
| 403 | `DATA_SCOPE_INVALID` | scope 缺失、未知 key、非法值或请求值超授权范围 |
| 404 | `NOT_FOUND` | 资源不存在，或不在 tenant/data_scope 内 |
| 409 | `STATE_CONFLICT` | 非法迁移、终态重复动作、过期或职责分离冲突 |
| 409 | `VERSION_CONFLICT` | 请求版本与当前版本不一致 |
| 409 | `IDEMPOTENCY_CONFLICT` | 幂等键已用于不同请求 |
| 422 | `VALIDATION_ERROR` | 字段或业务规则失败 |
| 422 | `FORBIDDEN_FIELD` | 出现合同明确禁止的字段 |

所有端点均可能返回 401/403。列表查询参数错误返回 400；详情及 action 对不可见对象返回 404；创建、PATCH 和 action 字段失败返回 422；创建及 action 幂等冲突返回 409；PATCH/action 版本冲突返回 409。

## 3. permission-specific data_scope

### 3.1 精确 permission 与允许 key

| Exact permission | 允许的 CUSTOM scope key |
|---|---|
| `pilot.control.view` | `pilot_environments` |
| `pilot.security_review.view` | `pilot_environments`、`security_review_ids` |
| `pilot.security_review.plan` | `pilot_environments`、`security_review_ids` |
| `pilot.security_review.review` | `pilot_environments`、`security_review_ids` |
| `pilot.verification.view` | `pilot_environments`、`verification_run_ids` |
| `pilot.verification.plan` | `pilot_environments`、`verification_run_ids` |
| `pilot.verification.review` | `pilot_environments`、`verification_run_ids` |
| `pilot.verification.record` | `pilot_environments`、`verification_run_ids` |
| `pilot.verification.cancel` | `pilot_environments`、`verification_run_ids` |
| `pilot.performance.view` | `pilot_environments`、`performance_run_ids` |
| `pilot.performance.plan` | `pilot_environments`、`performance_run_ids` |
| `pilot.performance.review` | `pilot_environments`、`performance_run_ids` |
| `pilot.performance.record` | `pilot_environments`、`performance_run_ids` |
| `pilot.performance.cancel` | `pilot_environments`、`performance_run_ids` |
| `pilot.entry.view` | `pilot_environments`、`entry_decision_ids` |
| `pilot.entry.plan` | `pilot_environments`、`entry_decision_ids` |
| `pilot.entry.review` | `pilot_environments`、`entry_decision_ids` |

- `pilot_environments`：1 至 20 个唯一值，仅 `sandbox/pilot` 且必须已在当前 tenant 登记。
- 四类资源 ID key：1 至 100 个唯一正整数，必须属于当前 tenant 对应资源。
- `ALL` 仅覆盖 exact permission 在当前 tenant 已登记资源，不代表系统全局。
- 无 scope、空 scope、未知 key、空字符串、重复值、未登记值、非法值或超限值返回 `403 DATA_SCOPE_INVALID`。
- system role 不绕过 tenant；superuser 绕过只允许测试/受控运维入口且必须审计。

### 3.2 创建授权

资源尚无 ID 时不得使用未来资源 ID 授权。四类 POST 创建固定执行：

1. 检查对应 `*.plan` exact permission。
2. `ALL` 可创建当前 tenant 已登记环境内资源。
3. `CUSTOM` 必须包含 `pilot_environments`，且请求 `environment` 必须在其中。
4. CUSTOM 中的资源 ID key 不授予创建权，也不能替代 `pilot_environments`。
5. 创建成功后资源 ID 自动落入 tenant 边界，但后续可见/可操作性仍由各 exact permission 自身 scope 决定。

### 3.3 列表、详情、PATCH 与 action

- 列表按 exact permission scope 中已提供的合法 key 做交集过滤；合法但无结果返回空分页。
- 详情必须命中 exact view permission 的资源 ID scope；越 scope 返回 404。
- PATCH、submit、approve、reject、record-result、cancel 使用各自动作 exact permission 的 scope，不继承 view scope；cancel 固定使用专用 `*.cancel` permission。
- CUSTOM action scope 必须包含目标资源 ID；如同时包含 `pilot_environments`，还必须匹配资源环境。
- PATCH 或请求体引用超 scope 值返回 403，且不得产生业务写入。

PATCH 授权属性规则：

1. 任何 PATCH 修改 `environment` 时，除目标资源 ID scope 外，CUSTOM plan scope 必须显式包含原环境和目标环境；`ALL` 也只允许当前 tenant 已登记环境。缺失目标环境授权返回 403。
2. 环境迁移成功审计同时记录 `source_environment/target_environment`，并对目标环境重新执行全部资源引用校验。
3. `owner_id` 为服务端只读字段：创建时固定为当前 actor，PATCH 不接受 owner_id；UI-P8 不提供 owner 转移端点。需要转移时必须另行冻结权限和审计合同。
4. 安全评审 PATCH 修改 `review_type` 或 `finance_scope` 时，必须按修改后的组合重新执行第 3.5 节；从 finance_boundary 改为其他类型时 finance_scope 必须显式为 null。

### 3.4 跨资源证据授权

创建、PATCH 和 submit 准入决策时，除 `pilot.entry.plan` 外，引用方必须逐类具备：

| 引用字段 | 必须具备 exact permission | 必须命中的 scope |
|---|---|---|
| `security_review_ids` | `pilot.security_review.view` | `security_review_ids`，以及存在时的 `pilot_environments` |
| `verification_run_ids` | `pilot.verification.view` | `verification_run_ids`，以及存在时的 `pilot_environments` |
| `performance_run_ids` | `pilot.performance.view` | `performance_run_ids`，以及存在时的 `pilot_environments` |
| `recovery_plan_ids` | `pilot.recovery.view` | UI-P7 `recovery_plan_ids` 与 `environment_ids` |
| `release_plan_ids` | `pilot.release.view` | UI-P7 `release_plan_ids` 与 `environment_ids` |

所有引用必须同 tenant、同 environment；缺 permission 返回 403，越 scope 引用返回 403，不存在或已被保护隐藏的引用返回 404。后端不得仅凭前端传入 ID 建立引用。

### 3.5 财务边界

- `review_type=finance_boundary` 的创建、PATCH、submit、approve 和 reject 均要求动作自身 pilot permission，同时具备 `finance.view`。
- 财务边界评审必须携带脱敏 `finance_scope`：`platforms` 为 1 至 20 个已登记平台编码，`currencies` 为 1 至 20 个大写 ISO 4217 编码；两者不得为空或重复。其他 review_type 的 `finance_scope` 必须为 null。
- `finance.view` 按 UI-P6 已冻结的 `platforms/currencies` scope 与 `finance_scope` 逐值校验；没有合法财务 scope 或任一请求值超 scope 返回 403。
- 财务审核只允许引用脱敏门禁状态，不得引用账单、账户、流水或银行明细。
- 控制台仅聚合后端已脱敏的财务门禁状态，不返回财务来源明细；缺 `finance.view` 时该门禁显示 `restricted`，整体不得计算为 `ready`。

## 4. 资源模型

### 4.1 `ControlRoom`

`environment:enum`、`capability_status:enum[pending,sandbox,degraded,disabled]`、`readiness_status:enum[blocked,conditional,ready,stale]`、`readiness_score:decimal[0..100](nullable)`、`gate_summary:GateSummary[]`、`blockers:Finding[]`、`warnings:Finding[]`、`evidence_counts:EvidenceCounts`、`stale_sources:StaleSource[]`、`contract_version:string`、`refreshed_at:datetime`。

- `GateSummary`：`code:string`、`name:string`、`status:enum[pending,passed,failed,blocked,stale,restricted]`、`source_type:string`、`source_id:int(nullable)`、`refreshed_at:datetime(nullable)`、`expires_at:datetime(nullable)`。
- `Finding`：`code:string`、`message:string`、`source_type:string`、`source_id:int(nullable)`。
- `EvidenceCounts`：固定含 `security_reviews/verification_runs/performance_runs/recovery_plans/release_plans`，均为非负整数。
- `StaleSource`：`source_type:string`、`source_id:int`、`expired_at:datetime`。

### 4.2 `SecurityReviewDetail`

`id:int`、`code:string`、`review_type:enum[platform_access,credential_custody,network_boundary,data_privacy,runner_security,finance_boundary]`、`environment:enum`、`scope_summary:string[1..1000]`、`risk_level:enum[low,medium,high,critical]`、`owner_id:int(readonly)`、`finance_scope:FinanceScope(nullable)`、`evidence_refs:string[]`、`expires_at:datetime`、`status:enum[draft,submitted,approved,rejected,expired]`、`creator_id:int`、`reviewer_id:int(nullable)`、`reviewed_at:datetime(nullable)`、`review_reason:string(nullable)`、`version:int`、`audit_ref:string`、`created_at:datetime`、`updated_at:datetime`。

- `FinanceScope`：`platforms:string[]`、`currencies:string[]`；只含编码，不含账户、流水、金额或凭据。

### 4.3 `VerificationRunDetail`

`id:int`、`code:string`、`category:enum[authentication,authorization,browser_e2e,backup_restore,failover,network_isolation,security_scan]`、`environment:enum`、`target_alias:string[2..64]`、`data_class:enum[demo,synthetic,masked]`、`planned_start_at:datetime`、`planned_end_at:datetime`、`success_criteria:string[1..500][1..20]`、`evidence_refs:string[]`、`status:enum[draft,submitted,approved,passed,failed,manual_required,cancelled]`、`result_summary:string[1..1000](nullable)`、`started_at:datetime(nullable)`、`finished_at:datetime(nullable)`、`error_code:string[1..80](nullable)`、`error_message:string[1..1000](nullable)`、`creator_id:int`、`reviewer_id:int(nullable)`、`recorder_id:int(nullable)`、`version:int`、`audit_ref:string`、`created_at:datetime`、`updated_at:datetime`。

### 4.4 `PerformanceRunDetail`

`id:int`、`code:string`、`scenario:string[1..200]`、`environment:enum`、`workload_profile:enum[demo,synthetic]`、`max_rps:int[1..500]`、`concurrency:int[1..100]`、`duration_seconds:int[1..3600]`、`thresholds:PerformanceThresholds`、`evidence_refs:string[]`、`status:enum[draft,submitted,approved,passed,failed,manual_required,cancelled]`、`p50_ms:decimal[0..3600000](nullable)`、`p95_ms:decimal[0..3600000](nullable)`、`error_rate:decimal[0..1](nullable)`、`cpu_percent:decimal[0..100](nullable)`、`memory_percent:decimal[0..100](nullable)`、`result_summary:string[1..1000](nullable)`、`creator_id:int`、`reviewer_id:int(nullable)`、`recorder_id:int(nullable)`、`version:int`、`audit_ref:string`、`created_at:datetime`、`updated_at:datetime`。

- `PerformanceThresholds` 精确含 `p95_ms_max:decimal>0`、`error_rate_max:decimal[0..1]`、`cpu_percent_max:decimal[0..100]`、`memory_percent_max:decimal[0..100]`，不允许未知 key。

### 4.5 `EntryDecisionDetail`

`id:int`、`code:string`、`environment:enum`、`decision:enum[go,no_go]`、`scope_summary:string[1..1000]`、`security_review_ids:int[]`、`verification_run_ids:int[]`、`performance_run_ids:int[]`、`recovery_plan_ids:int[]`、`release_plan_ids:int[]`、`expires_at:datetime`、`status:enum[draft,submitted,approved,rejected,expired]`、`evidence_snapshot:object(nullable)`、`evidence_hash:string(nullable)`、`blockers:Finding[]`、`warnings:Finding[]`、`contract_version:string(nullable)`、`creator_id:int`、`reviewer_id:int(nullable)`、`reviewed_at:datetime(nullable)`、`review_reason:string(nullable)`、`version:int`、`audit_ref:string`、`created_at:datetime`、`updated_at:datetime`。

`evidence_snapshot` 固定为：`captured_at:datetime`、`contract_version:string`、`sources:EvidenceSnapshotSource[]`。`EvidenceSnapshotSource` 固定含 `resource_type:enum[security_review,verification_run,performance_run,recovery_plan,release_plan]`、`resource_id:int`、`resource_version:int`、`status:string`、`evidence_digest:string`、`refreshed_at:datetime`、`expires_at:datetime(nullable)`；不允许未知字段。

### 4.6 列表摘要

- `SecurityReviewSummary`：`id/code/review_type/environment/risk_level/status/owner_id/expires_at/version/created_at/updated_at`。
- `VerificationRunSummary`：`id/code/category/environment/data_class/status/planned_start_at/planned_end_at/version/created_at/updated_at`。
- `PerformanceRunSummary`：`id/code/scenario/environment/workload_profile/status/max_rps/concurrency/version/created_at/updated_at`。
- `EntryDecisionSummary`：`id/code/environment/decision/status/expires_at/version/created_at/updated_at`。

列表不得返回 `evidence_snapshot`、完整 evidence 内容、内部地址或敏感来源字段。

## 5. 控制台端点

| 方法与路径 | permission | 请求 | 成功 data | 专属校验 |
|---|---|---|---|---|
| `GET /api/internal/pilot/control-room/` | `pilot.control.view` | query：`environment` 必填、`as_of:datetime` 可选 | `ControlRoom` | 强制来源缺失/过期或 finance gate restricted 时不得返回 `ready`；非法环境/日期 400 |

## 6. 安全评审端点

| 方法与路径 | permission | 请求 | 成功 | 状态 |
|---|---|---|---|---|
| `GET /api/internal/pilot/security-reviews/` | `pilot.security_review.view` | 公共列表 query | 200 分页 SecurityReviewSummary | 任意可见状态 |
| `POST /api/internal/pilot/security-reviews/` | `pilot.security_review.plan` | header 幂等键；body：`review_type/environment/scope_summary/risk_level/finance_scope/evidence_refs/expires_at` | 201 `SecurityReviewDetail` | 新建 `draft`；owner_id=actor |
| `GET /api/internal/pilot/security-reviews/{id}/` | `pilot.security_review.view` | 无 body | 200 `SecurityReviewDetail` | 任意可见状态 |
| `PATCH /api/internal/pilot/security-reviews/{id}/` | `pilot.security_review.plan` | body：`version` + 至少一个 `review_type/environment/scope_summary/risk_level/finance_scope/evidence_refs/expires_at` | 200 `SecurityReviewDetail` | 仅未过期 `draft` |
| `POST /api/internal/pilot/security-reviews/{id}/submit/` | `pilot.security_review.plan` | header 幂等键；body：`version/reason` | 200 `SecurityReviewDetail` | `draft -> submitted` |
| `POST /api/internal/pilot/security-reviews/{id}/approve/` | `pilot.security_review.review` | header 幂等键；body：`version/review_reason` | 200 `SecurityReviewDetail` | `submitted -> approved` |
| `POST /api/internal/pilot/security-reviews/{id}/reject/` | `pilot.security_review.review` | header 幂等键；body：`version/review_reason` | 200 `SecurityReviewDetail` | `submitted -> rejected` |

- `scope_summary` 为 1 至 1000 字符；evidence_refs 按公共类型校验。
- `expires_at` 必须晚于请求时刻，且不超过请求时刻后 180 天；PATCH 修改时执行同一规则，approve 时必须仍有效。
- 创建人不得 approve/reject 自己的评审。
- submit 后内容冻结；终态不可修改、删除或重复 action。

## 7. 受控验证端点

| 方法与路径 | permission | 请求 | 成功 | 状态 |
|---|---|---|---|---|
| `GET /api/internal/pilot/verification-runs/` | `pilot.verification.view` | 公共列表 query + `category/data_class` | 200 分页 VerificationRunSummary | 任意可见状态 |
| `POST /api/internal/pilot/verification-runs/` | `pilot.verification.plan` | header 幂等键；body：`category/environment/target_alias/data_class/planned_start_at/planned_end_at/success_criteria/evidence_refs` | 201 `VerificationRunDetail` | 新建 `draft` |
| `GET /api/internal/pilot/verification-runs/{id}/` | `pilot.verification.view` | 无 body | 200 `VerificationRunDetail` | 任意可见状态 |
| `PATCH /api/internal/pilot/verification-runs/{id}/` | `pilot.verification.plan` | body：`version` + 至少一个 `category/environment/target_alias/data_class/planned_start_at/planned_end_at/success_criteria/evidence_refs` | 200 `VerificationRunDetail` | 仅 `draft` |
| `POST /api/internal/pilot/verification-runs/{id}/submit/` | `pilot.verification.plan` | header 幂等键；body：`version/reason` | 200 `VerificationRunDetail` | `draft -> submitted` |
| `POST /api/internal/pilot/verification-runs/{id}/approve/` | `pilot.verification.review` | header 幂等键；body：`version/review_reason` | 200 `VerificationRunDetail` | `submitted -> approved` |
| `POST /api/internal/pilot/verification-runs/{id}/record-result/` | `pilot.verification.record` | header 幂等键；body：`version/reason/result/result_summary/evidence_refs/started_at/finished_at/error_code/error_message` | 200 `VerificationRunDetail` | `approved -> result` |
| `POST /api/internal/pilot/verification-runs/{id}/cancel/` | `pilot.verification.cancel` | header 幂等键；body：`version/cancel_reason` | 200 `VerificationRunDetail` | `draft/submitted/approved -> cancelled` |

- `target_alias` 必须匹配 `^[a-z][a-z0-9-]{1,63}$`，且为当前 tenant/environment 已登记受控别名；禁止 IP、主机名、URL 或连接串。
- `success_criteria` 为 1 至 20 个唯一字符串，每项 1 至 500 字符；结束时间必须晚于开始时间。
- `result` 仅 `passed/failed/manual_required`；`result_summary` 必填 1 至 1000 字符；`started_at/finished_at` 必填且 `finished_at >= started_at`。
- `error_code` nullable，非 null 时匹配 `^[A-Z][A-Z0-9_]{0,79}$`；`error_message` nullable，非 null 时 1 至 1000 字符。passed 时二者必须显式 null；failed/manual_required 时二者必须为非 null。
- API 不执行验证本身，不接受目标 URL、认证头、Cookie、Token 或命令。

## 8. 性能验证端点

| 方法与路径 | permission | 请求 | 成功 | 状态 |
|---|---|---|---|---|
| `GET /api/internal/pilot/performance-runs/` | `pilot.performance.view` | 公共列表 query + `workload_profile` | 200 分页 PerformanceRunSummary | 任意可见状态 |
| `POST /api/internal/pilot/performance-runs/` | `pilot.performance.plan` | header 幂等键；body：`scenario/environment/workload_profile/max_rps/concurrency/duration_seconds/thresholds/evidence_refs` | 201 `PerformanceRunDetail` | 新建 `draft` |
| `GET /api/internal/pilot/performance-runs/{id}/` | `pilot.performance.view` | 无 body | 200 `PerformanceRunDetail` | 任意可见状态 |
| `PATCH /api/internal/pilot/performance-runs/{id}/` | `pilot.performance.plan` | body：`version` + 至少一个 `scenario/environment/workload_profile/max_rps/concurrency/duration_seconds/thresholds/evidence_refs` | 200 `PerformanceRunDetail` | 仅 `draft` |
| `POST /api/internal/pilot/performance-runs/{id}/submit/` | `pilot.performance.plan` | header 幂等键；body：`version/reason` | 200 `PerformanceRunDetail` | `draft -> submitted` |
| `POST /api/internal/pilot/performance-runs/{id}/approve/` | `pilot.performance.review` | header 幂等键；body：`version/review_reason` | 200 `PerformanceRunDetail` | `submitted -> approved` |
| `POST /api/internal/pilot/performance-runs/{id}/record-result/` | `pilot.performance.record` | header 幂等键；body：`version/reason/result_mode/p50_ms/p95_ms/error_rate/cpu_percent/memory_percent/result_summary/evidence_refs` | 200 `PerformanceRunDetail` | `approved -> passed/failed/manual_required` |
| `POST /api/internal/pilot/performance-runs/{id}/cancel/` | `pilot.performance.cancel` | header 幂等键；body：`version/cancel_reason` | 200 `PerformanceRunDetail` | `draft/submitted/approved -> cancelled` |

- 计划字段固定为 `scenario/environment/workload_profile/max_rps/concurrency/duration_seconds/thresholds/evidence_refs`。
- `scenario` 必填 1 至 200 字符；evidence_refs 按公共类型校验。
- `result_mode` 仅 `measured/manual_required`；`result_summary` 必填 1 至 1000 字符。
- measured 要求 `p50_ms/p95_ms` 为 0 至 3600000 的 decimal，且 `p50_ms <= p95_ms`；`error_rate` 为 0 至 1；`cpu_percent/memory_percent` 为 0 至 100。五个指标均为 required 且非 null，后端按 thresholds 计算 passed/failed。
- manual_required 要求五个指标均为 required 且显式 null，并以 result_summary/evidence_refs 说明原因。请求不得提交最终 `result`，前端不得自行决定结果。
- API 不发起压力测试，不接受目标 URL、认证头、Cookie、Token 或执行命令。

## 9. 准入决策端点

| 方法与路径 | permission | 请求 | 成功 | 状态 |
|---|---|---|---|---|
| `GET /api/internal/pilot/entry-decisions/` | `pilot.entry.view` | 公共列表 query + `decision` | 200 分页 EntryDecisionSummary | 任意可见状态 |
| `POST /api/internal/pilot/entry-decisions/` | `pilot.entry.plan` | header 幂等键；body：`environment/decision/scope_summary/security_review_ids/verification_run_ids/performance_run_ids/recovery_plan_ids/release_plan_ids/expires_at` | 201 `EntryDecisionDetail` | 新建 `draft` |
| `GET /api/internal/pilot/entry-decisions/{id}/` | `pilot.entry.view` | 无 body | 200 `EntryDecisionDetail` | 任意可见状态 |
| `PATCH /api/internal/pilot/entry-decisions/{id}/` | `pilot.entry.plan` | body：`version` + 至少一个 `environment/decision/scope_summary/security_review_ids/verification_run_ids/performance_run_ids/recovery_plan_ids/release_plan_ids/expires_at` | 200 `EntryDecisionDetail` | 仅未过期 `draft` |
| `POST /api/internal/pilot/entry-decisions/{id}/submit/` | `pilot.entry.plan` | header 幂等键；body：`version/reason` | 200 `EntryDecisionDetail` | `draft -> submitted` |
| `POST /api/internal/pilot/entry-decisions/{id}/approve/` | `pilot.entry.review` | header 幂等键；body：`version/review_reason` | 200 `EntryDecisionDetail` | `submitted -> approved` |
| `POST /api/internal/pilot/entry-decisions/{id}/reject/` | `pilot.entry.review` | header 幂等键；body：`version/review_reason` | 200 `EntryDecisionDetail` | `submitted -> rejected` |

- 草稿字段固定为 `environment/decision/scope_summary/security_review_ids/verification_run_ids/performance_run_ids/recovery_plan_ids/release_plan_ids/expires_at`。
- 每类引用 1 至 100 个唯一正整数；必须通过第 3.4 节逐类授权。
- `scope_summary` 为 1 至 1000 字符；`expires_at` 必须晚于请求时刻，且不超过请求时刻后 30 天；PATCH 修改时执行同一规则。
- submit 时后端重新读取引用，生成不可变 `evidence_snapshot/evidence_hash/blockers/warnings/contract_version`；不得信任前端快照。
- `go` 必须满足所有强制评审有效、验证和性能结果通过、恢复/发布计划符合门禁、无 blocker 且证据未 stale。
- 创建人不得 approve/reject 自己的决策。批准只写准入结论，不执行部署、平台连接、流量切换或配置变更。

## 10. 公共列表合同

列表统一支持 `page/page_size/status/environment/created_from/created_to/ordering`。各模块可增加本合同明确登记的查询字段。

- `created_from/created_to` 为 UTC datetime，from 不得晚于 to。
- `ordering` 仅允许 `created_at/-created_at/updated_at/-updated_at/code/-code/status/-status`。
- 非法枚举、日期、页码、page_size 或 ordering 返回 400，不得静默返回空列表。

## 11. 状态机、过期、取消与职责分离

### 11.1 合法迁移矩阵

| 资源 | from | action | to | exact permission | actor 约束 |
|---|---|---|---|---|---|
| 安全评审 | draft | submit | submitted | `pilot.security_review.plan` | 创建人或同 scope 计划人 |
| 安全评审 | submitted | approve/reject | approved/rejected | `pilot.security_review.review` | 不得是创建人 |
| 安全评审 | draft/submitted/approved | expire | expired | system | 仅到期处理器 |
| 验证 | draft | submit | submitted | `pilot.verification.plan` | 创建人或同 scope 计划人 |
| 验证 | submitted | approve | approved | `pilot.verification.review` | 不得是创建人 |
| 验证 | approved | record-result | passed/failed/manual_required | `pilot.verification.record` | 不得是批准人 |
| 验证 | draft | cancel | cancelled | `pilot.verification.cancel` | 创建人或同 scope 取消人 |
| 验证 | submitted/approved | cancel | cancelled | `pilot.verification.cancel` | 不得是创建人 |
| 性能 | draft | submit | submitted | `pilot.performance.plan` | 创建人或同 scope 计划人 |
| 性能 | submitted | approve | approved | `pilot.performance.review` | 不得是创建人 |
| 性能 | approved | record-result | passed/failed | `pilot.performance.record` | 不得是批准人 |
| 性能 | draft | cancel | cancelled | `pilot.performance.cancel` | 创建人或同 scope 取消人 |
| 性能 | submitted/approved | cancel | cancelled | `pilot.performance.cancel` | 不得是创建人 |
| 准入决策 | draft | submit | submitted | `pilot.entry.plan` | 创建人或同 scope 计划人 |
| 准入决策 | submitted | approve/reject | approved/rejected | `pilot.entry.review` | 不得是创建人 |
| 准入决策 | draft/submitted/approved | expire | expired | system | 仅到期处理器 |

矩阵之外的迁移均返回 `409 STATE_CONFLICT`。终态不可修改、删除、恢复或重复 action；重新评审必须创建新资源。

### 11.2 过期规则

- 安全评审与准入决策以 `expires_at` 为唯一业务到期时间。
- 当 draft、submitted 或 approved 资源满足 `now >= expires_at`，定时任务必须以 system actor 执行 `expire`；详情、列表、控制台、PATCH、submit、approve/reject 和准入证据解析也必须先执行同一幂等惰性过期检查。
- draft 到期固定执行 `draft -> expired`，不得继续 PATCH 或 submit。GET/list/control-room 触发惰性过期后返回 200 并展示 expired/stale；PATCH/submit/approve/reject 等写动作触发过期后返回 `409 STATE_CONFLICT`。两类请求均先提交同一过期事务和审计。
- 过期处理使用行锁和版本递增，写 `from_status/to_status/expires_at/expired_at/actor_type=system/request_id/version` 审计。
- rejected 以及验证/性能终态不转 expired；过期的安全评审或准入结论不能被新决策复用。
- 到期检查与人工 action 并发时仅允许一个事务成功，另一方返回 409。

### 11.3 取消规则

- cancel 必须带 `cancel_reason`，取消后不可恢复。
- 所有取消固定使用专用 cancel permission；不得以 plan、review 或 record permission 代替。
- 创建人不得取消自己已 submitted/approved 的计划；批准人可以取消，但结果记录人不得与批准人相同。
- 已记录结果、已取消或其他终态重复取消返回 409。

### 11.4 防绕过

- status、reviewer、recorder、结果、快照、hash 和 audit 字段禁止通用 PATCH。
- 模型直接 save、QuerySet update/delete、bulk_update/bulk_create、admin action、级联删除和批量 API 不得绕过服务层状态机。
- 状态服务使用事务、行锁、version 和 Idempotency-Key；相同键同请求返回原结果，不同请求返回 409。

## 12. 证据与不可变审计

- evidence reference 必须属于当前 tenant 的受控证据注册表；跨 tenant、未知、失效或调用者无 view scope 的引用分别按 403/404 规则拒绝。
- 准入 snapshot 固定记录资源类型、ID、version、status、evidence digest、refreshed_at、expires_at 和 contract version；hash 使用服务端固定规范序列化后计算。
- 任一引用版本、状态、有效期或 digest 变化均使旧 snapshot stale；stale 结论不得返回 ready 或有效 go。
- 成功、失败、权限拒绝、data_scope 拒绝、422、幂等冲突、版本冲突、状态冲突、过期和取消均写不可变审计。
- 审计至少包含 `event_id/object_type/object_id/from_status/to_status/action/actor_id/actor_type/permission/reason/idempotency_key_hash/request_id/version/evidence_refs/occurred_at`。
- 审计及终态证据禁止 update/delete/bulk_update/bulk_create；关联 tenant、用户和资源使用 PROTECT 或脱敏保留语义。

## 13. 前端合同与当前状态

- 前端统一解析 `success/code/message/data` 和分页结构；非统一 HTTP 200 不包装为成功。
- 401、403、404、409、422 显示对应状态；无效详情 URL 显示可见 404。
- action 按状态对应的 exact permission 隐藏，后端拒绝仍是最终结果。
- 页面不得提供明文凭据、完整主机地址、执行命令、真实连接或生产发布按钮。
- `go` 仅显示为“准入结论”，不得显示为“已部署”或“生产已连接”。
- 全部 UI-P8 新端点保持 `pending`；开发、联调、测试和独立复审完成前不得标记 `connected` 或据此创建生产发布标签。
