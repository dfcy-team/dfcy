# AR0-002 开发A后端底座审核报告

## 1. 审核对象

- 项目根目录：`saas-collab-system/`
- 审核范围：`saas-collab-system/backend/`、`docker-compose.yml`、`.env.example`、后端相关 README 与测试文件
- 审核时间：2026-07-08
- 审核人员：系统架构需求拆分和核实人员

本次审核只生成报告，不修改 `backend/`、`frontend/`、`rpa-agent/`、`docker-compose.yml`、`.env.example`、`requirements.txt`、业务代码、配置代码或数据库迁移文件。

## 2. 审核结论

结论：`CONDITIONAL_PASS`

判断依据：

- 未发现 P0 问题。
- 存在 P1 问题，阶段1开始前必须整改。
- 后端底座已具备 Django + DRF、租户、账号、权限、RPA任务、API同步、Celery/Redis、审计附件、认证接口、统一响应工具、Docker Compose 和测试框架基础。

阶段1准入判断：暂不建议直接进入阶段1。建议先完成 P1 整改并复审。

## 3. 已完成项

### Django工程结构

- 已存在 `backend/manage.py`。
- 已存在 `backend/config/`。
- 已存在 `backend/config/urls.py`。
- 已存在 `backend/config/wsgi.py`。
- 已存在 `backend/config/asgi.py`。
- 已存在 `backend/config/settings/`。
- 已存在 `backend/config/settings/base.py`、`dev.py`、`prod.py`。
- 已存在 `backend/requirements.txt`。
- 已存在 `backend/README.md`。
- settings 已拆分为 `base/dev/prod`。
- 敏感配置通过环境变量读取。
- 已配置 Django REST Framework。
- 已预留 CORS 配置。

### 基础App目录

- 已存在 `backend/apps/common/`。
- 已存在 `backend/apps/tenants/`。
- 已存在 `backend/apps/accounts/`。
- 已存在 `backend/apps/permissions/`。
- 已存在 `backend/apps/audit/`。
- 已存在 `backend/apps/files/`。
- 已存在 `backend/apps/rpa/`。
- 已存在 `backend/apps/integrations/`。
- 已存在 `backend/apps/finance/`。
- 已存在 `backend/apps/reports/`。
- 未发现前端代码或 RPA Agent 脚本放入 `backend/`。

### SaaS租户与账号

- 已存在 `Tenant`、`Department`。
- 已存在自定义用户模型 `CustomUser`，并通过 `AUTH_USER_MODEL = "accounts.CustomUser"` 启用。
- `CustomUser` 已绑定 `tenant`。
- `CustomUser.user_type` 已区分 `internal`、`external`、`rpa`。
- 已存在 `InternalUserProfile`、`ExternalUserProfile`。
- `ExternalUserProfile` 已预留 `supplier_id`、`company_name`、`contact_name`。

### 权限与数据范围

- 已存在 `Role`、`Permission`、`UserRole`、`DataScope`。
- `Role`、`UserRole`、`DataScope` 均绑定 `tenant`。
- `DataScope.scope_type` 已预留 `all`、`department`、`own`、`custom`。
- 已存在基础权限检查函数 `check_user_permission`。
- 已存在数据范围查询函数 `get_user_data_scope`。

### API路径分区

- 已预留 `/api/internal/`。
- 已预留 `/api/external/`。
- 已预留 `/api/rpa/`。
- 已预留 `/api/platform/`。
- 已预留 `/api/wechat/`。
- 已预留 `/api/feishu/`。
- 已预留 `/api/finance/`。
- 已预留 `/api/report/`。
- 已存在 `/admin/`。
- 已存在 health check 占位：internal、external、rpa、platform、finance、report、wechat、feishu。
- 已存在权限类占位：`IsInternalUser`、`IsExternalUser`、`IsRPAAgent`、`IsFinanceUser`。

### RPA任务中心

- 已存在 `RPATool`。
- 已存在 `RPAAgent`。
- 已存在 `RPATask`。
- 已存在 `RPATaskStepLog`。
- 已存在 `BigSellerAccount`。
- `RPATask` 已包含 `tenant`、`task_type`、`business_type`、`business_id`、`status`、`priority`、`payload`、`result`、`error_message`、`screenshot_url`、`retry_count`、`max_retry_count`、`claimed_by`、`claimed_at`、`started_at`、`finished_at`、`created_at`、`updated_at`。
- `RPATask` 状态已包含 `pending`、`claimed`、`running`、`success`、`failed`、`retrying`、`manual_required`、`cancelled`。
- `RPAAgent` 已包含 `tenant`、`name`、`token_hash`、`device_fingerprint`、`ip_whitelist`、`status`、`last_heartbeat_at`。
- `RPATaskStepLog` 已包含 `tenant`、`task`、`step_name`、`status`、`message`、`screenshot_url`、`created_at`。
- 已预留 RPA 任务领取、心跳、日志、完成、失败接口。
- 未发现真实 BigSeller 自动化操作代码。

### API数据接入中心

- 已存在 `APIIntegrationConfig`。
- 已存在 `APISyncTask`。
- 已存在 `APISyncLog`。
- 已存在 `APIDataQualityCheck`。
- 已预留平台枚举：`bigseller`、`shopee`、`tiktok`、`other`。
- 已预留同步类型：`sales_order`、`inventory`、`inbound`、`shipment`、`settlement_bill`、`withdrawal`。
- 已预留同步状态：`pending`、`running`、`success`、`partial_success`、`failed`、`retrying`。
- 已预留同步日志、失败重试、数据质量校验字段。
- 未发现真实 Shopee/TK/BigSeller API 调用。
- 未发现自动清仓、自动补货、自动改价逻辑。

### Celery / Redis

- 已存在 `backend/config/celery.py`。
- settings 已配置 `REDIS_URL`、`CELERY_BROKER_URL`、`CELERY_RESULT_BACKEND`。
- Redis URL 通过环境变量配置。
- 已存在 `debug_task` 占位。
- 未发现真实外部 API 任务。

### 日志审计与附件

- 已存在 `OperationLog`。
- 已存在 `ApprovalLog`。
- 已存在 `NotificationMessage`。
- 已存在 `DataImportLog`。
- 已存在 `SystemExceptionLog`。
- 已存在 `AttachmentFile`。
- `OperationLog` 已包含租户、用户、模块、动作、对象、前后数据、IP、User-Agent、创建时间。
- `AttachmentFile` 已包含租户、文件名、路径、类型、大小、上传人、业务类型、业务ID、私有标记、创建时间。
- settings 已配置 `MEDIA_URL`、`MEDIA_ROOT`。
- 未发现真实对象存储密钥。

### 认证接口

- 已存在 `POST /api/internal/auth/login/`。
- 已存在 `POST /api/internal/auth/refresh/`。
- 已存在 `GET /api/internal/auth/me/`。
- `/me` 返回 `user_id`、`username`、`email`、`user_type`、`tenant_id`、`roles`、`permissions`。
- 内部登录序列化器限制只有 `internal` 用户可登录。
- 外部供应商登录未越界实现。
- RPA Token 登录仅有占位类，未混用普通用户登录接口。

### 统一响应与错误码

- 已存在 `success_response`。
- 已存在 `error_response`。
- 已存在错误码：`OK`、`AUTH_REQUIRED`、`PERMISSION_DENIED`、`TENANT_REQUIRED`、`VALIDATION_ERROR`、`NOT_FOUND`、`RPA_AGENT_INVALID`、`API_SYNC_FAILED`、`INTERNAL_ERROR`。
- 已存在 DRF 异常处理器 `custom_exception_handler`。

### Docker Compose 与环境配置

- 项目根目录已存在 `docker-compose.yml`。
- 项目根目录已存在 `.env.example`。
- backend 已存在 `Dockerfile`。
- backend 已存在 `entrypoint.sh`。
- docker-compose 包含 `backend`、`mysql`、`redis`、`celery`、`celery-beat`。
- MySQL 镜像为 `mysql:8`。
- Redis 仅通过 `expose` 暴露给内部 Docker 网络。
- `.env.example` 仅包含 `change-me-*` 示例值。
- README 已说明生产环境 MySQL/Redis 不得暴露公网。
- `.gitignore` 已忽略 `docker-compose.override.yml`。

### 测试框架

- 已存在 `backend/pytest.ini`。
- 已存在 `backend/tests/`。
- 已存在 Django 配置、Tenant、CustomUser、API health、RPA任务模型、API同步模型等测试文件。
- 测试代码使用示例密码、placeholder token、placeholder secret，不依赖真实外部 API、真实 BigSeller 账号或真实密钥。

## 4. 缺失项

- 财务独立授权目前仅为 `IsFinanceUser` 占位，实际逻辑只判断内部用户，缺少独立财务权限码或独立授权策略。
- 统一响应工具和异常处理器已存在，但 health、auth、rpa placeholder 等接口仍直接返回 `Response({...})`，尚未统一使用标准响应结构。
- `settings/base.py` 中数据库默认值仍可回退到 SQLite；虽然 docker-compose 和 `.env.example` 使用 MySQL，但标准配置边界还不够强。
- RPA 任务接口已预留领取、心跳、日志、完成、失败，但未显式预留截图上传接口；模型仅有 `screenshot_url` 字段。
- RPA 接口目前只返回 placeholder，尚未绑定任务状态流转。
- 供应商只能访问自己的任务尚未形成接口级验证或测试。
- 当前执行环境无法运行 pytest，缺少可直接复现的本地测试环境。

## 5. 越界项

- 未发现阶段0之外的真实 BigSeller 自动化操作。
- 未发现真实 Shopee/TK/BigSeller API 接入。
- 未发现自动清仓、自动补货、自动改价逻辑。
- 未发现财务自动对账逻辑。
- 未发现前端代码放入 `backend/`。
- 未发现 RPA Agent 脚本放入 `backend/`。
- 未发现业务接口放到 `/admin/` 下。

## 6. 安全风险

本次扫描范围包括 `.env.example`、`docker-compose.yml`、`README.md`、`docs/`、`backend/`。

扫描结果：

- 未发现真实 `.env` 文件。
- 未发现真实数据库密码。
- 未发现真实 Django `SECRET_KEY`。
- 未发现真实 API Key / API Secret。
- 未发现真实 BigSeller 账号密码。
- 未发现真实 Shopee/TK Token。
- 未发现真实银行账号或财务流水数据。
- 命中的 `.env.example` 值均为 `change-me-*` 示例值。
- 命中的测试密码为 `test-password`、`not-a-real-secret` 等测试占位。
- 命中的 `token_hash`、`credential_ref`、`api_key_encrypted`、`api_secret_encrypted` 为字段名或 placeholder，不是真实密钥。

安全结论：未发现 P0 敏感信息风险。

## 7. 模块审核明细

| 模块 | 结论 | 说明 |
|---|---|---|
| Django工程结构 | PASS | 工程结构完整，settings 已拆分，DRF/CORS/环境变量配置已具备。 |
| 基础App目录 | PASS | app 命名清晰，目录完整，未发现前端或 RPA 脚本混入 backend。 |
| SaaS租户与账号 | PASS | Tenant、Department、自定义用户、内部/外部 profile 已具备，用户绑定 tenant。 |
| 权限与数据范围 | CONDITIONAL_PASS | RBAC 与 DataScope 已具备，但财务独立授权仍不足。 |
| API路径分区 | PASS | internal/external/rpa/platform/wechat/feishu/finance/report/admin 分区已存在。 |
| RPA任务中心 | CONDITIONAL_PASS | 模型和五个基础接口已存在，状态流转和截图上传协议需补充。 |
| API数据接入中心 | PASS | 同步框架、日志、重试、质量校验已预留，未接真实外部 API。 |
| Celery / Redis | PASS | Celery 配置、Redis 环境变量、debug_task 占位已存在。 |
| 日志审计与附件 | PASS | 操作日志、异常日志、审批、通知、导入、附件模型已具备。 |
| 认证接口 | PASS | internal login/refresh/me 已具备，外部/RPA 登录未越界实现。 |
| 统一响应与错误码 | CONDITIONAL_PASS | 工具和错误码已存在，但接口返回尚未统一落地。 |
| Docker Compose | PASS | backend/mysql/redis/celery/celery-beat 已配置，MySQL 8，Redis 内网。 |
| 测试框架 | CONDITIONAL_PASS | 测试文件完整，但当前执行环境缺少 pytest，未能实际运行。 |

## 8. P0问题

无。

## 9. P1问题

### P1-001 财务独立授权不足

- 问题描述：`IsFinanceUser` 当前只判断用户是内部用户，未体现财务独立授权。
- 责任人：开发A
- 涉及目录：`backend/apps/permissions/`、`backend/apps/finance/`
- 整改要求：补充财务权限码或独立授权策略占位，例如 `finance.view`、`finance.export`、`finance.reconcile`。
- 验收标准：财务接口进入真实实现前必须绑定独立权限判断，并有测试覆盖普通内部用户不可访问财务敏感接口。

### P1-002 统一响应结构未在现有接口中统一落地

- 问题描述：`success_response`、`error_response` 和异常处理器已存在，但 health、auth、rpa placeholder 等接口仍直接返回原生 `Response`。
- 责任人：开发A
- 涉及目录：`backend/apps/common/`、`backend/apps/*/views.py`
- 整改要求：制定统一响应落地策略，阶段1前至少确保新增业务接口统一使用标准结构。
- 验收标准：接口成功响应符合 `{success, code, message, data}`；失败响应由统一异常处理器输出；测试覆盖至少一条成功和一条失败响应。

### P1-003 数据库默认回退 SQLite 与 MySQL 标准边界不一致

- 问题描述：`settings/base.py` 默认数据库引擎为 SQLite；docker-compose 和 `.env.example` 使用 MySQL。
- 责任人：开发A
- 涉及目录：`backend/config/settings/`、`.env.example`、`backend/README.md`
- 整改要求：明确 MySQL 是标准运行目标，生产环境禁止 SQLite；如保留本地 SQLite，需在 dev 文档中明确仅限本地临时开发。
- 验收标准：生产配置拒绝 SQLite；README 明确 MySQL 为最终可信业务数据存储。

## 10. P2问题

### P2-001 RPA截图上传接口未显式预留

- 问题描述：模型有 `screenshot_url`，但 `/api/rpa/*` 中没有截图上传接口占位。
- 责任人：开发A
- 涉及目录：`backend/apps/rpa/`
- 整改要求：补充截图上传接口契约或占位接口。
- 验收标准：RPA Agent 可通过 `/api/rpa/*` 提交截图引用或文件占位，接口受 `IsRPAAgent` 保护。

### P2-002 RPA状态流转仍为 placeholder

- 问题描述：领取、心跳、日志、完成、失败接口返回 placeholder，未写入任务状态或日志。
- 责任人：开发A
- 涉及目录：`backend/apps/rpa/`
- 整改要求：补充状态机文档，明确阶段1每个接口对应的状态变更。
- 验收标准：文档覆盖 pending、claimed、running、success、failed、retrying、manual_required、cancelled 的流转规则。

### P2-003 供应商只能访问自己的任务尚未形成接口级验证

- 问题描述：`ExternalUserProfile` 有 `supplier_id`，但没有外部供应商任务接口或跨供应商访问测试。
- 责任人：开发A
- 涉及目录：`backend/apps/accounts/`、`backend/apps/permissions/`
- 整改要求：补充供应商数据范围规则和测试计划。
- 验收标准：外部供应商资源访问必须按 `tenant_id + supplier_id` 过滤，并有越权测试。

### P2-004 当前环境未能运行 pytest

- 问题描述：系统 PATH 中无 `python`/`py`；Codex 捆绑 Python 存在，但未安装 `pytest`。
- 责任人：开发A
- 涉及目录：`backend/README.md`、测试运行环境
- 整改要求：提供可复现测试环境，或通过 Docker/CI 跑通测试。
- 验收标准：新环境按 README 或 CI 能执行 `pytest` 并产出结果。

## 11. 整改任务建议

| 编号 | 等级 | 问题描述 | 责任人 | 涉及目录 | 整改要求 | 验收标准 |
|---|---|---|---|---|---|---|
| AR0-002-P1-001 | P1 | 财务独立授权不足 | 开发A | `backend/apps/permissions/`、`backend/apps/finance/` | 增加财务权限码或独立授权策略占位 | 普通内部用户不能访问财务敏感接口，测试覆盖权限拒绝 |
| AR0-002-P1-002 | P1 | 统一响应结构未在接口中统一落地 | 开发A | `backend/apps/common/`、`backend/apps/*/views.py` | 统一新增接口响应格式并补测试 | 成功/失败响应均符合 `{success, code, message, data}` |
| AR0-002-P1-003 | P1 | 默认数据库回退 SQLite 与 MySQL 标准边界不一致 | 开发A | `backend/config/settings/`、`.env.example`、`backend/README.md` | 明确 MySQL 为标准目标，生产禁止 SQLite | 生产配置拒绝 SQLite，README 明确 MySQL 是最终可信存储 |
| AR0-002-P2-001 | P2 | RPA截图上传接口未显式预留 | 开发A | `backend/apps/rpa/` | 增加截图上传接口契约或占位 | `/api/rpa/*` 下存在截图提交方案，受 RPA 权限保护 |
| AR0-002-P2-002 | P2 | RPA状态流转仍为 placeholder | 开发A | `backend/apps/rpa/` | 补充 RPA 状态机文档 | 状态流转规则完整覆盖所有预留状态 |
| AR0-002-P2-003 | P2 | 供应商任务访问缺少接口级验证 | 开发A | `backend/apps/accounts/`、`backend/apps/permissions/` | 补充供应商数据范围规则和测试计划 | 外部用户资源访问按 `tenant_id + supplier_id` 过滤 |
| AR0-002-P2-004 | P2 | 当前环境未能运行 pytest | 开发A | `backend/README.md`、测试运行环境 | 提供可复现测试环境或 CI | 能执行 `pytest` 并产出测试结果 |

## 12. 阶段1准入建议

阶段1准入建议：暂不允许直接进入阶段1。

原因：

- 当前无 P0，可继续整改。
- 存在 P1 问题，按规则结论为 `CONDITIONAL_PASS`。
- 阶段1开始前应至少完成财务独立授权、统一响应落地策略、MySQL 标准边界三项整改。

准入条件：

1. P1 问题全部关闭。
2. AR0-002 复审结论达到 `PASS`，或由架构人员确认 P1 已降级。
3. 至少提供一次后端测试运行结果，或说明 CI 已覆盖。

## AR0-002-P1-001 整改记录

- 整改任务：补充财务独立授权策略
- 责任人：开发A
- 整改状态：已完成代码侧阶段0占位整改，待测试环境验证

整改内容：

- 在权限模块预留财务权限码：
  - `finance.view`
  - `finance.export`
  - `finance.reconcile`
  - `finance.import`
  - `finance.exception.handle`
- 更新 `IsFinanceUser`，要求用户必须同时满足：
  - 已认证
  - `user_type == internal`
  - 具备财务权限码或财务角色
- 为 finance health 占位接口增加 `IsFinanceUser` 权限保护。
- 新增测试覆盖：
  - 普通 internal 用户访问财务接口被拒绝
  - 具备 `finance.view` 权限的 internal 用户可访问财务占位接口
  - external 用户不可访问
  - rpa 用户不可访问

未做内容：

- 未实现真实财务对账。
- 未写入真实银行账号、账单、流水数据。
- 未修改前端。
- 未修改 RPA。

## AR0-002-P1-002 整改记录

- 整改任务：统一现有接口响应结构
- 责任人：开发A
- 整改状态：已完成

整改内容：

- health check 接口统一使用 `success_response`：
  - `/api/internal/health/`
  - `/api/external/health/`
  - `/api/rpa/health/`
  - `/api/platform/health/`
  - `/api/wechat/health/`
  - `/api/feishu/health/`
  - `/api/finance/health/`
  - `/api/report/health/`
- `auth/me` 接口统一使用 `success_response`。
- RPA placeholder 接口统一使用 `success_response`。
- 外部登录和 RPA token 登录占位接口统一使用 `error_response`。
- 保留 DRF exception handler，不改 JWT 登录/刷新逻辑。
- 新增和更新测试覆盖：
  - health 成功响应标准结构
  - 未授权失败响应标准结构
  - RPA placeholder 响应标准结构

未做内容：

- 未实现真实业务接口。
- 未连接真实外部平台。
- 未修改前端。

## AR0-002-P1-003 整改记录

- 整改任务：明确 MySQL 标准运行边界，生产禁止 SQLite
- 责任人：开发A
- 整改状态：已完成

整改内容：

- 在 `prod.py` 中增加生产数据库校验：
  - 禁止 `django.db.backends.sqlite3`
  - 要求生产环境提供完整 `DB_*` MySQL 配置
- 在 `.env.example` 中明确 MySQL 为标准数据库目标，所有值均为示例值。
- 在 `backend/README.md` 中补充说明：
  - MySQL 8 是标准数据库
  - MySQL 是最终可信业务数据存储
  - 生产环境禁止 SQLite
  - MySQL/Redis 不得暴露公网
  - SQLite 如存在，仅限本地临时开发，不可用于 staging/prod
- 新增配置测试：
  - prod 配置拒绝 SQLite
  - prod 配置接受来自环境变量的 MySQL 配置

未做内容：

- 未写入真实数据库密码。
- 未提交真实 `.env`。
- 未修改前端。
- 未修改 RPA。
