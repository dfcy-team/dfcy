# UI-P8-ARCH-R1 独立实现复审报告

## 1. 审核对象与基线

- 审核分支：`feature/ui-p8-production-pilot-security-readiness`
- 当前 HEAD：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 与 `main` 的共同基线：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 审核依据：UI-P8 scope、R3 冻结 API 合同、验收清单、实现报告及当前工作区实现。
- 审核性质：只审核，不修复；本报告之外未因 R1 修改业务代码。

无关 DOCX、`docs/00_stage0/architecture/` 和 `docs/04_rpa/协同开发下发/` 未纳入 UI-P8 审核范围，后续提交仍须排除。

## 2. 审核结论

**CONDITIONAL_PASS**

未发现 P0、真实平台接入、真实密钥或高风险自动化，但发现 6 项未关闭 P1。当前只允许定向整改和 R2 复审，不允许 UI-P8 正式收尾、提交合并结论或进入真实生产试点。

## 3. 后端模型与 API

### 已通过

- 控制台、安全评审、验证、性能和准入决策端点均挂载在 `/api/internal/pilot/*`，未发现重复路由。
- 四类资源具备 tenant、受控环境、版本、幂等键和职责角色字段；tenant、环境、用户和审计关联使用 `PROTECT`。
- 成功响应、分页、400/401/403/404/409/422 基础异常外壳与冻结合同一致。
- 详情响应已移除未冻结辅助字段，安全评审成功响应字段集合已有回归断言。

### 未通过

- `SecurityPatchSerializer` 仅复用字段，没有执行安全评审创建时的跨字段校验。独立执行证明以下两类 PATCH 均被 serializer 接受：切换到 `finance_boundary` 但不提交 `finance_scope`；切换到非财务类型却保留非空 `finance_scope`。服务层也没有强制“离开 finance_boundary 必须显式清空”。
- `target_alias` 只校验 slug 格式，没有核验其为当前 tenant/environment 已登记的受控别名；普通 `evidence_refs` 也只做格式和敏感模式检查，没有受控引用登记校验。

## 4. 权限、tenant 与 data_scope

### 已通过

- 17 个 UI-P8 exact permission 已登记并提供迁移。
- `DeclaredApplicationPermission` 要求 authenticated internal 用户、精确权限和权限对应 data scope；external/RPA 不能通过该入口。
- CUSTOM scope 严格拒绝未知 key、空数组、重复值、非法枚举、未登记环境、跨 tenant ID 和超限值。
- 创建按 `pilot_environments` 授权；详情和 action 使用对应资源 ID scope；PATCH 环境变化校验原环境、目标环境和资源 ID。
- 准入引用按五类资源分别检查 view permission、data_scope、tenant 和 environment。

### 未通过

- 控制台财务门禁仅调用 `check_user_permission(finance.view)`；没有对 `finance.view` 的 data_scope 完整性和有效值执行同等校验。拥有权限码但 scope 缺失或非法时可能不显示 restricted。
- 对 `finance_boundary` 目标组合的 PATCH 校验不闭合，属于权限与目标属性共同越界风险。

## 5. 状态机、证据与审计

### 已通过

- submit、approve/reject、record-result、cancel 使用事务、行锁、version 和 Idempotency-Key。
- 创建人与审批人分离；验证/性能审批人与结果记录人分离；submitted/approved 取消限制创建人。
- QuerySet update/delete、bulk_update/bulk_create、实例修改受保护字段和实例删除受到保护。
- 安全评审及准入惰性过期使用 system actor、版本递增和不可变审计；审计记录和 tenant 删除使用保护语义。
- 准入 submit 由后端读取来源并生成 evidence snapshot、hash 和 contract version。

### 未通过

- 准入 `approve` 仅检查 submit 时保存的 `blockers`，没有重新读取引用资源并验证其当前状态、版本和有效期。提交后安全评审过期或来源状态变化时，旧快照仍可能被批准为 `go`。
- 控制台只惰性过期安全评审，没有对 `EntryDecision` 执行合同要求的同一过期服务，虽然查询不会把已到期 approved go 当作有效，但状态和 system 审计不会由控制台读取补写。
- `_audit()` 只在成功创建、成功 PATCH、成功 action 和系统过期后调用。权限拒绝、data_scope 拒绝、serializer 422、版本/状态/幂等 409 均没有独立失败审计通道；测试也未断言失败审计。
- 模型保护只在已有实例保存时比较受保护字段。直接 `objects.create(status='approved', ...)` 仍可绕过初始 draft 和创建服务；冻结合同要求模型直接保存和 admin/bulk 入口均不能绕过。

## 6. 前端页面、权限和状态

### 已通过

- 五个 UI-P8 工作台、列表/详情路由和菜单均存在，路由只允许 internal 且按 exact view permission 放行。
- 创建、提交、审核、结果记录和取消按钮按 plan/review/record/cancel 权限与状态显示。
- API 仅访问 `/api/internal/pilot/*`，未访问 `/api/rpa/*`、`/api/finance/*` 或 `/admin/`。
- Mock 保持 `mock`，真实成功响应仍强制保持 `pending`，没有误标 `connected`。
- 已增加真实组件挂载测试，覆盖 loading、empty、无效详情 404 和 view-only 动作隐藏。

### 未通过

- 工作台列表未实现筛选和分页控件，`fetchP8Resources()` 始终使用默认参数；冻结验收要求分页状态及组件交互证据。
- 页面没有 PATCH 编辑流程，安全评审、验证、性能和准入草稿只能创建固定 demo 数据后执行状态动作，不能验证 PATCH 字段、版本冲突和目标 scope 的页面错误展示。
- 组件测试尚未覆盖 401、403、409、422、stale、offline、分页、全部 action permission 组合及成功 action 后的真实组件状态。
- `docs/00_stage0/frontend_api_mapping.md` 仍写明“UI-P8 尚未实现”，并把五项 Mock 文件登记为不存在的 `frontend/src/mock/pilotReadiness.js`；实际实现位于 `frontend/src/mock/pilot.js`，当前映射会误导联调和验收。

## 7. 测试与构建实际结果

2026-07-20 独立复跑结果：

| 检查 | R1 结果 | 备注 |
|---|---|---|
| Django check | PASS | `System check identified no issues` |
| migration 一致性 | PASS | `No changes detected` |
| 临时测试数据库迁移 | PASS | pytest 创建测试数据库并应用迁移 |
| 后端全量 pytest | PASS | `393 passed in 40.32s` |
| `npm ci` | PASS | 249 packages，0 vulnerabilities |
| 前端全量测试 | PASS | 11 files / 139 tests |
| 前端生产构建 | PASS | Vite build 通过 |
| Docker Compose 静态解析 | PASS | exit 0；未加载真实环境变量，仅有空变量提示 |
| RPA JSON | PASS | 16 个，0 invalid |
| `git diff --check` | PASS | 仅换行转换提示 |
| 受限角色 JWT 浏览器 E2E | 未执行 | 当前没有独立复审可使用的受控账号和认证测试数据；不得以 Mock 代替 |
| 远端 CI | 未执行 | 当前实现尚未提交和推送，尚无可审核的 PR HEAD |

自动化全绿不能关闭本报告发现的问题。当前 UI-P8 后端专项测试仅 15 项，未覆盖 entry 完整状态机、证据过期后审批、cancel、跨 tenant、external/RPA、失败审计、并发和直接创建绕过；前端专项测试 9 项，未覆盖冻结的完整组件矩阵。

## 8. 安全扫描结果

- 高置信私钥、AWS key、GitHub token 和 `sk-` 密钥签名：0 matches。
- UI-P8 实现中的外部 HTTP、RPA Agent、finance/admin、Shell、Docker、SSH 执行调用：0 matches。
- `frontend/dist`、`node_modules` 处于忽略状态；未发现被跟踪的构建缓存。
- 未发现真实 `.env`、账号、密码、Token、Cookie、Session、API Key/API Secret、真实平台连接或真实业务/财务数据。
- 未发现自动采购、供应商通知、改库存、刊登、改价、清仓、停售、归档、真实 RPA、付款、转账或提现能力。

## 9. P0

无。

## 10. P1

| 编号 | 问题 | 证据 | 关闭标准 |
|---|---|---|---|
| UI-P8-R1-P1-001 | 财务安全评审 PATCH 与受控引用校验不闭合 | `ui_p8_serializers.py` 的动态 PatchSerializer 不执行创建跨字段规则；独立 serializer 检查接受两类非法组合；target_alias/evidence_refs 未核验登记资源 | 对 PATCH 目标组合执行同创建规则，切入/离开财务边界规则唯一；校验受控别名和证据引用；补 422/403/无写入测试 |
| UI-P8-R1-P1-002 | 准入批准与控制台过期证据未重新验证 | `transition_resource()` approve 只读取旧 blockers；`control_room_payload()` 只过期 SecurityReview | approve 重新读取并锁定全部来源，拒绝 stale/版本变化/越 scope；控制台对 EntryDecision 使用统一过期服务；补回归和并发测试 |
| UI-P8-R1-P1-003 | 失败审计合同未实现 | UI-P8 view/service 无失败 audit wrapper，`_audit()` 仅成功和 expire 使用 | 403、DATA_SCOPE、422、409 通过独立事务写不可变失败审计且不污染业务事务；覆盖创建和全部 action |
| UI-P8-R1-P1-004 | 状态机创建入口仍可直接绕过 | `ProtectedStateModel.save()` 对新实例不校验初始状态，manager `create()` 未禁用 | 限制普通直接创建只能得到合法 draft 或只允许受控服务创建；补实例、manager、admin/bulk 回归测试 |
| UI-P8-R1-P1-005 | 前端工作台与组件验收矩阵不完整 | `P8WorkflowWorkspace.vue` 无分页、筛选和 PATCH；测试未覆盖完整错误/action 状态矩阵 | 实现分页、必要筛选和草稿 PATCH；挂载组件覆盖 401/403/404/409/422/stale/offline、分页和逐 action 权限 |
| UI-P8-R1-P1-006 | 接口映射与端到端证据不完整 | 总映射仍称未实现并引用不存在的 Mock 文件；无受限 JWT E2E 和远端 CI | 更新实现状态和真实 Mock 路径；用受限账号完成浏览器 E2E；提交后以固定 HEAD 取得远端 CI 成功证据 |

## 11. P2

1. `npm ci` 保留 `esbuild`、`vue-demi` allow-scripts 审核提示。
2. Vite/Rollup 对第三方 `@vueuse/core` PURE 注释位置给出非阻断警告。

## 12. 整改建议

1. 先关闭后端财务 PATCH、准入证据刷新、失败审计和直接创建防绕过四项，补齐定向测试。
2. 再补前端分页、筛选、PATCH 和组件状态矩阵，并修正总接口映射。
3. 建立受限 internal 账号与 demo/合成数据，执行真实 JWT 浏览器 E2E，所有新端点仍保持 pending。
4. 完成整改后创建 `ui_p8_arch_r2_recheck_prompt.md`，执行独立 R2；R2 PASS 前不得正式收尾。

## 13. 是否允许 UI-P8 正式收尾

**不允许。**

当前无 P0，但存在 6 项未关闭 P1，仅允许定向整改和 R2 复审。该结论不允许真实平台接入、生产发布、主机执行、真实 RPA、自动采购或资金操作。
