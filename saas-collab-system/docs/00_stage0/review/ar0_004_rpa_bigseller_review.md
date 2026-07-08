# AR0-004 RPA Agent 与 BigSeller 文档专项审核报告

## 1. 审核对象

- 项目根目录：`saas-collab-system/`
- 审核范围：
  - `rpa-agent/`
  - `docs/04_rpa/`
  - `docs/04_rpa/examples/`
  - `rpa-agent/tasks/examples/`
  - `.gitignore`
- 审核时间：2026-07-08
- 审核人员：系统架构需求拆分和核实人员
- 审核依据：
  - `docs/00_stage0/review/ar0_003_r1_frontend_rpa_recheck.md`
  - `docs/04_rpa/bigseller_rpa_steps.md`
  - `docs/04_rpa/examples/`
  - `rpa-agent/`
  - `rpa-agent/tasks/examples/`

## 2. 审核结论

结论：`CONDITIONAL_PASS`

判断依据：

- 未发现真实密钥、真实账号、真实 Token、真实数据库密码、RPA 直连数据库、真实自动化脚本或真实平台连接配置。
- RPA Agent 目录、环境变量示例、BigSeller 步骤文档、payload/result 样例、运行目录与 `.gitignore` 已满足阶段0主体要求。
- 存在 P1 问题：RPA 与后端接口边界未完整列明 `heartbeat`、`complete`、`fail` 等阶段1关键执行端点；`BIGSELLER_UPDATE_PRICE` payload 未显式包含审批单号或审批通过状态，不能充分证明阶段1不会绕过审批执行改价。
- 因无 P0 但存在 P1，结论为 `CONDITIONAL_PASS`。

## 3. 已完成项

### RPA Agent目录

- 已存在 `rpa-agent/README.md`、`rpa-agent/.env.example`。
- 已存在 `agents/`、`bigseller/steps/`、`bigseller/selectors/`、`bigseller/examples/`、`tasks/examples/`、`screenshots/`、`logs/`、`config/`、`cache/`、`downloads/`。
- 运行目录 `screenshots/`、`logs/`、`cache/`、`downloads/` 当前仅保留 `.gitkeep`。

### 环境变量示例

- `rpa-agent/.env.example` 仅包含 `RPA_AGENT_NAME`、`RPA_AGENT_TOKEN`、`RPA_API_BASE_URL`、`BIGSELLER_LOGIN_URL`、`HEADLESS`。
- `RPA_AGENT_TOKEN=change-me-rpa-token` 为示例值。
- `BIGSELLER_LOGIN_URL=https://example.com/bigseller-login` 为示例地址。

### BigSeller步骤文档

- `docs/04_rpa/bigseller_rpa_steps.md` 覆盖 10 类流程。
- 每个流程均包含：流程名称、输入字段、页面步骤、成功判断、失败判断、截图节点、回写字段、人工接管条件。
- 选择器使用 `selector.*` 占位名称。

### Payload与Result样例

- `docs/04_rpa/examples/` 和 `rpa-agent/tasks/examples/` 均包含 8 个指定 JSON 文件。
- 16 个 JSON 文件格式有效。
- payload 文件均包含 `task_type`、`business_type`、`business_id`、`payload`。
- result 文件均包含 `status`、`message`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- `docs/04_rpa/examples/README.md` 已说明每个 JSON 用途。

### 运行产物与.gitignore

- `.gitignore` 已忽略 `rpa-agent/screenshots/*`、`rpa-agent/logs/*`、`rpa-agent/cache/`、`rpa-agent/downloads/`。
- 未发现真实截图、真实页面 HTML、真实导出文件。

## 4. 缺失项

### RPA接口边界缺失

- 未在当前 RPA 文档或 README 中完整列明以下阶段1关键端点：
  - `/api/rpa/tasks/{id}/heartbeat/`
  - `/api/rpa/tasks/{id}/complete/`
  - `/api/rpa/tasks/{id}/fail/`
- 当前已有 `/api/rpa/tasks/claim/`、`/api/rpa/tasks/{id}/logs/`、`/api/rpa/tasks/{id}/screenshots/`、`/api/rpa/tasks/{id}/result/` 等说明，但与专项审核清单中的执行协议不完全一致。

### 高风险改价审批字段缺失

- `BIGSELLER_UPDATE_PRICE` 示例包含 `approved_price`，但未显式包含 `approval_id`、`approval_status` 或等价审批通过凭证字段。
- 阶段1前需要明确 RPA 只能执行后端已审批任务，不得自行决定改价。

### Result协议关联字段不足

- `rpa_task_success_result.json` 和 `rpa_task_failed_result.json` 未包含 `task_id`。
- 该项不影响此前必填字段校验，但从任务协议完整性看，建议补充任务关联字段，便于阶段1回写和审计追踪。

## 5. 越界项

- 未发现真实浏览器自动化脚本。
- 未发现真实改价脚本。
- 未发现真实平台连接逻辑。
- 未发现 RPA 直连 MySQL、Redis 或任何数据层配置。
- 未发现 RPA 访问 `/api/finance/*` 或 `/api/internal/finance/*` 的配置。
- 未发现 `/admin/` 被用作 RPA 业务接口。
- 未发现真实 BigSeller 账号、密码、Token、店铺信息或真实选择器。

## 6. 安全风险

扫描范围：

- `rpa-agent/`
- `docs/04_rpa/`

扫描关注项：

- `password`、`secret`、`token`、`api_key`、`apikey`、`api-secret`、`cookie`、`session`
- `mysql`、`redis`、`finance`、`bank`、`account`
- `BigSeller`、`Shopee`、`TikTok`、`TK`
- 真实平台 URL、真实选择器、真实浏览器自动化代码

扫描结果：

- `rpa-agent/.env.example` 中出现 `RPA_AGENT_TOKEN=change-me-rpa-token`，判断为示例值，不构成 P0。
- `rpa-agent/.env.example` 中出现 `BIGSELLER_LOGIN_URL=https://example.com/bigseller-login`，判断为 example.com 示例地址，不构成 P0。
- 文档中出现 BigSeller、Token、账号密码等词汇均为边界说明或禁止说明，不构成 P0。
- 未发现真实 Token、Cookie、Session、API Key、数据库密码、银行或财务数据。
- 未发现 MySQL/Redis 连接配置。

安全判断：未发现 P0 安全风险。

## 7. 模块审核明细

| 模块 | 结论 | 证据 | 说明 |
|---|---|---|---|
| RPA Agent目录结构 | PASS | `rpa-agent/` | 目录齐全，空目录有 `.gitkeep` 或 README 占位 |
| RPA环境变量示例 | PASS | `rpa-agent/.env.example` | 仅包含示例字段，未发现数据库或财务接口配置 |
| BigSeller RPA步骤文档 | PASS | `docs/04_rpa/bigseller_rpa_steps.md` | 覆盖 10 类流程，选择器为 `selector.*` 占位 |
| RPA任务类型 | CONDITIONAL_PASS | `docs/04_rpa/examples/*.json`、`rpa-agent/tasks/examples/*.json` | 6 类任务类型齐全；改价任务需补审批凭证字段 |
| RPA payload/result样例 | CONDITIONAL_PASS | `docs/04_rpa/examples/`、`rpa-agent/tasks/examples/` | JSON 有效；result 建议补 `task_id` |
| RPA与后端接口边界 | CONDITIONAL_PASS | `docs/00_stage0/frontend_api_mapping.md`、`docs/04_rpa/bigseller_rpa_steps.md`、`rpa-agent/README.md` | 已明确 `/api/rpa/*`，但缺少 heartbeat/complete/fail 端点说明 |
| RPA运行产物与.gitignore | PASS | `.gitignore`、`rpa-agent/screenshots/`、`rpa-agent/logs/`、`rpa-agent/cache/`、`rpa-agent/downloads/` | 运行目录仅 `.gitkeep`，忽略规则覆盖运行产物 |

## 8. P0问题

无。

## 9. P1问题

### AR0-004-P1-001 RPA与后端执行接口边界未完整列明

- 责任人：开发A
- 涉及目录：`docs/04_rpa/`、后续后端 RPA 接口文档
- 问题描述：当前文档明确 RPA 只能访问 `/api/rpa/*`，但未完整列明 `claim`、`heartbeat`、`logs`、`complete`、`fail`、截图提交等阶段1执行端点及字段边界。
- 风险：阶段1开发时 Agent 与后端接口语义可能不一致，导致任务状态回写、失败处理、心跳超时和截图留证缺少统一契约。

### AR0-004-P1-002 改价任务缺少审批凭证字段

- 责任人：开发B
- 涉及目录：`docs/04_rpa/examples/`、`rpa-agent/tasks/examples/`
- 问题描述：`BIGSELLER_UPDATE_PRICE` payload 使用 `approved_price`，但未显式包含 `approval_id`、`approval_status` 或等价审批通过凭证字段。
- 风险：阶段1若按该样例扩展，可能无法证明 RPA 改价任务来自后端审批通过结果，不符合“RPA 不允许绕过审批执行改价”的边界。

## 10. P2问题

### AR0-004-P2-001 result样例缺少task_id

- 责任人：开发B
- 涉及目录：`docs/04_rpa/examples/`、`rpa-agent/tasks/examples/`
- 问题描述：成功和失败 result 示例未包含 `task_id`。
- 影响：不影响阶段0 JSON 必填字段校验，但不利于阶段1结果回写、日志追踪和审计关联。

### AR0-004-P2-002 BIGSELLER_READ_PAGE_PRICE只读边界可更明确

- 责任人：开发B
- 涉及目录：`docs/04_rpa/`
- 问题描述：文档描述为页面价格回读，但可进一步明确该任务不得点击保存、不得修改页面价格、不得触发平台提交。
- 影响：属于边界表达增强项。

## 11. 整改任务建议

| 编号 | 等级 | 问题描述 | 责任人 | 涉及目录 | 整改要求 | 验收标准 |
|---|---|---|---|---|---|---|
| AR0-004-P1-001 | P1 | RPA与后端执行接口边界未完整列明 | 开发A | `docs/04_rpa/`、后续后端 RPA 接口文档 | 补充 `/api/rpa/tasks/claim/`、`/api/rpa/tasks/{id}/heartbeat/`、`/api/rpa/tasks/{id}/logs/`、`/api/rpa/tasks/{id}/complete/`、`/api/rpa/tasks/{id}/fail/`、截图提交或 `screenshot_url` 规则 | 文档明确每个端点的用途、请求字段、返回字段、状态流转和禁止访问范围 |
| AR0-004-P1-002 | P1 | 改价任务缺少审批凭证字段 | 开发B | `docs/04_rpa/examples/`、`rpa-agent/tasks/examples/` | 为 `BIGSELLER_UPDATE_PRICE` payload 增加 `approval_id`、`approval_status=approved` 或等价审批通过凭证字段，并在文档中说明 RPA 只执行后端已审批任务 | 示例和文档均能证明 RPA 不自行决定改价、不绕过审批 |
| AR0-004-P2-001 | P2 | result样例缺少task_id | 开发B | `docs/04_rpa/examples/`、`rpa-agent/tasks/examples/` | 在成功/失败 result 示例中补充 `task_id` | result 与任务可直接关联，便于回写和审计 |
| AR0-004-P2-002 | P2 | READ_PAGE_PRICE只读边界可更明确 | 开发B | `docs/04_rpa/` | 在页面价格回读流程中补充“不保存、不提交、不修改页面价格”的说明 | 文档明确该任务为只读采集任务 |

## 12. 阶段1准入建议

建议：有条件允许进入阶段1准备，但 P1 必须在阶段1正式开发 RPA 执行逻辑前整改完成。

准入说明：

- 当前未发现 P0 风险，不阻断阶段1准备工作。
- RPA 目录、阶段0文档、payload/result 样例、运行目录和安全边界已具备阶段1讨论基础。
- 阶段1正式实现 RPA Agent 与后端任务执行前，必须先关闭 AR0-004-P1-001 和 AR0-004-P1-002，避免接口契约不清和高风险改价绕过审批。
