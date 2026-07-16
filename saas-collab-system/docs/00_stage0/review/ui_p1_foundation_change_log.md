# UI-P1 基础认证与页面骨架变更记录

## 1. 任务信息

- 任务阶段：UI-P1
- 实施分支：`feature/ui-p1-foundation-auth-layout`
- 实施日期：2026-07-16
- 目标：落实真实登录会话、后端可信角色菜单、统一页面骨架、完整状态组件和角色工作台。

## 2. 认证与会话

- 登录在 `VITE_USE_MOCK=false` 时调用 `/api/internal/auth/login/`，不再回退 Mock。
- 登录成功后调用 `/api/internal/auth/me/` 获取可信用户、租户、角色、权限和 `data_scope`。
- 请求层统一注入 Bearer access token。
- access token 失效时只允许一次受控 refresh；刷新失败立即清理会话并返回登录页。
- 会话使用 `sessionStorage`，关闭浏览器会话后失效；未写入 `localStorage`。
- 退出登录清除前端 access/refresh token 和可信用户上下文。
- 后端 `/auth/me/` 补充 `is_superuser` 和 `data_scope` 字段，前端不自行扩大权限。

## 3. 菜单与路由

- 新增统一菜单合同，依据后端 `user_type`、`roles`、`permissions`、`data_scope` 过滤入口。
- 路由守卫在真实模式下先恢复会话并调用 `/auth/me/`，未认证跳转登录，权限不足跳转 403 页面。
- RPA 管理菜单不模拟 Agent token，不调用 Agent 执行端点。
- 财务、报表、配置和治理入口均由对应权限码控制。

## 4. 页面骨架与状态

- 新增统一 `AppPage` 页面骨架：标题、说明、能力标签、边界提示、操作区和内容区。
- 新增统一 `AppState` 状态组件：loading、empty、error、forbidden、conflict、invalid、partial、offline。
- 新增 403 页面。
- 主布局包含桌面侧栏、移动抽屉、面包屑、环境标识、可信用户上下文和退出入口。
- 修复 Element Plus 按需样式遗漏，桌面侧栏宽度固定为 248px。

## 5. 角色工作台

- 工作台根据可信角色解析业务工作区，并显示认证、租户、数据范围和可用入口。
- 常用入口由权限过滤后的菜单生成。
- 待办与异常聚合接口未冻结前保持空状态，不展示虚构业务数字。
- 页面明确保留人工确认边界，不直接触发采购、改价、RPA 或资金动作。

## 6. 接口映射

- 更新 `docs/00_stage0/frontend_api_mapping.md`，记录 login、refresh、me 和工作台当前状态。
- 认证接口标记为“代码完成，待 Pilot 复验”，未误标为 connected。

## 7. 安全确认

- 未提交真实 `.env`。
- 未提交真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未启用自动采购、改价、清仓、停售、归档、真实 RPA 或资金操作。
- 前端菜单和路由仅用于用户体验，后端权限与 tenant/data_scope 校验仍为最终安全边界。

## 8. 待架构复审观察项

- 当前 refresh token 保存在 `sessionStorage`；生产准入前应专项评估 HttpOnly/Secure/SameSite Cookie 与 CSRF 方案。
- 当前退出为客户端会话清理；生产准入前应评估 refresh token 服务端撤销或黑名单机制。
- 本机补齐仓库已声明的 `mysqlclient 2.2.8` 后，全量后端测试通过；Pilot/Docker 环境仍需执行真实登录复验。
