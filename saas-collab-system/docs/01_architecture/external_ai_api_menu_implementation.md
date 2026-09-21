# 知识库 AI 数据接口实施与单菜单归集方案

## 1. 实施结论

在现有一级菜单“API数据接入”下新增且仅新增一个二级菜单“内部系统数据接口”。知识库项目及其他内部调用系统的服务身份、数据授权、接口文档和调用审计全部归集到该页面，不再拆分侧边栏菜单。

禁止直接把管理员账号或现有内部 JWT 交给外部 AI。新能力应使用独立服务身份、只读数据范围、可撤销凭据和完整审计。

### 1.1 系统边界

AI 能力位于独立的“知识库项目”，不在本 SaaS 协同系统内建设。两个项目的职责固定如下：

| 项目 | 责任 |
| --- | --- |
| SaaS 协同系统 | 作为权威数据源，提供受控的只读 API、租户隔离、字段脱敏、增量水位、限速和调用审计 |
| 知识库项目 | 调用 API，完成抽取、清洗、切分、向量化、索引、训练/RAG、训练数据版本和失败重试 |

知识库项目不直连本系统业务数据库，不共享人员账号，不把向量、切片、模型、提示词或训练任务写回本系统。两个项目仅通过 HTTPS API 和可追踪的服务身份集成。

### 1.2 只读红线

知识库对本系统是绝对只读消费方，不具有任何业务写入能力：

- 对外知识库凭据只允许 `GET`、`HEAD` 和 `OPTIONS`；任何 `POST`、`PUT`、`PATCH` 和 `DELETE` 在路由层和权限层双重拒绝。
- 不开放新增、修改、删除、审批、发布、回滚、导入、批量操作、任务触发或状态切换接口。
- 不允许通过 webhook、回调、消息队列、RPA、共享数据库账号或其他旁路向本系统写入。
- 知识库中的索引、标注、摘要、分类、评分和 AI 生成内容不回写本系统。
- 知识库读取时不得触发业务数据修改；如需记录访问，只允许由系统侧写入独立审计日志，不改变业务对象。
- 本系统管理员可在“内部系统数据接口”页面修改接入策略、撤销凭据或缩小授权；这是本系统内部管理行为，不是赋予调用方的写入权限。

## 2. 菜单与路由配置

```js
{
  path: '/integrations/ai-open-api',
  label: '内部系统数据接口',
  permissions: ['config.system.manage'],
  allPermissions: ['config.view'],
}
```

- 上级菜单：`API数据接入`
- 页面路由：`/integrations/ai-open-api`（为减少实现变更保留技术路径，用户文案使用“内部系统数据接口”）
- 页面组件：`frontend/src/views/integrations/AIExternalApiSettings.vue`
- 模块归属：沿用 `/integrations` 的 `api_integrations`，不新增模块映射。
- 路由能力：必须同步登记到 `routeCapabilities`；现有机制对未登记路由默认拒绝。

页面访问需同时具有 `config.system.manage` 和 `config.view`。页面内操作按钮继续使用现有权限：

| 操作 | 权限 |
| --- | --- |
| 查看配置、资源范围和审计 | `config.view` |
| 新建草稿、修改白名单、停用凭据 | `config.manage` |
| 审批发布 | `config.approve` |
| 回滚配置版本 | `config.rollback` |
| 进入页面及服务身份管理 | `config.system.manage` + `ALL scope` |

## 3. 单页归集内容

### 3.1 概览

展示且仅展示非敏感状态：

- 服务状态：未启用、待审批、已启用、已停用。
- 对外基础地址：虚拟机与阿里云分别显示，不显示内部 `8000` 端口。
- 当前发布版本、配置版本、最后审批人与发布时间。
- 已启用服务身份数、近24小时调用量、失败量和最后调用时间。
- 安全门状态：HTTPS、IP 白名单、速率限制、审计、凭据托管。

### 3.2 访问凭据

服务身份字段：

| 字段 | 要求 |
| --- | --- |
| 名称 | 必填，表示使用方或 AI 应用 |
| 租户 | 必填，不允许跨租户 |
| 用途说明 | 必填，用于审批和审计 |
| 凭据标识 | 可查看，不是密钥原文 |
| 密钥 | 创建或轮换后仅显示一次，服务端只保存哈希或凭据托管引用 |
| 到期时间 | 必填，不提供永久凭据 |
| 允许 IP/CIDR | 生产环境必填 |
| 限速 | 按分钟和按日配置 |
| 状态 | 草稿、待审批、启用、停用、过期、撤销 |

支持的操作：新建草稿、提交审批、启用、轮换、停用和撤销。任何列表、详情和审计响应都不得返回密钥原文。

### 3.3 数据授权

采用“资源 + 动作 + 数据范围”三层授权：

- 资源：商品、采购、供应商、仓储、销售、财务、报表等，默认全部未勾选。
- 动作：永久只支持 `read` 和 `list`，禁止 `create/update/delete/approve/publish/rollback/trigger/import/export-all`；这不是仅限第一期的临时约束。
- 范围：固定租户，可再限制店铺、仓库、供应商、市场或数据时间范围。
- 字段：默认遮蔽个人信息、凭据、内部备注、成本敏感字段和未授权财务字段。
- 数量：必须分页，限制单页数量、总导出量和查询时间跨度。

授权变更必须生成新配置版本，经审批后生效，不允许直接修改已发布版本。

### 3.4 接口文档

- 显示 OpenAPI 3.x 文档的版本、生成时间和下载入口。
- 只展示当前服务身份可访问的资源，不向其暴露管理接口。
- 提供健康检查、鉴权方式、分页、错误码、限速返回头和最小调用示例。
- 不在文档或示例中写入真实密钥、生产用户名或业务数据。

数据模型应为知识库同步提供稳定字段：`resource_type`、`resource_id`、`tenant_id`、`updated_at`、`deleted_at`、`version`、`content_hash` 和 `next_cursor`。这些字段用于增量同步、幂等更新和删除传播，但切片与向量数据仍由知识库项目管理。

### 3.5 调用审计

支持按时间、服务身份、资源、响应码、请求 ID 和来源 IP 查询。最少记录：

- 服务身份 ID、租户 ID、凭据指纹（非原文）。
- 请求 ID、路由模板、HTTP 方法、响应码、耗时和返回行数。
- 来源 IP、客户端标识、限速结果和拒绝原因。
- 授权规则版本和接口版本。

审计记录不保存 Authorization 头、密钥、完整请求体或完整业务响应。

## 4. 后端接口规划

管理端使用现有内部鉴权：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/internal/integrations/ai-open-api/overview/` | 概览与安全门状态 |
| GET/POST | `/api/internal/integrations/ai-open-api/clients/` | 查询或新建服务身份草稿 |
| GET/PATCH | `/api/internal/integrations/ai-open-api/clients/{id}/` | 查看或修改未发布配置 |
| POST | `/api/internal/integrations/ai-open-api/clients/{id}/rotate/` | 轮换凭据，新值只返回一次 |
| POST | `/api/internal/integrations/ai-open-api/clients/{id}/revoke/` | 撤销凭据 |
| GET/PUT | `/api/internal/integrations/ai-open-api/clients/{id}/grants/` | 查看或编辑授权草稿 |
| GET | `/api/internal/integrations/ai-open-api/audits/` | 分页查询调用审计 |
| GET | `/api/internal/integrations/ai-open-api/openapi/` | 获取经裁剪的 OpenAPI 文档 |

对外读取端点建议使用独立版本前缀 `/api/external/ai/v1/`，不与内部管理路由共用身份或权限类。该前缀永久只注册经审批的 GET/HEAD/OPTIONS 路由，不得挂载任何业务写入 view/action。

## 5. 实施步骤

1. 与知识库项目冻结第一期数据合同。明确允许读取的业务对象、字段、租户范围、增量水位、删除传播、分页上限和禁止字段。
2. 实现独立身份。新增服务身份、凭据指纹/托管引用、过期、撤销和 IP 白名单；不复用人员密码及管理员 JWT。
3. 实现授权模型。将服务身份绑定固定租户、只读资源、数据范围和字段遮蔽规则，所有查询默认拒绝。
4. 实现管理 API。复用现有 `production-settings` 的版本创建、审批、发布和回滚模式，且强制 `ALL scope`。
5. 实现外部只读 API。独立鉴权中间件、资源白名单、分页、超时、限速和统一错误码；在进入业务 view 前就拒绝非安全 HTTP 方法。
6. 实现审计。鉴权成功或失败、越权、限速、撤销后调用和配置变更都必须留痕。
7. 生成 OpenAPI 文档。仅包含对外白名单路由，文档与实际路由在 CI 中做一致性检查。
8. 实现单菜单页面。新增菜单、路由白名单、页面组件和 API adapter，五个标签页共用一个路由。
9. 安全与回归测试。覆盖未鉴权、过期、撤销、错误 IP、跨租户、越权字段、超限和审计脱敏。
10. 先发布虚拟机。使用测试服务身份完成只读冒烟、撤销验证、审计核对和回滚演练。
11. 再发布阿里云。不复制虚拟机凭据和环境文件；在云端独立生成凭据、白名单和限速配置，后端 `8000` 端口继续不对公网开放。
12. 生产验收。从公网 HTTPS 验证健康、合法读取、越权拒绝、限速、凭据撤销和审计闭环。

## 6. 最小改动清单

前端：

- `frontend/src/router/menu.js`：增加单菜单和 `routeCapabilities`。
- `frontend/src/router/index.js`：增加惰加载组件与子路由。
- `frontend/src/views/integrations/AIExternalApiSettings.vue`：五标签页归集界面。
- `frontend/src/api/integrations.js`：增加管理 API adapter。
- `frontend/tests/ai-open-api-settings.spec.js`：菜单、路由、权限和脱敏回归。

后端：

- `backend/apps/integrations/urls_internal.py`：注册管理路由。
- `backend/apps/integrations/ai_open_api.py`：管理、审批、凭据和授权服务。
- `backend/apps/integrations/urls_external_ai.py`：独立对外 v1 路由。
- `backend/apps/integrations/ai_api_authentication.py`：服务身份鉴权、白名单与撤销检查。
- `backend/apps/integrations/models.py` 及迁移：服务身份、授权版本、凭据引用和调用审计。
- `backend/apps/permissions/catalog.py` 及迁移：只有新操作无法由现有 `config.*` 表达时才新增权限编码。
- `backend/tests/`：鉴权、租户隔离、资源白名单、字段遮蔽、限速、撤销和审计测试。

## 7. 验收标准

- 侧边栏只新增一个“内部系统数据接口”菜单，所有数据提供端配置都在单页标签中完成。
- 无权限用户不见菜单，直接输入路由也被拒绝；后端独立再做权限判定。
- 知识库不能通过管理员 JWT 或人员密码接入。
- 使用知识库凭据向任何对外路由发送 `POST/PUT/PATCH/DELETE` 都被拒绝，且业务表数据及业务审计字段保持不变。
- 不存在可供知识库调用的 webhook、任务触发、导入、审批或回写路由。
- 新建或轮换密钥只显示一次，之后任何页面、API 和日志都不可恢复原文。
- 所有对外数据查询都限定租户、资源、动作和字段；默认拒绝未配置内容。
- 撤销凭据后立即无法调用，且生成审计记录。
- OpenAPI 文档与实际对外路由一致，不包含内部管理端点。
- 虚拟机与阿里云使用同版本功能和独立凭据；阿里云只通过 HTTPS 443 提供对外入口。
- 知识库项目能通过游标断点续传，重复拉取不产生重复数据，源系统删除或停用能通过 `deleted_at`/删除事件同步。
- SaaS 项目中不出现向量库、切片、嵌入模型、训练任务或提示词管理功能。
- 连续读取同一资源不改变其 `updated_at`、版本、状态、归属或任何业务字段。
- 相关单元、API、权限、安全和前端路由回归测试通过。
