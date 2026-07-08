# AR0-008 前后端接口一致性审核报告

## 1. 审核对象
- 项目根目录：`saas-collab-system/`
- 审核范围：`docs/00_stage0/frontend_api_mapping.md`、`docs/04_rpa/`、`backend/config/urls.py`、`backend/apps/*/urls.py`、`frontend/src/api/*.js`、`frontend/src/router/index.js`、`frontend/src/views/`
- 审核时间：2026-07-08
- 审核人员：系统架构需求拆分和核实人员
- 审核依据：
  - `docs/00_stage0/frontend_api_mapping.md`
  - `docs/04_rpa/rpa_api_protocol.md`
  - `docs/04_rpa/bigseller_rpa_steps.md`
  - `docs/00_stage0/review/ar0_002_r1_backend_base_recheck.md`
  - `docs/00_stage0/review/ar0_003_r1_frontend_rpa_recheck.md`
  - `docs/00_stage0/review/ar0_004_r1_rpa_bigseller_recheck.md`
  - `docs/00_stage0/review/ar0_005_system_boundary_review.md`
  - `docs/00_stage0/review/ar0_006_security_secret_review.md`
  - `docs/00_stage0/review/ar0_007_start_build_test_review.md`
  - `backend/config/urls.py`
  - `backend/apps/*/urls.py`
  - `frontend/src/api/*.js`
  - `frontend/src/router/index.js`

## 2. 审核结论

PASS

判断说明：
- 未发现 P0 问题。
- 未发现 P1 问题。
- 发现 2 个 P2 问题，均为阶段0文档/占位口径优化项，不存在真实越界调用或阶段1准入阻断。

## 3. 已完成项

- 后端URL：`backend/config/urls.py` 已预留 `/api/internal/`、`/api/external/`、`/api/rpa/`、`/api/platform/`、`/api/wechat/`、`/api/feishu/`、`/api/finance/`、`/api/report/`、`/admin/` 分区。
- 后端业务边界：`/admin/` 仅挂载 Django Admin；`/api/rpa/*` 已提供任务领取、心跳、日志、完成、失败占位；`/api/finance/*` 独立于 internal，财务 health 使用财务权限。
- 前端API：`frontend/src/api/request.js` 从 `VITE_API_BASE_URL` 读取 baseURL，存在 `VITE_USE_MOCK` Mock 开关；当前业务 API 文件均返回 Mock 数据或 pending 响应。
- 接口映射清单：`docs/00_stage0/frontend_api_mapping.md` 覆盖 25 个指定页面，字段包含页面名称、页面路径、API、方法、参数、返回字段、Mock 文件、后端负责人、当前状态。
- 状态标记：25 个页面状态仅为 `mock` 或 `pending`，未发现未完成接口被标记为 `connected`。
- 路径边界：供应商页面规划为 `/api/external/*`；财务页面规划为 `/api/finance/*`；报表页面规划为 `/api/report/*`；RPA Agent 执行接口规划为 `/api/rpa/*`。
- RPA协议：`docs/04_rpa/rpa_api_protocol.md` 与 `docs/04_rpa/bigseller_rpa_steps.md` 明确 RPA Agent 只能访问 `/api/rpa/*`，不得访问 `/api/finance/*`、`/api/internal/finance/*` 或 `/admin/`。
- 权限接口：前端路由守卫和 auth store 明确阶段0权限仅为展示占位，真实权限以后端 `/api/internal/auth/me/` 返回的 `roles`、`permissions`、`tenant_id`、`user_type` 为准。
- 页面映射：接口映射清单中 25 个页面均能在 `frontend/src/router/index.js` 找到对应路由；映射中引用的 Mock 文件均存在。

## 4. 缺失项

- 后端当前未提供独立 `POST /api/rpa/tasks/{id}/screenshots/` 占位路由；RPA协议和步骤文档列明该端点，同时说明阶段1可通过 logs/result 中的 `screenshot_url` 或 `screenshots` 占位字段先行处理。
- `docs/00_stage0/frontend_api_mapping.md` 尚未列出 `/api/platform/*`、`/api/wechat/*`、`/api/feishu/*` 的页面映射项；当前这些属于后端 health/回调占位而非前端页面，不构成 P1。

## 5. 不一致项

### AR0-008-P2-001 RPA result路径与最新complete/fail协议口径不完全一致

- 证据：`docs/00_stage0/frontend_api_mapping.md` 的 RPA Agent 示例仍包含 `/api/rpa/tasks/{id}/result/`。
- 对比：`docs/04_rpa/rpa_api_protocol.md`、`docs/04_rpa/bigseller_rpa_steps.md` 和 `backend/apps/rpa/urls.py` 已使用 `/api/rpa/tasks/{id}/complete/` 与 `/api/rpa/tasks/{id}/fail/` 作为成功/失败主回写路径。
- 判断：未发现前端或 RPA Agent 真实调用 `/result/`；属于文档旧口径残留，记录为 P2。

### AR0-008-P2-002 RPA截图提交端点在后端占位路由中尚未独立实现

- 证据：`docs/04_rpa/rpa_api_protocol.md` 和 `docs/04_rpa/bigseller_rpa_steps.md` 均列出 `/api/rpa/tasks/{id}/screenshots/`；`backend/apps/rpa/urls.py` 当前仅有 `claim`、`heartbeat`、`logs`、`complete`、`fail`。
- 判断：文档已说明可通过 logs/result 中 `screenshot_url` 或 `screenshots` 占位字段过渡，未发现真实调用冲突，记录为 P2。

## 6. 越界项

- 供应商访问 internal：未发现。映射清单中供应商任务和出货页面均使用 `/api/external/supplier/*`。
- RPA访问 finance/admin：未发现。RPA协议、步骤文档和 rpa-agent README 均明确禁止；前端 RPA 页面 API 仅使用 Mock，不访问财务或 admin。
- 前端调用 `/admin/` 作为业务接口：未发现。
- 未完成接口标记 connected：未发现。
- 真实平台接入：未发现真实 BigSeller、Shopee、TK/TikTok API 接入。
- 阶段0越界业务：未发现真实自动改价、自动清仓、自动补货或财务自动对账。

## 7. 安全快速复核

扫描范围：
- `backend/`
- `frontend/`
- `rpa-agent/`
- `docs/00_stage0/`
- `docs/04_rpa/`
- `.env.example`
- `docker-compose.yml`

命中项与判断：
- `password`、`secret`、`token`、`api_key` 等命中为测试值、字段名、示例值或文档禁止说明，不构成 P0。
- `/api/finance` 命中主要为财务接口映射、禁止 RPA 访问说明和财务权限测试，不构成 P0。
- `/api/internal` 命中主要为内部页面映射、auth/me 权限来源说明，不构成 P1。
- `/api/external` 命中主要为供应商页面映射，不构成 P1。
- `/api/rpa` 命中主要为 RPA协议和后端占位路由，不构成 P0。
- `/admin/` 命中均为禁止说明或 Django Admin 路由，未发现前端业务调用。

结论：
- 未发现真实密钥、真实账号、真实 Token、真实 Cookie、真实平台 URL 或真实银行数据。
- 未发现供应商访问 internal、RPA访问 finance/admin、前端调用 admin 的真实越界行为。

## 8. 模块审核明细

| 模块 | 结论 | 证据 | 备注 |
|---|---|---|---|
| 后端URL分区 | PASS | `backend/config/urls.py`、`backend/apps/*/urls.py` | 指定 URL 分区均存在；`/admin/` 仅为 Django Admin |
| 前端API文件 | PASS | `frontend/src/api/*.js`、`frontend/src/api/request.js` | 当前全部使用 Mock/pending；未发现真实后端公网地址、真实平台 API 或 `/admin/` 调用 |
| 接口映射清单 | PASS | `docs/00_stage0/frontend_api_mapping.md` | 覆盖 25 个页面；状态仅为 `mock` / `pending` |
| RPA接口一致性 | PASS_WITH_P2 | `docs/04_rpa/rpa_api_protocol.md`、`docs/04_rpa/bigseller_rpa_steps.md`、`backend/apps/rpa/urls.py` | 主路径为 `claim/heartbeat/logs/complete/fail`；`result` 旧口径和截图端点记录为 P2 |
| 权限接口一致性 | PASS | `backend/apps/accounts/`、`backend/apps/permissions/`、`backend/apps/finance/`、`frontend/src/stores/auth.js`、`frontend/src/router/index.js` | 真实权限以后端 `/api/internal/auth/me/` 为准；财务独立授权；前端仅展示占位 |
| 页面与API映射一致性 | PASS | `frontend/src/router/index.js`、`frontend/src/views/**/*.vue`、`frontend/src/mock/*.js`、`docs/00_stage0/frontend_api_mapping.md` | 25 个映射页面均有路由；Mock 文件存在；页面标注多为逻辑名，映射清单提供实际后续 API 路径 |
| 状态标记 | PASS | `docs/00_stage0/frontend_api_mapping.md`、`frontend/src/api/*.js`、`frontend/src/mock/*.js` | 未发现未完成接口标记 `connected` |
| 安全快速复核 | PASS | `rg` 扫描结果 | 未发现真实凭据、真实平台接入或接口越界 |

## 9. P0问题

无。

## 10. P1问题

无。

## 11. P2问题

### AR0-008-P2-001 RPA result路径与最新complete/fail协议口径不完全一致

- 问题描述：`frontend_api_mapping.md` 的 RPA Agent 示例仍包含 `/api/rpa/tasks/{id}/result/`，而最新协议和后端占位以 `/complete/`、`/fail/` 为成功/失败回写主路径。
- 影响判断：当前无真实调用，不构成 P1。
- 责任人：架构人员

### AR0-008-P2-002 RPA截图提交端点在后端占位路由中尚未独立实现

- 问题描述：RPA协议列出 `/api/rpa/tasks/{id}/screenshots/`，后端占位路由尚未提供该端点。
- 影响判断：文档允许通过 logs/result 字段过渡，且阶段0不实现真实截图上传，不构成 P1。
- 责任人：开发A

## 12. 整改任务建议

| 编号 | 等级 | 问题描述 | 责任人 | 涉及目录 | 整改要求 | 验收标准 |
|---|---|---|---|---|---|---|
| AR0-008-P2-001 | P2 | RPA result路径与最新complete/fail协议口径不完全一致 | 架构人员 | `docs/00_stage0/frontend_api_mapping.md`、`docs/04_rpa/` | 后续统一说明 `/result/` 是否废弃、兼容或仅为历史口径，并以 `/complete/`、`/fail/` 作为阶段1主路径 | 接口映射、RPA协议、后端路由不再出现互相矛盾的结果回写主路径 |
| AR0-008-P2-002 | P2 | RPA截图提交端点在后端占位路由中尚未独立实现 | 开发A | `backend/apps/rpa/`、`docs/04_rpa/` | 阶段1前明确截图提交采用独立 `/screenshots/` 端点或 logs/result 字段，并补齐对应后端占位与测试 | 后端路由、协议文档、样例 result 与测试用例对截图提交方式保持一致 |

## 13. 阶段1准入建议

1. 允许进入阶段1。
2. 当前未发现必须先处理的 P0/P1 接口一致性问题。
3. 阶段1开发时必须继续遵守以下接口路径边界：
   - 内部后台页面使用 `/api/internal/*`。
   - 供应商外部页面使用 `/api/external/*`，不得访问 `/api/internal/*`。
   - RPA Agent 执行接口只能使用 `/api/rpa/*`，不得访问 `/api/finance/*`、`/api/internal/finance/*` 或 `/admin/`。
   - 财务页面使用 `/api/finance/*`，并保持独立财务权限控制。
   - 报表页面使用 `/api/report/*`。
   - 平台同步使用 `/api/platform/*` 或 `/api/internal/integrations/*` 占位，不得承担页面操作。
   - 微信、飞书回调分别使用 `/api/wechat/*`、`/api/feishu/*`。
   - 未完成接口继续标记为 `mock` 或 `pending`，不得提前标记 `connected`。
   - `/admin/` 仅用于 Django Admin，不作为业务接口。
   - 阶段1接入真实平台前必须另行完成密钥、审计、权限、网络隔离和接口契约审核。

