# V2.44.135 内部系统只读数据接口菜单候选登记

## 登记结论

- 版本：`V2.44.135`
- 登记日期：`2026-09-21`
- 本次修订：菜单及页面用户名称由“知识库数据接口”统一调整为“内部系统数据接口”；知识库作为只读调用方之一。
- 状态：已登记候选，未形成干净候选提交，未部署。
- 直接父基线：`V2.44.134` / `v2.44.134-deployed` / `7a7581cf5c928cb49bd7627f5122086f9155cb2e`。
- 版本占用复核：登记时未发现 `V2.44.135` 文档或 `v2.44.135*` 标签。
- 发布边界：本记录不创建 deployed 标签、不合并主线、不触发虚拟机或阿里云部署。

## 候选目标

在“API数据接入”下增加唯一的“内部系统数据接口”菜单入口，用于统一承载知识库项目及其他内部系统的只读数据访问边界。本版本仅增加前端管理入口、受保护路由、只读原则页面和回归测试，不新增对外业务 API、服务凭据或数据库模型。

## 不可放宽的边界

- 知识库及其他内部调用系统对本接口均只读，只允许 `GET`、`HEAD` 和 `OPTIONS`。
- `POST`、`PUT`、`PATCH` 和 `DELETE` 必须在路由层和权限层双重拒绝。
- 不开放回写、导入、审批、发布、回滚、任务触发、webhook、RPA、消息队列或数据库直连旁路。
- 知识库产生的索引、切片、向量、摘要、标签和评分不回写 SaaS 系统。
- 本系统可记录独立访问审计，但读取不得修改被读业务对象的任何字段。

## 能力状态

- 已具备：菜单入口、受保护路由、只读边界说明、数据合同说明、安全要求说明和实施状态展示。
- 尚未具备：统一只读 API、独立服务身份、凭据生命周期、资源/字段/IP 白名单、限流和真实调用审计。
- 对外口径：本候选不得标记为“API 已上线”，不得发放生产凭据，不得用于知识库或其他内部系统的真实数据拉取。

## 精确增量范围

| 文件 | 候选增量 |
| --- | --- |
| `frontend/src/router/menu.js` | 在 API 数据接入下增加菜单，并向 `routeCapabilities` 增加 internal + `config.system.manage` + `config.view` 保护项 |
| `frontend/src/router/index.js` | 惰加载页面并注册 `/integrations/ai-open-api` |
| `frontend/src/views/integrations/AIExternalApiSettings.vue` | 新增只读边界、数据合同、安全要求和实施状态页；不包含输入框、保存按钮或凭据创建操作 |
| `frontend/tests/knowledge-base-api-menu.spec.js` | 新增菜单唯一性、双权限、内部用户限制和无回写控件合同测试 |
| `frontend/tests/v24433-menu-baseline.spec.js` | 更新当前菜单总数基线 |
| `docs/01_architecture/external_ai_api_menu_implementation.md` | 记录知识库项目边界、只读红线和后续 API 实施要求 |
| `docs/00_stage0/review/v244135_knowledge_base_api_ui_capability_verification.md` | 记录浏览器界面、权限合同及实际能力缺口验证 |

`menu.js`、`index.js` 和菜单基线测试在当前工作树已包含其他未登记改动。形成候选时必须从 `v2.44.134-deployed` 创建干净工作树，仅重放上表指定的功能片段，不得整体提交当前混合工作树。

## 当前验证证据（菜单更名后）

- 定向前端回归：`frontend/tests/knowledge-base-api-menu.spec.js`，3/3 通过。
- `npm run build`：通过。
- Playwright 真实浏览器验证：“内部系统数据接口”菜单、面包屑、页面标题、只读边界和四个页签正常。
- 浏览器截图：`frontend/output/playwright/internal-system-data-api-renamed.png`。
- 浏览器控制台：仅 `favicon.ico` 404，属于非阻断静态资源问题。
- 后端代码核验：未发现 `/api/internal-readonly/v1/` 或等价的统一只读接口实现。
- `git diff --check`：通过。
- 数据库迁移：无。
- 后端业务改动：无。

## 当前候选阻断

当前工作分支 `codex/v24459-api-production-readiness` 的 `HEAD` 为 `9ff4426d9e09c51e8bf18f55970aee99390445d3`，相对 `origin/main` 落后 96 个提交且存在大量其他在制改动。因此本次只完成版本号与范围登记，不将当前分支视为可发布候选。

## 形成正式候选的前置条件

1. 从 `v2.44.134-deployed` 创建干净工作树。
2. 只重放本文“精确增量范围”，解决主线菜单数量和路由结构差异。
3. 重新执行相关前端回归、完整前端测试和生产构建。
4. 核对候选 diff 不包含知识库回写、后端 API、凭据或数据库迁移。
5. 形成单一审核提交/PR，通过 CI 后才能进入虚拟机发布审批。
6. 只有受控虚拟机发布、部署后验收和双账本完成后，才能创建 `v2.44.135-deployed`。

## 回滚边界

本版本无数据库迁移和业务数据写入。如候选页面或导航发生回归，回滚到 `V2.44.134` 的不可变前端镜像；不执行数据库反向迁移，不覆盖业务数据。
