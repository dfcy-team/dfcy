# AR0-005 API/RPA/权限/供应商/财务系统边界审核报告

## 1. 审核对象
- 项目根目录：`saas-collab-system/`
- 审核范围：`backend/`、`frontend/`、`rpa-agent/`、`docs/00_stage0/`、`docs/04_rpa/`、`.env.example`、`docker-compose.yml`
- 审核时间：2026-07-08
- 审核人员：系统架构需求拆分和核实人员
- 审核依据：
  - `docs/00_stage0/stage0_file_scope.md`
  - `docs/00_stage0/frontend_api_mapping.md`
  - `docs/00_stage0/review/ar0_002_r1_backend_base_recheck.md`
  - `docs/00_stage0/review/ar0_003_r1_frontend_rpa_recheck.md`
  - `docs/00_stage0/review/ar0_004_r1_rpa_bigseller_recheck.md`
  - `docs/04_rpa/rpa_api_protocol.md`
  - `docs/04_rpa/bigseller_rpa_steps.md`
  - `backend/`
  - `frontend/`
  - `rpa-agent/`

## 2. 审核结论

PASS

判断说明：
- 未发现 P0 问题。
- 未发现 P1 问题。
- 发现 2 个 P2 观察项，不影响阶段1准入，但建议阶段1接口实现前统一收口。

## 3. 已完成项

- API边界：`backend/apps/integrations/` 仅包含平台枚举、API配置模型、同步任务、同步日志、数据质量检查和 health 占位；未发现页面点击、页面录入、页面价格修改或真实外部平台调用。
- RPA边界：`docs/04_rpa/rpa_api_protocol.md` 和 `rpa-agent/README.md` 明确 RPA Agent 只能访问 `/api/rpa/*`，不得访问 `/api/finance/*`、`/api/internal/finance/*`、`/admin/`，不得直连 MySQL/Redis。
- 权限边界：后端存在 `Role`、`Permission`、`UserRole`、`DataScope`；用户区分 `internal`、`external`、`rpa`；存在 `IsInternalUser`、`IsExternalUser`、`IsRPAAgent`、`IsFinanceUser`。
- 财务边界：`IsFinanceUser` 要求 internal 用户同时具备财务权限码或财务角色；已预留 `finance.view`、`finance.export`、`finance.reconcile`、`finance.import`、`finance.exception.handle`。
- 供应商边界：`ExternalUserProfile` 预留 `supplier_id`；前后端接口清单将供应商页面规划到 `/api/external/*`，未将供应商页面规划为 `/api/internal/*`。
- 多租户边界：用户、角色、数据范围、RPA、API同步、文件、审计等核心模型均具备 `tenant` 或 `tenant_id` 隔离意识。
- 安全边界：未发现真实 BigSeller、Shopee、TikTok/TK 账号、密码、Token、API Key、Cookie、Session、真实店铺或真实平台 URL。

## 4. 缺失项

- 后端 `backend/apps/rpa/urls.py` 当前已提供 `claim`、`heartbeat`、`logs`、`complete`、`fail` 占位端点，但尚未提供独立 `screenshots` 占位端点；文档允许阶段1先通过 `logs/result` 中的 `screenshot_url` 或 `screenshots` 占位，因此记录为 P2。
- `docs/00_stage0/frontend_api_mapping.md` 的 RPA Agent 示例仍列出 `/api/rpa/tasks/{id}/result/`，而最新 RPA 协议使用 `/complete/` 与 `/fail/` 回写成功/失败结果；属于文档口径不完全一致，记录为 P2。

## 5. 越界项

- 真实平台接入：未发现真实 BigSeller、Shopee、TikTok/TK API 调用。
- 真实自动化：未发现真实浏览器自动化脚本、真实选择器、真实页面点击或录入逻辑。
- 权限绕过：未发现前端绕过后端权限进行真实授权判断；前端 README、store 和路由守卫均说明阶段0权限仅为展示占位。
- 财务越权：未发现 RPA 或供应商访问财务接口；财务 health 接口使用 `IsFinanceUser`。
- 供应商越权：阶段0仅为 mock 页面和接口映射，供应商路径规划为 `/api/external/*`；未发现供应商访问财务、销售或完整商品主数据的真实接口实现。
- 数据层越界：未发现 `rpa-agent/` 中存在 MySQL、Redis 或其他数据层连接配置。

## 6. 安全风险

扫描范围：
- `backend/`
- `frontend/`
- `rpa-agent/`
- `docs/00_stage0/`
- `docs/04_rpa/`
- `.env.example`
- `docker-compose.yml`

命中项与判断：
- `.env.example` 中 `change-me-db-password`、`change-me-root-password`、Redis/MySQL 示例地址为示例值，不构成 P0。
- `rpa-agent/.env.example` 中 `RPA_AGENT_TOKEN=change-me-rpa-token`、`BIGSELLER_LOGIN_URL=https://example.com/bigseller-login` 为示例值，不构成 P0。
- `backend/tests/` 中 `test-password`、`not-a-real-secret`、`change-me-placeholder`、`test-token-hash` 为测试占位值，不构成 P0。
- `backend/apps/integrations/models.py` 中 `api_key_encrypted`、`api_secret_encrypted` 为字段名，不是真实密钥。
- `backend/apps/rpa/models.py` 中 `token_hash`、`credential_ref` 为字段名或引用字段，不是真实 Token。

判断结果：
- 未发现真实 `.env`。
- 未发现真实账号密码。
- 未发现真实 Token。
- 未发现真实 API Key。
- 未发现真实数据库密码。
- 未发现真实 Cookie 或 Session。
- 未发现真实银行账号、账单、流水或财务数据。

## 7. 模块审核明细

| 模块 | 结论 | 证据 | 备注 |
|---|---|---|---|
| API边界 | PASS | `backend/apps/integrations/models.py`、`backend/apps/integrations/views.py`、`docs/00_stage0/frontend_api_mapping.md` | 同步类型限定为销售、库存、入库、发货、账单、取款等数据类；未发现页面操作或自动改价逻辑 |
| RPA边界 | PASS | `backend/apps/rpa/views.py`、`backend/apps/rpa/urls.py`、`docs/04_rpa/rpa_api_protocol.md`、`rpa-agent/README.md` | RPA 后端接口受 `IsRPAAgent` 保护；文档明确禁止访问财务接口、`/admin/` 和数据层 |
| 权限边界 | PASS | `backend/apps/permissions/`、`backend/apps/accounts/models.py`、`frontend/src/stores/auth.js`、`frontend/src/router/index.js` | 后端区分 internal/external/rpa；前端权限仅展示占位 |
| 供应商边界 | PASS | `backend/apps/accounts/models.py`、`docs/00_stage0/frontend_api_mapping.md`、`frontend/src/api/suppliers.js` | `ExternalUserProfile` 预留 `supplier_id`；供应商接口规划为 `/api/external/*` |
| 财务边界 | PASS | `backend/apps/finance/views.py`、`backend/apps/permissions/services.py`、`frontend/src/api/finance.js` | 财务接口独立 `/api/finance/*`，且使用 `IsFinanceUser` |
| 前后端接口路径一致性 | PASS_WITH_P2 | `backend/config/urls.py`、`backend/apps/*/urls.py`、`docs/00_stage0/frontend_api_mapping.md` | 主路径边界清晰；RPA result/complete/fail 口径建议统一 |
| 多租户与数据隔离 | PASS | `backend/apps/accounts/`、`backend/apps/permissions/`、`backend/apps/rpa/`、`backend/apps/integrations/`、`backend/apps/audit/`、`backend/apps/files/` | 核心模型已具备 `tenant` 外键或 `tenant_id` 索引意识 |
| 安全与越界扫描 | PASS | `rg` 扫描结果、`.env.example`、`rpa-agent/.env.example` | 命中均为示例值、字段名、测试占位或禁止项说明 |

## 8. P0问题

无。

## 9. P1问题

无。

## 10. P2问题

### AR0-005-P2-001 RPA截图提交端点在后端占位中尚未独立列出

- 问题描述：`docs/04_rpa/rpa_api_protocol.md` 已列出 `POST /api/rpa/tasks/{id}/screenshots/` 或 `screenshot_url` 占位规则；当前 `backend/apps/rpa/urls.py` 尚未提供独立 `screenshots` 占位端点。
- 影响判断：阶段0文档已说明可通过 `logs/result` 的截图字段占位，未构成 P1；阶段1实现前建议统一为独立截图端点或明确继续使用 `logs/result`。
- 责任人：开发A

### AR0-005-P2-002 RPA结果回写路径在接口清单与最新协议中口径不完全一致

- 问题描述：`docs/00_stage0/frontend_api_mapping.md` 的 RPA Agent 示例仍包含 `/api/rpa/tasks/{id}/result/`，而最新协议和后端占位使用 `/api/rpa/tasks/{id}/complete/` 与 `/api/rpa/tasks/{id}/fail/`。
- 影响判断：该路径位于阶段0接口清单说明区，未发现真实调用代码，不构成 P1。
- 责任人：架构人员

## 11. 整改任务建议

| 编号 | 等级 | 问题描述 | 责任人 | 涉及目录 | 整改要求 | 验收标准 |
|---|---|---|---|---|---|---|
| AR0-005-P2-001 | P2 | RPA截图提交端点在后端占位中尚未独立列出 | 开发A | `backend/apps/rpa/`、`docs/04_rpa/` | 阶段1接口实现前明确是否新增 `POST /api/rpa/tasks/{id}/screenshots/`，或正式采用 `logs/result` 中 `screenshot_url`、`screenshots` 字段 | 后端路由、RPA协议、样例 result、测试用例对截图提交方式保持一致 |
| AR0-005-P2-002 | P2 | RPA结果回写路径在接口清单与最新协议中口径不完全一致 | 架构人员 | `docs/00_stage0/frontend_api_mapping.md`、`docs/04_rpa/` | 将 `/api/rpa/tasks/{id}/result/` 与 `/complete/`、`/fail/` 的关系统一说明 | 接口清单、RPA协议、后端占位路由不再出现互相矛盾的结果回写路径 |

## 12. 阶段1准入建议

1. 允许进入阶段1。
2. 允许正式开发业务接口，但必须继续遵守 `/api/internal/*`、`/api/external/*`、`/api/rpa/*`、`/api/finance/*`、`/api/report/*` 的路径边界。
3. 允许正式开发 RPA 执行逻辑前的后端任务协议，但 RPA Agent 必须只能访问 `/api/rpa/*`，不得访问财务接口、内部财务接口、`/admin/`，不得直连 MySQL/Redis。
4. 阶段1实现供应商接口时，必须按 `tenant_id + supplier_id` 做数据过滤，并增加越权测试。
5. 阶段1实现财务接口时，必须继续使用独立财务权限码或财务角色授权，并增加普通 internal、external、rpa 的拒绝测试。
6. 阶段1实现高风险 RPA 任务时，改价、清仓、补货、上下架必须由后端审批后生成任务，RPA 只执行任务并回写执行结果。
7. 阶段1接入真实平台前，必须完成密钥托管、脱敏日志、配置隔离、审计追踪和生产环境网络隔离方案。

