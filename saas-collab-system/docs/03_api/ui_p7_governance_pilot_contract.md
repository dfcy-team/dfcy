# UI-P7 治理与受控试点 API 合同

## 1. 合同状态与证据规则

本合同冻结 UI-P7 的唯一页面/API口径。合同冻结时，仓库中不存在 UI-P7 后端端点、前端 API、页面或 Mock handler，因此所有新能力当前均为 `pending`。名称包含 `mock` 仅表示计划实现固定示例行为，不代表 Mock 已实现；在 handler、自动化测试和变更证据齐备前统一标记 `pending（planned mock）`。

状态变更必须满足：

| 目标状态 | 最小证据 |
|---|---|
| `mock` | 可执行的本地 Mock handler、固定 demo 数据、无网络/主机/业务写入测试、变更记录 |
| `sandbox` | 隔离环境、真实认证会话、权限/data_scope/错误/E2E证据 |
| `connected` | 本项目后端真实端点、真实认证会话、前后端联调、权限/data_scope/异常/审计验收及 CI 证据 |
| `degraded` | 已连接能力的依赖或证据部分失效，并明确影响范围 |
| `stale` | 证据超过该 gate/metric 的有效期，不得用于放行 |

路径存在、HTTP 200、页面可见、固定 JSON 文件或开发者说明均不能单独证明 `mock`、`sandbox` 或 `connected`。`connected` 不代表任何外部平台生产连接。

## 2. 通用请求、响应与分页

### 2.1 标量与字段规则

- `id`：正整数。
- 时间：带时区 ISO 8601，服务端存储和输出使用 UTC。
- `version`：从 1 开始的正整数，用于乐观锁。
- `reason`：去除首尾空白后 1 至 500 字符。
- `approval_ref`：可空字符串，非空时仅允许 `demo-` 或本系统不可变审批记录 ID；不得包含外部凭据。
- `evidence_refs`：最多 20 个内部脱敏引用，每项 1 至 200 字符；禁止 URL 查询密钥、完整主机地址、连接串、备份正文和文件内容。
- 未在端点表中列出的查询参数或请求字段返回 `400 UNKNOWN_FIELD`。
- 所有字符串拒绝控制字符；所有数组去重后校验，空字符串和非法枚举返回 `422 FIELD_VALIDATION_FAILED`。

### 2.2 成功与失败响应

对象成功响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

列表成功响应：

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

失败响应固定为 `success=false`、`data=null`。非统一 HTTP 200 响应视为 `INVALID_API_RESPONSE`，前端必须显示错误，不得包装为成功或标记 `connected`。

| HTTP | code | 精确语义 |
|---|---|---|
| 400 | `INVALID_REQUEST` / `UNKNOWN_FIELD` / `INVALID_PAGINATION` | JSON、未知字段/参数、页码或 page_size 非法 |
| 401 | `AUTH_REQUIRED` | 未认证、会话失效或 Token 无效 |
| 403 | `PERMISSION_DENIED` / `DATA_SCOPE_INVALID` / `DATA_SCOPE_FORBIDDEN` / `DATA_SCOPE_UNSUPPORTED` | user_type、exact permission、system scope 或 data_scope 不满足 |
| 404 | `RESOURCE_NOT_FOUND` | 资源不存在、跨 tenant 或详情资源不可见 |
| 409 | `VERSION_CONFLICT` / `STATE_CONFLICT` / `IDEMPOTENCY_CONFLICT` / `DUPLICATE_PLAN` | 版本、状态、幂等或重复计划冲突 |
| 422 | `FIELD_VALIDATION_FAILED` / `GATE_FAILED` / `APPROVAL_REQUIRED` / `SEPARATION_OF_DUTIES` / `POLICY_VIOLATION` | 字段、门禁、审批、职责分离、RPO/RTO、灰度或回滚规则失败 |

### 2.3 分页、header与写入规则

- 列表 `page` 默认 1，`page_size` 默认 20、最大 100；非正整数或超过上限返回 `400 INVALID_PAGINATION`，不得静默截断。
- 列表排序只接受端点明确列出的 `ordering` 值；未知值返回 400。
- 所有 POST 动作必须带 `Idempotency-Key` header，长度 16 至 128；同 key 不同请求返回 409。
- 创建端点不传 `version`；创建后返回 `version=1`。
- 针对既有对象的动作请求必须带 body `version` 和 `reason`。审批、排期、开始、恢复、取消、结果和回滚动作还必须按端点表提交字段。
- UI-P7 不提供 PUT、通用 PATCH、DELETE 或任意 `status` 更新端点。

## 3. 公共响应模型

下表字段均为响应必填；标记 nullable 的字段允许 `null`。

| 模型 | 字段 |
|---|---|
| `ApiContractSummary` | `id:int`、`module:string`、`name:string`、`path:string`、`method:enum[GET,POST]`、`owner:string`、`status:enum[pending,mock,sandbox,connected,degraded,disabled,stale]`、`version:string`、`permission:string`、`scope_keys:string[]`、`response_schema_version:string`、`evidence_status:enum[missing,valid,stale,failed]`、`updated_at:datetime` |
| `ApiContractDetail` | `ApiContractSummary`全部字段、`request_fields:RequestFieldSpec[]`、`response_fields:ResponseFieldSpec[]`、`error_codes:ApiErrorSpec[]`、`compatibility:enum[current,deprecated,pending]`、`deprecation_at:datetime(nullable)`、`change_history:ContractChangeEntry[]` |
| `AssistantSummary` | `id:int`、`code:string`、`name:string`、`status:enum[placeholder,review_pending,sandbox,disabled]`、`capability_declarations:string[]`、`data_classes:string[]`、`tool_allowlist:string[]`、`human_confirmation_required:true`、`updated_at:datetime` |
| `AssistantDetail` | `AssistantSummary`全部字段、`input_policy:string`、`output_policy:string`、`limitations:string[]`、`review_owner:string`、`reviewed_at:datetime(nullable)`；禁止 provider key、私有 prompt、Token、外部连接配置 |
| `ReadinessGate` | `gate_code:string`、`name:string`、`status:enum[not_started,in_progress,passed,failed,blocked,expired]`、`evidence_at:datetime(nullable)`、`expires_at:datetime(nullable)`、`blockers:string[]`、`owner:string`、`evidence_refs:string[]` |
| `TopologyService` | `service_name:string`、`host_role:enum[application,database]`、`network_zone:enum[controlled_app,controlled_db]`、`masked_endpoint:string`、`exposure:enum[loopback,app_host_only,controlled_lan,none]`、`health_status:enum[unknown,healthy,degraded,offline,stale]`、`checked_at:datetime(nullable)` |
| `RecoveryPlan` | `id:int`、`environment_id:string`、`name:string`、`rpo_minutes:int`、`rto_minutes:int`、`backup_summary:string`、`backup_checksum_masked:string`、`approval_ref:string(nullable)`、`status:RecoveryStatus`、`scheduled_at:datetime(nullable)`、`created_by_id:int`、`approved_by_id:int(nullable)`、`version:int`、`created_at:datetime`、`updated_at:datetime`、`audit_ref:string` |
| `RecoveryDrill` | `id:int`、`recovery_plan_id:int`、`status:enum[running,success,failed,manual_required,cancelled]`、`started_at:datetime(nullable)`、`finished_at:datetime(nullable)`、`actual_rpo_minutes:int(nullable)`、`actual_rto_minutes:int(nullable)`、`result_summary:string(nullable)`、`evidence_refs:string[]`、`version:int`、`audit_ref:string` |
| `ReleasePlan` | `id:int`、`environment_id:string`、`release_channel:enum[demo,controlled_pilot]`、`commit_sha:string`、`tag:string(nullable)`、`demo_tenant_refs:string[]`、`observation_minutes:int`、`stop_conditions:string[]`、`rollback_point:string`、`database_compatibility:enum[verified,not_required,failed,pending]`、`approval_ref:string(nullable)`、`rollback_approval_ref:string(nullable)`、`rollback_approved_by_id:int(nullable)`、`rollback_approved_at:datetime(nullable)`、`rollback_approval_expires_at:datetime(nullable)`、`status:ReleaseStatus`、`manual_context:enum[release,rollback](nullable)`、`scheduled_at:datetime(nullable)`、`created_by_id:int`、`approved_by_id:int(nullable)`、`version:int`、`created_at:datetime`、`updated_at:datetime`、`audit_ref:string` |
| `CapacityObservation` | `id:int`、`environment_id:string`、`service_name:string`、`metric_code:enum[cpu_percent,memory_percent,http_rps,queue_depth,db_connections]`、`value:number(nullable)`、`unit:string`、`threshold:number(nullable)`、`status:enum[normal,warning,critical,unknown,stale]`、`source:string`、`observed_at:datetime`、`expires_at:datetime`、`is_missing:boolean` |

`masked_endpoint` 只允许服务别名和网络区，例如 `mysql@controlled_db`；禁止完整 IP、端口、DNS、URL、连接串、用户名、代理地址或凭据指纹。

### 3.1 API合同详情嵌套item schema

下列 item 的全部字段均为必填；标记 nullable 的字段必须显式返回 `null`，数组无值时返回 `[]`，不得省略或以 null 代替。

| item schema | 字段 |
|---|---|
| `RequestFieldSpec` | `name:string[1..100]`、`location:enum[path,query,header,body]`、`type:enum[string,integer,number,boolean,datetime,object,array]`、`required:boolean`、`nullable:boolean`、`enum_values:string[]`、`item_type:enum[string,integer,number,boolean,datetime,object](nullable)`、`schema_ref:string(nullable)`、`min_length:int(nullable)`、`max_length:int(nullable)`、`minimum:number(nullable)`、`maximum:number(nullable)`、`pattern:string(nullable)`、`description:string[1..500]` |
| `ResponseFieldSpec` | `field_path:string[1..200]`、`type:enum[string,integer,number,boolean,datetime,object,array]`、`required:boolean`、`nullable:boolean`、`enum_values:string[]`、`item_type:enum[string,integer,number,boolean,datetime,object](nullable)`、`schema_ref:string(nullable)`、`description:string[1..500]` |
| `ApiErrorSpec` | `http_status:enum[400,401,403,404,409,422]`、`code:string[1..100]`、`condition:string[1..500]`、`field:string(nullable)`、`retryable:boolean` |
| `ContractChangeEntry` | `version:string[1..40]`、`change_type:enum[added,changed,deprecated,removed]`、`summary:string[1..500]`、`changed_at:datetime`、`owner:string[1..120]`、`deprecation_at:datetime(nullable)` |

- item schema 字段自身的必填与空值规则如下；表内未列字段一律拒绝并返回 `422 SCHEMA_FIELD_UNKNOWN`。

| item schema | 字段 | 类型 | required | nullable | 约束与语义 |
|---|---|---|---|---|---|
| RequestFieldSpec | name | string | 是 | 否 | 1..100；当前请求结构内唯一字段名 |
| RequestFieldSpec | location | enum | 是 | 否 | path/query/header/body |
| RequestFieldSpec | type | enum | 是 | 否 | string/integer/number/boolean/datetime/object/array |
| RequestFieldSpec | required | boolean | 是 | 否 | 描述目标 API 字段是否必填 |
| RequestFieldSpec | nullable | boolean | 是 | 否 | 描述目标 API 字段是否允许 null |
| RequestFieldSpec | enum_values | string[] | 是 | 否 | 无枚举时必须为 `[]` |
| RequestFieldSpec | item_type | enum | 是 | 是 | type=array 时必填且非 null；其余类型为 null |
| RequestFieldSpec | schema_ref | string | 是 | 是 | type=object 或 array item_type=object 时必填且非 null；其余类型为 null |
| RequestFieldSpec | min_length | integer | 是 | 是 | 仅 string；0..10000，不适用为 null |
| RequestFieldSpec | max_length | integer | 是 | 是 | 仅 string；必须大于等于 min_length，不适用为 null |
| RequestFieldSpec | minimum | number | 是 | 是 | 仅 integer/number；不适用为 null |
| RequestFieldSpec | maximum | number | 是 | 是 | 仅 integer/number；必须大于等于 minimum，不适用为 null |
| RequestFieldSpec | pattern | string | 是 | 是 | 仅 string；正则最长 500，不适用为 null |
| RequestFieldSpec | description | string | 是 | 否 | 1..500；说明用途、单位或格式 |
| ResponseFieldSpec | field_path | string | 是 | 否 | 1..200；当前响应结构内唯一，嵌套使用点号路径 |
| ResponseFieldSpec | type | enum | 是 | 否 | string/integer/number/boolean/datetime/object/array |
| ResponseFieldSpec | required | boolean | 是 | 否 | 描述目标响应字段是否保证返回 |
| ResponseFieldSpec | nullable | boolean | 是 | 否 | 描述目标响应字段是否允许 null |
| ResponseFieldSpec | enum_values | string[] | 是 | 否 | 无枚举时必须为 `[]` |
| ResponseFieldSpec | item_type | enum | 是 | 是 | type=array 时必填且非 null；其余类型为 null |
| ResponseFieldSpec | schema_ref | string | 是 | 是 | type=object 或 array item_type=object 时必填且非 null；其余类型为 null |
| ResponseFieldSpec | description | string | 是 | 否 | 1..500；说明用途、单位或脱敏语义 |
| ApiErrorSpec | http_status | enum | 是 | 否 | 400/401/403/404/409/422 |
| ApiErrorSpec | code | string | 是 | 否 | 1..100；同一 http_status 下唯一 |
| ApiErrorSpec | condition | string | 是 | 否 | 1..500；可直接转换为测试前置条件 |
| ApiErrorSpec | field | string | 是 | 是 | 字段级错误填写字段路径；非字段错误为 null |
| ApiErrorSpec | retryable | boolean | 是 | 否 | 是否允许在请求不变时重试 |
| ContractChangeEntry | version | string | 是 | 否 | 1..40；合同版本 |
| ContractChangeEntry | change_type | enum | 是 | 否 | added/changed/deprecated/removed |
| ContractChangeEntry | summary | string | 是 | 否 | 1..500；变更摘要 |
| ContractChangeEntry | changed_at | datetime | 是 | 否 | UTC |
| ContractChangeEntry | owner | string | 是 | 否 | 1..120；责任角色或团队，不记录个人凭据 |
| ContractChangeEntry | deprecation_at | datetime | 是 | 是 | deprecated 时必填且晚于 changed_at；其他类型为 null |

- `RequestFieldSpec` 排序固定为 location `path/query/header/body`，同 location 按 name 升序。
- `ResponseFieldSpec` 按 field_path 升序；嵌套字段使用点号路径，例如 `data.results[].id`。
- `ApiErrorSpec` 按 http_status、code 升序；同一 http/code 只允许一个现行condition。
- `ContractChangeEntry` 按 changed_at 降序、version 降序。
- `type=array` 时 item_type 必填；`type=object` 时 schema_ref 必填；其他类型的 item_type/schema_ref 必须为 null。
- enum_values 无枚举时返回 `[]`；min/max/pattern 不适用时返回 null。未知 item 字段或违反上述组合规则返回 422。

## 4. API治理与智能体占位

| 用途 | 方法与路径 | exact permission | 查询或请求体 | data | 当前状态 |
|---|---|---|---|---|---|
| 合同目录 | `GET /api/internal/governance/api-contracts/` | `governance.api.view` | 查询：`page:int`、`page_size:int`、`module:string`、`status:ApiStatus`、`version:string`、`ordering:enum[module,-updated_at]` | 分页 `ApiContractSummary[]` | pending |
| 合同详情 | `GET /api/internal/governance/api-contracts/{id}/` | `governance.api.view` | 路径：`id:int` | `ApiContractDetail` | pending |
| Mock一致性检查 | `POST /api/internal/governance/api-contracts/check-mock/` | `governance.api.check` | body：`contract_ids:int[1..50]`、`sample_case:enum[success,pagination,400,401,403,404,409,422]` | `checked_count:int`、`passed_count:int`、`violations:{contract_id:int,field:string,code:string}[]`、`evidence_status:"fixed_demo"` | pending（planned mock） |
| 占位目录 | `GET /api/internal/governance/assistants/` | `governance.assistants.view` | 查询：`page`、`page_size`、`status:AssistantStatus`、`data_class:string`、`ordering:enum[code,-updated_at]` | 分页 `AssistantSummary[]` | pending |
| 占位详情 | `GET /api/internal/governance/assistants/{id}/` | `governance.assistants.view` | 路径：`id:int` | `AssistantDetail` | pending |
| Mock评估 | `POST /api/internal/governance/assistants/{id}/evaluate-mock/` | `governance.assistants.evaluate` | body：`scenario:enum[catalog_review,readiness_summary,risk_summary]`、`demo_input_ref:string`（必须以 `demo-` 开头）、`version:int`、`reason:string` | `assistant_id:int`、`recommendation:string`、`limitations:string[]`、`confidence:number[0..1]`、`human_confirmation_required:true`、`tool_calls:[]`、`business_writes:[]` | pending（planned mock） |

`ApiStatus` 为 `pending/mock/sandbox/connected/degraded/disabled/stale`；`AssistantStatus` 为 `placeholder/review_pending/sandbox/disabled`。Mock输出不得调用工具、写业务数据或触发 RPA。

## 5. 试点就绪、拓扑与容量

| 用途 | 方法与路径 | exact permission | 查询或请求体 | data | 当前状态 |
|---|---|---|---|---|---|
| 就绪总览 | `GET /api/internal/pilot/readiness/` | `pilot.readiness.view` | 查询：`environment_id:string`、`gate_code:string`、`status:GateStatus` | `environment_id:string`、`overall_status:GateStatus`、`evaluated_at:datetime`、`gates:ReadinessGate[]` | pending |
| 脱敏拓扑 | `GET /api/internal/pilot/topology/` | `pilot.topology.view` | 查询：`environment_id:string`、`service_name:string` | `environment_id:string`、`generated_at:datetime`、`services:TopologyService[]` | pending |
| Mock拓扑检查 | `POST /api/internal/pilot/topology/verify-mock/` | `pilot.topology.verify` | body：`environment_id:string`、`services:{service_name:string,host_role:HostRole,network_zone:NetworkZone,exposure:Exposure}[]`、`reason:string` | `valid:boolean`、`violations:{service_name:string,code:string,message:string}[]`、`checked_at:datetime`、`evidence_status:"fixed_demo"` | pending（planned mock） |
| 容量摘要 | `GET /api/internal/pilot/capacity/summary/` | `pilot.capacity.view` | 查询：`environment_id:string`、`window_minutes:enum[5,15,60,1440]` | `environment_id:string`、`window_minutes:int`、`generated_at:datetime`、`quality_status:enum[valid,partial,missing,stale]`、`metrics:CapacityObservation[]` | pending |
| 观测列表 | `GET /api/internal/pilot/capacity/observations/` | `pilot.capacity.view` | 查询：`page`、`page_size`、`environment_id`、`service_name`、`metric_code`、`status`、`observed_from:datetime`、`observed_to:datetime`、`ordering:enum[observed_at,-observed_at]` | 分页 `CapacityObservation[]` | pending |

就绪门禁状态为 `not_started/in_progress/passed/failed/blocked/expired`。证据时间统一 UTC；缺少 TTL 或超过 `expires_at` 时状态必须为 `expired/stale`，不得用于放行。缺失容量值返回 `value=null`、`is_missing=true`，不得补零或由前端跨环境聚合。

| 证据类型 | 默认TTL | 过期语义 |
|---|---|---|
| code/CI/security/config gate | 24小时 | gate=`expired`，overall不得passed |
| database/network/backup/recovery/rollback gate | 8小时 | gate=`expired`，阻断排期或开始 |
| capacity 5/15分钟窗口 | 15分钟 | metric=`stale` |
| capacity 60分钟窗口 | 2小时 | metric=`stale` |
| capacity 1440分钟窗口 | 26小时 | metric=`stale` |

## 6. 备份恢复端点

| 用途 | 方法与路径 | exact permission | 查询或请求体 | data | 当前状态 |
|---|---|---|---|---|---|
| 计划列表 | `GET /api/internal/pilot/recovery-plans/` | `pilot.recovery.view` | 查询：`page`、`page_size`、`environment_id`、`status:RecoveryStatus`、`ordering:enum[created_at,-created_at,scheduled_at]` | 分页 `RecoveryPlan[]` | pending |
| 创建计划 | `POST /api/internal/pilot/recovery-plans/` | `pilot.recovery.plan` | body：`environment_id:string`、`name:string[1..120]`、`rpo_minutes:int[1..10080]`、`rto_minutes:int[1..10080]`、`backup_summary:string[1..500]`、`backup_checksum_masked:string[1..128]`、`reason:string`；header：`Idempotency-Key` | `RecoveryPlan(status=draft,version=1)` | pending |
| 计划详情 | `GET /api/internal/pilot/recovery-plans/{id}/` | `pilot.recovery.view` | 路径：`id:int` | `RecoveryPlan` | pending |
| 提交审批 | `POST /api/internal/pilot/recovery-plans/{id}/submit-review/` | `pilot.recovery.plan` | body：`version:int`、`reason:string`、`approval_ref:string` | `RecoveryPlan(status=review_pending)` | pending |
| 批准 | `POST /api/internal/pilot/recovery-plans/{id}/approve/` | `pilot.recovery.review` | body：`version:int`、`reason:string`、`approval_ref:string` | `RecoveryPlan(status=approved)` | pending |
| 拒绝 | `POST /api/internal/pilot/recovery-plans/{id}/reject/` | `pilot.recovery.review` | body：`version:int`、`reason:string` | `RecoveryPlan(status=rejected)` | pending |
| 排期 | `POST /api/internal/pilot/recovery-plans/{id}/schedule/` | `pilot.recovery.plan` | body：`version:int`、`reason:string`、`scheduled_at:datetime` | `RecoveryPlan(status=scheduled)` | pending |
| 开始演练记录 | `POST /api/internal/pilot/recovery-plans/{id}/start/` | `pilot.recovery.record` | body：`version:int`、`reason:string` | `RecoveryPlan(status=running)`、`drill:RecoveryDrill(status=running)` | pending |
| 恢复人工演练 | `POST /api/internal/pilot/recovery-plans/{id}/resume/` | `pilot.recovery.record` | body：`version:int`、`reason:string`、`manual_resolution_ref:string` | `RecoveryPlan(status=running)`、`drill:RecoveryDrill(status=running)` | pending |
| 取消 | `POST /api/internal/pilot/recovery-plans/{id}/cancel/` | `pilot.recovery.plan` | body：`version:int`、`reason:string` | `RecoveryPlan(status=cancelled)` | pending |
| 演练记录列表 | `GET /api/internal/pilot/recovery-drills/` | `pilot.recovery.view` | 查询：`page`、`page_size`、`environment_id`、`recovery_plan_id:int`、`status`、`ordering:enum[started_at,-started_at]` | 分页 `RecoveryDrill[]` | pending |
| 记录演练结果 | `POST /api/internal/pilot/recovery-drills/{id}/record-result/` | `pilot.recovery.record` | body：`version:int`、`reason:string`、`result_status:enum[success,failed,manual_required]`、`actual_rpo_minutes:int(nullable)`、`actual_rto_minutes:int(nullable)`、`result_summary:string[1..1000]`、`evidence_refs:string[]` | `RecoveryDrill(status=result_status)`、对应 `RecoveryPlan(status=result_status)` | pending |

不得在请求体中提交备份正文、恢复脚本、文件系统路径、数据库连接串、密码、私钥或主机命令；出现这些字段返回 `422 POLICY_VIOLATION` 且不得写入。

## 7. 灰度发布与回滚端点

| 用途 | 方法与路径 | exact permission | 查询或请求体 | data | 当前状态 |
|---|---|---|---|---|---|
| 计划列表 | `GET /api/internal/pilot/release-plans/` | `pilot.release.view` | 查询：`page`、`page_size`、`environment_id`、`release_channel`、`status:ReleaseStatus`、`ordering:enum[created_at,-created_at,scheduled_at]` | 分页 `ReleasePlan[]` | pending |
| 创建计划 | `POST /api/internal/pilot/release-plans/` | `pilot.release.plan` | body：`environment_id:string`、`release_channel:enum[demo,controlled_pilot]`、`commit_sha:string[40-or-64-hex]`、`tag:string(nullable)`、`demo_tenant_refs:string[1..20]`、`observation_minutes:int[15..1440]`、`stop_conditions:string[1..20]`、`rollback_point:string[1..200]`、`database_compatibility:enum[verified,not_required,pending]`、`reason:string` | `ReleasePlan(status=draft,version=1)` | pending |
| 计划详情 | `GET /api/internal/pilot/release-plans/{id}/` | `pilot.release.view` | 路径：`id:int` | `ReleasePlan` | pending |
| 提交审批 | `POST /api/internal/pilot/release-plans/{id}/submit-review/` | `pilot.release.plan` | body：`version:int`、`reason:string`、`approval_ref:string` | `ReleasePlan(status=review_pending)` | pending |
| 批准 | `POST /api/internal/pilot/release-plans/{id}/approve/` | `pilot.release.review` | body：`version:int`、`reason:string`、`approval_ref:string` | `ReleasePlan(status=approved)` | pending |
| 拒绝 | `POST /api/internal/pilot/release-plans/{id}/reject/` | `pilot.release.review` | body：`version:int`、`reason:string` | `ReleasePlan(status=rejected)` | pending |
| 排期 | `POST /api/internal/pilot/release-plans/{id}/schedule/` | `pilot.release.plan` | body：`version:int`、`reason:string`、`scheduled_at:datetime` | `ReleasePlan(status=scheduled)` | pending |
| 开始结果记录 | `POST /api/internal/pilot/release-plans/{id}/start/` | `pilot.release.record` | body：`version:int`、`reason:string` | `ReleasePlan(status=running)` | pending |
| 恢复发布人工处理 | `POST /api/internal/pilot/release-plans/{id}/resume/` | `pilot.release.record` | body：`version:int`、`reason:string`、`manual_resolution_ref:string` | 仅 `manual_context=release`；返回 `ReleasePlan(status=running)` | pending |
| 取消 | `POST /api/internal/pilot/release-plans/{id}/cancel/` | `pilot.release.plan` | body：`version:int`、`reason:string` | `ReleasePlan(status=cancelled)` | pending |
| 记录发布结果 | `POST /api/internal/pilot/release-plans/{id}/record-result/` | `pilot.release.record` | body：`version:int`、`reason:string`、`result_status:enum[success,failed,rollback_required,manual_required]`、`result_summary:string[1..1000]`、`evidence_refs:string[]` | `ReleasePlan(status=result_status)` | pending |
| 批准回滚 | `POST /api/internal/pilot/release-plans/{id}/approve-rollback/` | `pilot.release.rollback` | body：`version:int`、`reason:string`、`rollback_approval_ref:string`、`approval_expires_at:datetime`（UTC，晚于当前时间且不超过24小时） | 状态保持 rollback_required；记录 `rollback_approval_ref/rollback_approved_by_id/rollback_approved_at/rollback_approval_expires_at` 并递增version | pending |
| 恢复回滚人工处理 | `POST /api/internal/pilot/release-plans/{id}/resume-rollback/` | `pilot.release.rollback` | body：`version:int`、`reason:string`、`manual_resolution_ref:string`、`rollback_approval_ref:string` | 仅 `manual_context=rollback`；返回 `ReleasePlan(status=rollback_required)` | pending |
| 记录回滚结果 | `POST /api/internal/pilot/release-plans/{id}/record-rollback/` | `pilot.release.rollback` | body：`version:int`、`reason:string`、`rollback_approval_ref:string`、`rollback_status:enum[rolled_back,failed,manual_required]`、`result_summary:string[1..1000]`、`evidence_refs:string[]` | `ReleasePlan(status=rollback_status)` | pending |

不得提交部署脚本、Git命令、数据库命令、密钥、真实平台配置或高风险业务动作；端点只记录已在受控主机外部执行的结果。

## 8. 恢复与发布合法状态机

### 8.1 状态枚举

- `RecoveryStatus`：`draft/review_pending/approved/rejected/scheduled/running/success/failed/manual_required/cancelled`。
- `ReleaseStatus`：`draft/review_pending/approved/rejected/scheduled/running/success/failed/rollback_required/rolled_back/manual_required/cancelled`。

### 8.2 恢复计划迁移矩阵

| 动作 | from | to | exact permission | 前置条件 |
|---|---|---|---|---|
| `submit-review` | draft | review_pending | `pilot.recovery.plan` | RPO/RTO、备份摘要、校验摘要完整；提交人是创建人或计划负责人 |
| `approve` | review_pending | approved | `pilot.recovery.review` | 审批人与创建人不同；approval_ref有效；版本一致 |
| `reject` | review_pending | rejected | `pilot.recovery.review` | 审批人与创建人不同；拒绝原因非空 |
| `schedule` | approved | scheduled | `pilot.recovery.plan` | scheduled_at为未来时间；批准未过期 |
| `start` | scheduled | running | `pilot.recovery.record` | 当前时间进入允许窗口；创建唯一运行中的 drill |
| `record-result(success)` | running | success | `pilot.recovery.record` | 结果、RPO/RTO和脱敏证据完整 |
| `record-result(failed)` | running | failed | `pilot.recovery.record` | 失败原因和证据完整 |
| `record-result(manual_required)` | running | manual_required | `pilot.recovery.record` | 人工原因和最后成功步骤完整 |
| `resume` | manual_required | running | `pilot.recovery.record` | manual_resolution_ref有效；不存在其他运行实例 |
| `cancel` | draft/review_pending/approved/scheduled/manual_required | cancelled | `pilot.recovery.plan` | 原因非空；running 状态不得取消，必须先记录失败或人工接管 |

`rejected/success/failed/cancelled` 为终态，不允许恢复或修改；需重新创建新计划。

### 8.3 发布计划迁移矩阵

| 动作 | from | to | exact permission | 前置条件 |
|---|---|---|---|---|
| `submit-review` | draft | review_pending | `pilot.release.plan` | commit/tag、demo tenant、观察窗口、停止条件、回滚点完整 |
| `approve` | review_pending | approved | `pilot.release.review` | 审批人与创建人不同；全部 readiness gate 有效；数据库兼容性非 failed/pending |
| `reject` | review_pending | rejected | `pilot.release.review` | 审批人与创建人不同；拒绝原因非空 |
| `schedule` | approved | scheduled | `pilot.release.plan` | scheduled_at为未来时间；批准与门禁未过期 |
| `start` | scheduled | running | `pilot.release.record` | 进入窗口；commit/tag未变化；只记录外部执行开始 |
| `record-result(success)` | running | success | `pilot.release.record` | 观察窗口完成且停止条件未触发 |
| `record-result(failed)` | running | failed | `pilot.release.record` | 失败原因与证据完整，且不需要回滚 |
| `record-result(rollback_required)` | running | rollback_required | `pilot.release.record` | 停止条件触发或验证失败；回滚点有效；清空旧rollback approval字段 |
| `record-result(manual_required)` | running | manual_required | `pilot.release.record` | 人工原因与证据完整；写入 manual_context=release |
| `resume` | manual_required且manual_context=release | running | `pilot.release.record` | manual_resolution_ref有效；门禁仍有效；清空manual_context |
| `approve-rollback` | rollback_required | rollback_required | `pilot.release.rollback` | rollback_approval_ref唯一且 approval_expires_at 合法；批准人不是创建人或发布审批人；记录独立批准审计；重新批准替换旧批准并使旧ref失效 |
| `record-rollback(rolled_back)` | rollback_required | rolled_back | `pilot.release.rollback` | rollback_approval_ref与计划一致且未失效；记录人不是回滚批准人；结果与脱敏证据完整 |
| `record-rollback(failed)` | rollback_required | failed | `pilot.release.rollback` | rollback_approval_ref与计划一致且未失效；记录人不是回滚批准人；失败原因完整 |
| `record-rollback(manual_required)` | rollback_required | manual_required | `pilot.release.rollback` | rollback approval有效；记录人不是回滚批准人；写入 manual_context=rollback |
| `resume-rollback` | manual_required且manual_context=rollback | rollback_required | `pilot.release.rollback` | manual_resolution_ref有效；rollback_approval_ref匹配且未失效；清空manual_context |
| `cancel` | draft/review_pending/approved/scheduled，或manual_required且manual_context=release | cancelled | `pilot.release.plan` | 原因非空；running/rollback_required及回滚人工接管不得直接取消 |

`rejected/success/failed/rolled_back/cancelled` 为终态。审批通过只允许进入受控计划，不授权真实平台或高风险业务动作。

### 8.4 防绕过与不可变审计

- 状态字段在所有创建/详情 serializer 中只读；不存在集合或详情通用状态 PATCH。
- 只有上述专用动作端点可调用状态迁移服务。服务必须在事务和行锁内校验 tenant/system scope、exact permission、data_scope、当前状态、版本、幂等 key、职责分离和前置门禁。
- 直接 `model.save(update_fields=["status"])`、QuerySet `update(status=...)`、admin修改状态、信号或批处理绕过服务均必须被模型/manager保护或 CI 静态检查拒绝。
- 审批人不得是创建人；记录执行结果的人员不得修改原审批结论。
- 回滚必须经过独立 `approve-rollback`；原发布审批不自动授权回滚。回滚批准人不得是计划创建人、发布审批人或回滚结果记录人。
- 回滚批准仅在同一 release plan、`status=rollback_required`、ref完全匹配且当前时间早于 `rollback_approval_expires_at` 时有效。离开 rollback_required、重新批准、commit/tag/rollback_point 变化或重新进入 rollback_required 均使旧批准立即失效；过期返回 `422 ROLLBACK_APPROVAL_EXPIRED`，ref不匹配返回 `422 ROLLBACK_APPROVAL_INVALID`。批准、替换、过期拒绝及结果记录均写不可变审计。
- `resume` 只处理 `manual_context=release` 并使用 record 权限；`resume-rollback` 只处理 `manual_context=rollback` 并使用 rollback 权限，两者不得互为别名或共享权限判断。
- 非法 from/to 返回 `409 STATE_CONFLICT`；缺失/失效审批或门禁返回 422；版本冲突返回 409；越权对象返回 404。
- 每次成功或失败动作均写不可变审计：`event_id/object_type/object_id/from_status/to_status/action/actor_id/permission/reason/approval_ref/rollback_approval_ref/idempotency_key_hash/request_id/version/evidence_refs/occurred_at`。
- 审计实例禁止更新和删除；QuerySet update/delete、bulk_update、级联删除和后台删除均必须拒绝。关联 tenant、用户、计划采用 PROTECT 或脱敏保留策略。

## 9. 权限和permission-specific data_scope

- 所有 UI-P7 端点拒绝 external 和 RPA 用户。
- `governance.*` 与 `pilot.*` 不由其他模块权限、登录状态或 superuser UI 文案隐式替代。
- system scope 不得包含 tenant 业务明细；tenant 相关证据只返回脱敏 tenant 引用并按 data_scope 过滤。
- 审计查询复用 `/api/internal/audit/operation-logs/`，UI-P7 不新增审计修改或删除端点。

| Permission | 允许的 CUSTOM scope key |
|---|---|
| `governance.api.view/check` | `modules`、`api_contract_ids`、`statuses` |
| `governance.assistants.view/evaluate` | `assistant_ids`、`data_classes` |
| `pilot.readiness.view` | `environment_ids`、`gate_codes` |
| `pilot.topology.view/verify` | `environment_ids`、`service_names`、`network_zones` |
| `pilot.recovery.view/plan/review/record` | `environment_ids`、`recovery_plan_ids` |
| `pilot.release.view/plan/review/record/rollback` | `environment_ids`、`release_plan_ids`、`release_channels` |
| `pilot.capacity.view` | `environment_ids`、`service_names`、`metric_codes` |

- `modules`：非空模块编码数组，仅接受治理目录已登记编码；`api_contract_ids/assistant_ids/recovery_plan_ids/release_plan_ids`：1至100个正整数。
- `statuses`：对应端点冻结的状态枚举数组；`data_classes`：仅 `public_demo/internal_demo/restricted_demo`。
- `environment_ids`：1至20个已登记环境编码，格式 `^[a-z0-9][a-z0-9-]{1,63}$`；未登记编码返回 `DATA_SCOPE_INVALID`。
- `gate_codes`：仅 `code/ci/security/config/database/network/backup/recovery/rollback/capacity`。
- `service_names`：仅 `nginx/backend/celery_worker/celery_beat/redis/mysql`；`network_zones`：仅 `controlled_app/controlled_db`。
- `release_channels`：仅 `demo/controlled_pilot`；`metric_codes`：仅 `cpu_percent/memory_percent/http_rps/queue_depth/db_connections`。
- 每个端点只读取当前 exact permission 的 scope，不使用跨 permission 的合并 scope。
- `ALL` 仅放行该 permission 在受控试点环境中的可见集合，不放行其他 tenant 数据或未登记主机资源。
- 无 scope、空 scope、未知 key、空字符串、非法 ID/枚举返回 `403 DATA_SCOPE_INVALID`；未冻结归属的 `OWN/DEPARTMENT` 返回 `403 DATA_SCOPE_UNSUPPORTED`。
- 多条 CUSTOM scope 按 OR；同一条记录中的不同 key 按 AND。
- 合法但超 scope 的列表筛选返回 200 空分页；详情按 ID 越权返回 404；请求体包含超 scope 值返回 403 且不写入。
- `review`、`record`、`rollback` 必须各自重新计算 scope，不继承 `view/plan` scope。

## 10. 禁止路径、字段与动作

- 前端不得调用 `/api/rpa/*` Agent执行接口、`/admin/`、Docker socket、数据库管理端口或 shell 接口。
- 不创建 `/deploy/`、`/backup/`、`/restore/`、`/rollback/` 形式的直接执行 Web 端点。
- 请求和响应禁止 `password/secret/token/cookie/session/api_key/api_secret/private_key/connection_string/proxy_url/backup_content/script/command/raw_log` 等字段。
- 不接入真实 AI provider、BigSeller、Shopee、TikTok/TK、银行或支付系统。
- 不让治理、试点、容量或智能体页面触发采购、库存修改、刊登、改价、清仓、上下架、RPA、付款、转账或提现。
