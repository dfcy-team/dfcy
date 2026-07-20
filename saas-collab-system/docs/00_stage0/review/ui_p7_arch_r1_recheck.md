# UI-P7-ARCH-R1 独立实现复审报告

## 1. 复审对象

- 项目根目录：`saas-collab-system/`
- 审核分支：`feature/ui-p7-governance-pilot-readiness`
- 对比基线：`origin/main@17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`
- 审核对象：UI-P7 治理、受控试点、权限、data_scope、双状态机、Mock/dry-run、页面及测试成果。
- 审核性质：只审核，不修复；本次仅新增本报告。
- 审核日期：2026-07-17。

## 2. 复审依据

- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/00_stage0/review/ui_p7_implementation_report.md`
- `docs/00_stage0/review/ui_p7_test_result.md`
- `backend/apps/governance/`
- `backend/apps/pilot/`
- `backend/apps/permissions/ui_p7_scopes.py`
- `backend/tests/test_ui_p7_governance_pilot.py`
- `frontend/src/api/governance.js`、`frontend/src/api/pilot.js`
- `frontend/src/mock/governance.js`、`frontend/src/mock/pilot.js`
- `frontend/src/views/governance/`、`frontend/src/views/pilot/`
- `frontend/tests/ui-p7-governance-pilot.spec.js`

## 3. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：5 项，尚未关闭。
- P2：2 项，不单独阻断，但应纳入收尾观察。
- 37 个冻结 `method + path` 组合均有唯一 URL/handler 入口；实现使用 35 条 Django URL pattern，其中恢复计划和发布计划集合路径各承载 `GET` 与 `POST`。
- 未发现真实平台连接、真实密钥、真实 RPA、资金动作或直接基础设施执行端点。
- 当前不得正式收尾、不得标记 `connected`、不得进入真实试点发布；应完成整改并执行 `UI-P7-ARCH-R2`。

## 4. 端点、请求与响应合同

### 已通过

- 冻结端点无同义重复路径，未提供通用 PUT/PATCH/DELETE 状态接口。
- POST handler 均要求 `Idempotency-Key`，请求 serializer 使用未知字段拒绝策略。
- 列表统一使用 `success/code/message/data` 与 `count/next/previous/results` 分页外壳。

### 未通过

- 公共响应模型未按冻结字段实现。`ApiContractSummarySerializer` 返回 `permission_code/data_scope_keys/tenant_ref`，但合同要求 `permission/scope_keys/response_schema_version/evidence_status`；助手、ReadinessGate、TopologyService、CapacityObservation 也存在缺字段或字段名、枚举不一致。
- 拓扑实现和 Mock 使用 `exposure=private`、`host_ref_masked/port_hint/verified_at`，冻结合同要求 `loopback/app_host_only/controlled_lan/none` 与 `masked_endpoint/health_status/checked_at`。
- 容量实现和 Mock 使用 `warning_threshold/critical_threshold` 与 `status=valid/partial/missing/stale`，冻结 `CapacityObservation` 要求 `threshold/expires_at` 与 `normal/warning/critical/unknown/stale`。
- 普通 DRF `ValidationError` 仍映射为通用 `VALIDATION_ERROR`，且失败响应保留校验详情到 `data`；冻结合同要求精确的 `UNKNOWN_FIELD/INVALID_PAGINATION/FIELD_VALIDATION_FAILED` 等 code 且 `data=null`。
- 多个查询枚举只作为 ORM 字符串过滤，非法 `status/metric_code` 等可能得到空集合而不是 422；非法日期也缺少端点级显式解析证据。

## 5. 权限、tenant 与 data_scope

### 已通过

- 17 个 UI-P7 权限码已登记并有数据迁移。
- UI-P7 handler 使用 `DeclaredApplicationPermission`，仅允许具备精确权限和 scope 的 internal 用户。
- 查询首先限定 tenant 或 system 可见集合；详情使用授权 queryset 返回 404。
- 多条 CUSTOM scope 按 OR、单条配置不同 key 按 AND 组合。

### 未通过

- scope 校验只检查格式和冻结枚举，没有核验 `modules/environment_ids/*_ids` 是否已登记、数组是否去重、ID 数量是否为 1 至 100、environment 数量是否为 1 至 20。
- `ALL` 没有进一步限制为受控试点登记资源；任何新增 `PilotEnvironment` 都可能进入 ALL 可见集合。
- 恢复计划创建仅调用 `environment_allowed()`。当 `pilot.recovery.plan` 的 CUSTOM scope 只包含 `recovery_plan_ids` 时，该函数会因缺少 `environment_ids` 而放行任意已登记环境，创建权限没有按完整 permission-specific scope 求值。
- 现有定向测试未覆盖 external、RPA、system scope、跨 tenant、合法超 scope 空列表、详情 404、请求体 403 和各 action 独立 scope。

## 6. Mock/dry-run 与安全边界

### 已通过

- 合同检查、助手评估和拓扑校验均为固定本地逻辑。
- 助手响应明确 `human_confirmation_required=true`、`tool_calls=[]`、`business_writes=[]`。
- 未发现外部模型、真实平台、Docker socket、Shell、SQL、SSH、真实部署/恢复/回滚调用。
- 定向测试确认 Mock 不新增采购订单和 RPA 任务。

### 观察

- Mock 合同条目只覆盖少量示例，且若干示例使用与冻结公共模型不一致的字段；因此只能证明“无外部副作用”，不能证明合同一致性。

## 7. 恢复、发布与不可变审计

### 已通过

- 专用 transition service 使用事务、行锁、version 和幂等事件查询。
- 创建人与发布/恢复审批人分离；回滚批准人与创建人、发布审批人及回滚结果记录人分离。
- `resume` 与 `resume-rollback` 使用独立状态上下文和权限。
- 审计实例、QuerySet update/delete、bulk_update/bulk_create 受到不可变保护；tenant、用户和计划关联采用 PROTECT。

### 未通过

- `ProtectedStateModel` 和 manager 仅禁止直接修改 `status`。已批准的 `ReleasePlan` 仍可通过实例 `save()` 或 QuerySet `update()` 修改 `commit_sha/tag/rollback_point/database_compatibility`，也可直接改写回滚批准字段，而不会使既有审批失效或写审计。
- 回滚批准引用没有跨计划唯一约束，不能证明“rollback_approval_ref 唯一”。
- `_audit()` 只在成功保存状态后调用。版本冲突、非法状态、门禁失败、职责分离失败、回滚引用不匹配和批准过期均在审计调用前抛出异常；冻结合同要求成功与失败动作均留不可变审计，尤其要求回滚过期拒绝留痕。
- 对回滚批准替换、离开并重新进入 `rollback_required`、批准过期、不匹配引用、所有终态和失败/manual_required/cancelled 路径缺少完整回归证据。

## 8. 前端页面与动作权限

### 已通过

- API治理、助手、就绪、拓扑、恢复、发布和容量页面均有路由及菜单合同。
- 路由仅允许 internal 且按 view permission 访问；未登记路径继续默认拒绝。
- Mock 检查按钮使用精确 action permission；API 封装只访问 `/api/internal/governance/*` 和 `/api/internal/pilot/*`。
- 真实后端成功响应在受控 E2E 前保持 `sandbox`，未因 HTTP 200 标记为 `connected`。
- 页面未提供真实基础设施或高风险业务执行入口。

### 未通过

- 恢复/发布工作台只提供创建、提交、批准和拒绝。排期、开始记录、恢复、取消、演练/发布结果、独立回滚批准、回滚恢复和回滚结果均无页面交互，`pilot.*.record` 与 `pilot.release.rollback` 权限没有在页面动作层落实。
- 合同/助手详情路由已登记，但页面没有根据路由 `:id` 主动加载详情，只能从列表行点击打开抽屉，直接访问详情 URL 不形成合同要求的详情工作流。
- 页面和 Mock 沿用错误的 topology/readiness/capacity 字段，无法证明真实 API 切换后的字段映射正确。
- 前端 UI-P7 测试主要是源码字符串扫描，没有挂载组件验证 loading/empty/401/403/404/409/422/degraded/offline/stale、详情直达、分页和动作权限矩阵。

## 9. 实际测试与构建

| 检查 | R1实际结果 | 备注 |
|---|---|---|
| Django check | PASS | `System check identified no issues` |
| migration一致性 | PASS | `No changes detected` |
| 后端全量 pytest | PASS | `330 passed in 32.19s` |
| `npm ci` | PASS | 197 packages，0 vulnerabilities；首次因正在运行的 Vite 锁定 esbuild 失败，停止服务后干净重跑通过 |
| 前端全量测试 | PASS | 9 files / 105 tests |
| 前端构建 | PASS | Vite build通过 |
| Docker Compose静态解析 | PASS | exit 0；未加载真实环境变量，仅有空变量提示 |
| RPA JSON | PASS | 16 个，0 invalid |
| `git diff --check` | PASS | 仅换行转换提示 |
| 浏览器受控账号 E2E | 未执行 | 当前没有可用于独立复审的受控账号/真实认证测试环境；此前本地 Mock 冒烟不能替代该项，故继续保持 sandbox |

自动化“全绿”不能关闭本报告发现的问题：当前 UI-P7 后端仅 8 项定向测试、前端仅 6 项定向测试，未覆盖冻结验收矩阵要求的全部端点、字段、错误、状态迁移和越权反例。

## 10. 安全扫描结果

- 私钥头、常见真实密钥格式：0 matches。
- UI-P7 API/页面中的 `/api/rpa/*`、`/admin/`、Docker socket、Shell/SQL/SSH执行入口：0 matches。
- Git 跟踪的环境文件仅 `.env.example` 示例文件；未发现真实 `.env`、pem/key/p12/pfx。
- `frontend/dist`、`node_modules` 未跟踪；RPA运行目录仅跟踪 `.gitkeep`。
- 未发现真实账号、Token、Cookie、Session、API Key/API Secret、真实平台连接或真实业务/财务数据。

## 11. P0问题

无。

## 12. P1问题

| 编号 | 问题 | 证据 | 关闭标准 |
|---|---|---|---|
| UI-P7-R1-P1-001 | 公共响应模型、枚举和错误合同未统一 | `governance/serializers.py`、`pilot/views.py`、`pilot/serializers.py`、`common/exceptions.py` 及前端 Mock | 后端与 Mock 逐字段符合冻结模型；非法查询/字段精确返回冻结 HTTP/code 且失败 `data=null`；补齐合同测试 |
| UI-P7-R1-P1-002 | 状态防绕过、回滚批准失效和失败审计不完整 | `pilot/models.py` 仅保护 status；`pilot/services.py` 仅成功后调用 `_audit()` | 冻结关键字段或经服务修改并使审批失效；回滚 ref 唯一；所有成功/失败动作及过期拒绝均留不可变审计；补齐回归测试 |
| UI-P7-R1-P1-003 | permission-specific data_scope 严格性不足 | `ui_p7_scopes.py` 未核验登记资源/数量/去重；恢复创建仅使用 `environment_allowed()` | 严格核验登记值和数量；ALL限制受控资源；创建与每个 action 按 exact permission 完整求值；覆盖 external/RPA/tenant/system/403/404 |
| UI-P7-R1-P1-004 | 恢复、发布和回滚页面动作链未完成 | `PilotWorkflow.vue` 仅创建、提交、批准、拒绝；详情直达未加载 | 实现排期、记录开始/结果、人工恢复、取消和独立回滚动作，按 plan/review/record/rollback 权限显示；详情路由可直接加载；不得执行真实主机操作 |
| UI-P7-R1-P1-005 | 自动化与受控 E2E 证据不足 | 后端8项、前端6项定向测试，受控认证浏览器E2E未执行 | 覆盖37端点的字段/分页/400/401/403/404/409/422、双状态机、审计、scope及前端组件状态；使用受控账号完成E2E并保留sandbox/connected证据 |

## 13. P2问题

1. `npm ci` 保留 `esbuild`、`vue-demi` allow-scripts 审核提示。
2. Vite/Rollup 对第三方 `@vueuse/core` PURE 注释位置给出非阻断警告。

## 14. 整改与复审建议

1. 先按冻结公共模型修正后端 serializer、前端 Mock 和页面字段，并建立逐端点响应快照测试。
2. 对 ReleasePlan 的 commit/tag/rollback_point/审批字段建立不可变或受控服务规则；实现独立失败审计通道，避免业务事务回滚吞掉失败证据。
3. 收紧 scope 配置登记校验和恢复创建授权语义，补齐所有角色、tenant/system 和 action scope 反例。
4. 完成恢复/发布/回滚页面的全部受控“记录型”动作，不增加部署、恢复或回滚执行能力。
5. 扩展后端契约测试、前端组件测试，并在受控认证环境执行浏览器 E2E。
6. 完成整改后创建 R2 提示并执行独立 `UI-P7-ARCH-R2`；R2 前不得提交 UI-P7 正式收尾结论。

## 15. 是否允许 UI-P7 正式收尾

**不允许。** 当前无 P0，但 5 项 P1 未关闭；仅允许定向整改和 R2 复审。该结论不允许真实平台接入、生产发布、真实恢复/回滚、真实 RPA 或任何资金操作。
