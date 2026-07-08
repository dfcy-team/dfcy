# AR0-006 全局安全与密钥审核报告

## 1. 审核对象
- 项目根目录：`saas-collab-system/`
- 审核范围：`backend/`、`frontend/`、`rpa-agent/`、`docs/`、`.env.example`、`.gitignore`、`docker-compose.yml`、`README.md`、`backend/requirements.txt`、`frontend/package.json`
- 审核时间：2026-07-08
- 审核人员：系统架构需求拆分和核实人员
- 审核依据：
  - `docs/00_stage0/stage0_file_scope.md`
  - `docs/00_stage0/review/ar0_002_r1_backend_base_recheck.md`
  - `docs/00_stage0/review/ar0_003_r1_frontend_rpa_recheck.md`
  - `docs/00_stage0/review/ar0_004_r1_rpa_bigseller_recheck.md`
  - `docs/00_stage0/review/ar0_005_system_boundary_review.md`
  - `.gitignore`
  - `.env.example`
  - `docker-compose.yml`
  - `backend/`
  - `frontend/`
  - `rpa-agent/`
  - `docs/`

## 2. 审核结论

PASS

判断说明：
- 未发现 P0 安全问题。
- 未发现 P1 安全问题。
- 发现 1 个 P2 问题：`.gitignore` 中 `rpa-agent/cache/`、`rpa-agent/downloads/` 会覆盖对应目录下的 `.gitkeep` 保留规则。

## 3. 已完成项

- 文件范围：未发现真实 `.env`、`.env.local`、`.env.production`、`.env.prod`、私钥、证书、SQLite 数据库、真实日志、真实截图、真实导出文件、真实平台页面快照或真实财务导入文件。
- 密钥扫描：未发现真实 Token、JWT、API Key、Cookie、Session、私钥、数据库密码、平台账号、银行账号或流水号。
- 环境变量与配置：根 `.env.example`、`frontend/.env.example`、`rpa-agent/.env.example` 均使用 `change-me`、`demo`、`example.com`、localhost 等示例值。
- 后端安全：`SECRET_KEY`、数据库、Redis 配置均来自环境变量；生产配置禁止 SQLite；`APIIntegrationConfig` 使用 `api_key_encrypted`、`api_secret_encrypted` 字段；`RPAAgent` 使用 `token_hash`；`BigSellerAccount` 未存明文密码。
- 前端安全：未发现硬编码真实 Token、账号密码、真实外部平台 API 地址或真实后端公网地址；Mock 用户为 `mock-*` 示例；前端权限明确为展示占位。
- RPA安全：未发现真实 BigSeller 账号、密码、Cookie、Session、真实选择器、真实浏览器自动化脚本、真实改价脚本或 MySQL/Redis 连接配置。
- 财务与供应商安全：财务接口使用 `/api/finance/*` 且受 `IsFinanceUser` 保护；供应商页面规划到 `/api/external/*`；未发现真实银行账号、账单、流水、利润数据或财务导入文件。
- `.gitignore`：已覆盖 `.env`、`.env.*`、密钥证书、Python/Django 临时文件、Node/Vue 临时文件、虚拟环境、日志、IDE、系统文件、Docker override、RPA 截图和日志运行产物。
- 阶段0越界：未发现真实平台 API 接入、真实 BigSeller 自动化脚本、真实页面点击脚本、真实价格修改、自动清仓、自动补货、财务自动对账、真实微信/飞书接入、真实银行接口或真实对象存储密钥。

## 4. 缺失项

- `.gitignore` 对 `rpa-agent/cache/.gitkeep`、`rpa-agent/downloads/.gitkeep` 的保留规则不够精确，当前会被 `rpa-agent/cache/`、`rpa-agent/downloads/` 目录忽略规则覆盖。
- 本地存在 `frontend/dist/`、`backend/.pytest_cache/` 等运行/构建产物，但已被 `.gitignore` 或 `backend/.gitignore` 覆盖，未纳入 P0/P1。

## 5. 越界项

- 真实平台接入：未发现。
- 真实自动化：未发现。
- 真实财务数据：未发现。
- 真实凭据：未发现。
- RPA越界访问财务接口、`/admin/` 或数据层：未发现。
- 前端绕过后端真实权限判断：未发现。
- 供应商越权访问内部后台或财务接口：未发现。

## 6. 安全扫描结果

扫描范围：
- `backend/`
- `frontend/`
- `rpa-agent/`
- `docs/`
- `.env.example`
- `.gitignore`
- `docker-compose.yml`
- `README.md`

命中项与判断：
- `backend/tests/` 中 `test-password`、`not-a-real-secret`、`test-token-hash`、`sha256-placeholder`、`change-me-placeholder` 为测试占位值，不构成 P0。
- `frontend/src/mock/auth.js` 中 `mock-session-only` 为 Mock 会话示例，不构成 P0。
- `.env.example` 中 `DJANGO_SECRET_KEY=change-me-dev-only`、`DB_PASSWORD=change-me-db-password`、`MYSQL_ROOT_PASSWORD=change-me-root-password` 为示例值，不构成 P0。
- `rpa-agent/.env.example` 中 `RPA_AGENT_TOKEN=change-me-rpa-token`、`BIGSELLER_LOGIN_URL=https://example.com/bigseller-login` 为示例值，不构成 P0。
- `backend/apps/integrations/models.py` 中 `api_key_encrypted`、`api_secret_encrypted` 为字段名，不是真实密钥。
- `backend/apps/rpa/models.py` 中 `token_hash`、`credential_ref` 为字段名或引用字段，不是真实 Token。
- 文档中出现的 BigSeller、Shopee、TikTok/TK、Token、密码、银行、财务等内容均为边界说明、禁止说明或 demo/placeholder 示例，不构成 P0。
- `docker-compose.yml` 中 MySQL 端口绑定为 `127.0.0.1:3306:3306`，Redis 使用 `expose`，且文件末尾明确 MySQL 仅限本地开发、生产不得公网暴露，不构成 P0。

文件范围结果：
- 未发现 `.env`、`.env.local`、`.env.production`、`.env.prod`。
- 未发现 `*.pem`、`*.key`、`*.crt`、`*.p12`、`*.pfx`、`id_rsa`、`id_ed25519`。
- 未发现 `*.sqlite3`、`db.sqlite3`。
- RPA 运行目录 `screenshots/`、`logs/`、`cache/`、`downloads/` 仅发现 `.gitkeep`，未发现真实运行产物。

## 7. 模块审核明细

| 模块 | 结论 | 证据 | 备注 |
|---|---|---|---|
| 文件范围 | PASS | 文件枚举、`.gitignore`、`rpa-agent/` 运行目录检查 | 未发现真实 `.env`、私钥证书、SQLite、真实日志、真实截图、真实导出或财务导入文件 |
| 密钥关键词扫描 | PASS | `rg` 扫描结果 | 命中项均为示例值、测试值、字段名或文档禁止说明 |
| 环境变量与配置 | PASS | `.env.example`、`frontend/.env.example`、`rpa-agent/.env.example`、`backend/config/settings/`、`docker-compose.yml` | 生产禁止 SQLite；MySQL/Redis 未公网暴露；RPA env 无 MySQL/Redis 字段 |
| 后端安全 | PASS | `backend/config/settings/`、`backend/apps/accounts/`、`backend/apps/permissions/`、`backend/apps/finance/`、`backend/apps/rpa/`、`backend/apps/integrations/`、`backend/apps/audit/`、`backend/apps/files/` | 配置来自环境变量；财务独立授权；RPA token 使用 hash；平台密钥字段为 encrypted 占位 |
| 前端安全 | PASS | `frontend/src/`、`frontend/.env.example`、`frontend/README.md` | 未发现真实 Token、账号密码、真实平台 API 地址；权限仅展示占位 |
| RPA安全 | PASS | `rpa-agent/`、`docs/04_rpa/` | 仅文档和 JSON 样例；无真实脚本、真实选择器、真实平台凭据、数据库连接配置 |
| 财务与供应商安全 | PASS | `backend/apps/finance/`、`backend/apps/accounts/`、`backend/apps/permissions/`、`frontend/src/views/finance/`、`frontend/src/views/suppliers/`、`docs/00_stage0/frontend_api_mapping.md` | 财务接口独立授权；供应商页面规划为 `/api/external/*`；未发现真实财务数据 |
| .gitignore | PASS_WITH_P2 | `.gitignore`、`git check-ignore -v` | 关键密钥和运行产物规则齐全；`cache/.gitkeep`、`downloads/.gitkeep` 被目录忽略规则覆盖 |
| 阶段0越界 | PASS | 全局扫描、AR0-002/003/004/005 复审报告 | 未发现真实平台接入、真实自动化、真实改价、自动清仓、自动补货、财务自动对账 |

## 8. P0问题

无。

## 9. P1问题

无。

## 10. P2问题

### AR0-006-P2-001 RPA cache/downloads 目录下 .gitkeep 被忽略

- 问题描述：`.gitignore` 中 `rpa-agent/cache/`、`rpa-agent/downloads/` 会忽略对应目录下的 `.gitkeep`。虽然全局存在 `!.gitkeep`，但当前 `git check-ignore -v` 显示 `rpa-agent/cache/.gitkeep`、`rpa-agent/downloads/.gitkeep` 仍被目录规则覆盖。
- 影响判断：不涉及真实密钥、真实运行产物或业务代码，不构成 P0/P1；但与“空目录使用 .gitkeep 保留”的阶段0目录规范不完全一致。
- 责任人：架构人员

## 11. 整改任务建议

| 编号 | 等级 | 问题描述 | 责任人 | 涉及目录 | 整改要求 | 验收标准 |
|---|---|---|---|---|---|---|
| AR0-006-P2-001 | P2 | RPA cache/downloads 目录下 `.gitkeep` 被 `.gitignore` 目录规则覆盖 | 架构人员 | `.gitignore`、`rpa-agent/cache/`、`rpa-agent/downloads/` | 后续可将忽略规则调整为忽略目录内容但保留 `.gitkeep`，例如对 cache/downloads 增加 `*` 规则和反向保留规则 | `git check-ignore -v rpa-agent/cache/.gitkeep rpa-agent/downloads/.gitkeep` 不再显示被忽略，且运行产物仍被忽略 |

## 12. 阶段1准入建议

1. 允许进入阶段1。
2. 当前未发现必须先处理的 P0/P1 安全问题。
3. 阶段1开发时必须继续遵守以下安全边界：
   - 不提交真实 `.env`、数据库密码、Django `SECRET_KEY`、API Key、API Secret、Token、Cookie、Session。
   - 不提交真实 BigSeller、Shopee、TK/TikTok 账号、密码、Token、店铺密钥或平台凭据。
   - 不提交真实银行账号、账单、流水、利润数据或财务导入文件。
   - RPA Agent 只能访问 `/api/rpa/*`，不得访问 `/api/finance/*`、`/api/internal/finance/*`、`/admin/`，不得直连 MySQL/Redis。
   - 前端不得硬编码真实 Token、真实账号密码、真实 API 地址，不得承载真实权限判断。
   - 后端不得硬编码生产数据库、Redis 或第三方平台密钥。
   - 真实平台接入前必须完成密钥托管、脱敏日志、审计追踪、环境隔离和生产网络隔离方案。
   - 高风险 RPA 任务必须由后端审批后生成，RPA 只执行并回写执行结果，不做业务判断。

