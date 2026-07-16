# UI-P1-ARCH-R1 架构复审报告

## 1. 复审对象

- 项目：`saas-collab-system/`
- 分支：`feature/ui-p1-foundation-auth-layout`
- 基线：`main@488a38c`
- 复审日期：2026-07-16
- 复审对象：当前工作树中的 UI-P1 认证、菜单、路由、页面骨架、状态组件、角色工作台、后端可信用户合同及测试。
- 复审性质：只审核，不修复；本次除本报告外未修改业务代码或既有文档。

当前 UI-P1 实现尚未形成独立提交，因此本结论仅对应复审时工作树快照。创建 PR 前必须固定提交 HEAD，并确认文件范围和测试结果未变化。

## 2. 复审结论

结论：**CONDITIONAL_PASS**。

- P0：无。
- P1：2项。
- P2：5项观察。

真实 JWT 登录、刷新接口、`/auth/me/`、客户端会话恢复、菜单过滤、403、退出、统一页面状态和角色工作台已形成可运行基础；但非公开路由仍存在未登记路径默认放行，按钮/动作权限尚未按后端 action permission 收敛。原 `UI-P0-P1-002` 未完全关闭，因此暂不允许 UI-P1 正式收尾。

## 3. 认证与会话

复审结果：**通过，附P2安全观察**。

- `VITE_USE_MOCK=false` 时，登录只调用 `POST /api/internal/auth/login/`，当前用户只调用 `GET /api/internal/auth/me/`，未发现认证接口静默回退 Mock。
- 请求拦截器统一添加 Bearer access token。
- 401只触发一个共享 `refreshPromise`，每个原请求最多重试一次；刷新失败清理会话并调用统一过期处理器。
- 登录成功先保存 token，再调用 `/auth/me/` 建立可信用户上下文；`/auth/me/` 失败会清理会话。
- 退出操作清理客户端会话并返回登录页。
- production/真实API模式默认 `currentUser=null`、`isAuthenticated=false`，未默认注入 Mock 登录用户。

独立本地 E2E 使用临时 SQLite 和测试用户完成：

1. 浏览器真实调用 login，成功进入工作台。
2. 页面显示后端返回的 finance 角色、tenant和 `own` data_scope。
3. refresh接口返回新 access token，新 token 可访问 `/auth/me/`。
4. 退出后回到 `/login`，再次访问受保护页面需要重新认证。

测试数据库位于系统临时目录，复审结束后已删除；未使用 Pilot、生产或真实业务凭据。

## 4. 可信用户合同

复审结果：**通过**。

`CurrentUserSerializer` 已返回：

- `user_id`
- `username`
- `email`
- `user_type`
- `tenant_id`
- `is_superuser`
- `roles`
- `permissions`
- `data_scope`

普通用户的角色、权限和 data_scope 均按当前 tenant 和 active role 查询。超级管理员显式返回 `is_superuser=true` 和 tenant内 `all` scope。后端测试覆盖内部用户登录、统一 `/me` 响应、超级管理员、未认证、external拒绝内部登录和refresh端点。

## 5. 角色菜单与路由

复审结果：**部分通过，存在P1**。

已通过：

- 菜单会按 `user_type`、`is_superuser` 和 permission过滤。
- finance、integrations、reports、config、analytics、alerts、replenishment等菜单使用后端权限码。
- 已登记且无权的路径会进入统一403页面。浏览器实测 finance用户访问 `/integrations/configs` 被重定向至 `/forbidden`。
- 页面明确声明前端菜单和路由仅改善体验，后端权限仍为最终边界。

未通过：

- `canAccessPath()` 在找不到菜单条目时返回 `true`。
- `router/index.js` 中存在多条未登记到菜单合同的非公开路径，例如 `/finance/imports`、`/finance/withdrawals`、`/finance/bank-receipts`、`/finance/reconciliation/exceptions`、`/integrations/api-sync`、`/settings/platform-risk`、`/settings/security-review`、`/suppliers/tasks` 和部分RPA治理路径。
- 浏览器实测仅具备 `finance.view` 的用户可直接打开 `/finance/imports`；该能力按后端合同应需要 `finance.import`。当前页面为占位且未泄露真实数据，因此定级P1而非P0。

## 6. 页面骨架与状态组件

复审结果：**通过，附P2语义观察**。

- `AppPage` 提供统一页头、标题、说明、能力状态、边界提示、操作区和内容区。
- `AppState` 覆盖 loading、empty、error、forbidden、conflict、invalid、partial、offline。
- 403、409、422、partial和offline已有统一状态映射和组件测试。
- Element Plus布局样式已正确加载，桌面侧栏宽度稳定为248px。
- 390px视口实测桌面侧栏隐藏、移动菜单显示、header无溢出，`scrollWidth=clientWidth=375`。

观察：`statusFromApiResponse()` 将所有404统一映射为empty，详情资源不存在与列表空数据尚未区分；工作台在真实模式下仅根据 `VITE_USE_MOCK=false` 显示“已连接”，未附最近联调时间或具体能力健康证据。

## 7. 角色工作台

复审结果：**通过**。

- 工作台依据可信 permissions解析finance、technical、management、operations或system工作区。
- 展示认证状态、tenant、data_scope和权限过滤后的入口数量。
- 常用入口由过滤后的菜单生成，不手写扩大入口。
- 聚合接口未冻结时显示空状态，未展示虚构待办、异常或经营数字。
- 页面明确补货、采购、改价、RPA和资金动作不得由工作台直接触发。

本地真实API模式实测 finance用户进入“财务工作台”，显示后端角色 `finance_reviewer`、tenant 1、data_scope `own`。

## 8. tenant、data_scope与权限边界

复审结果：**后端可信合同通过，前端动作级收敛存在P1**。

- 后端 `/auth/me/` 的角色、权限和scope均绑定当前tenant。
- external用户被内部登录端点拒绝；全量后端测试覆盖 internal/external/RPA/finance 等既有权限边界。
- 未发现前端调用 `/admin/` 或 RPA Agent claim、heartbeat、logs、screenshots、complete、fail执行端点。
- finance API仍位于 `/api/finance/*`，最终权限由后端独立校验。

未通过项：前端 `auth.hasPermission()` 除定义外未被页面动作使用。页面通常只按view权限进入，但管理动作未按更细权限隐藏或禁用。例如：

- `replenishment.view` 页面展示 accept/reject，后端要求 `replenishment.review`。
- `reports.view` 页面展示申请导出，后端要求 `reports.export`。
- `config.view` 页面展示提交审批，后续动作需要 `config.manage`/`config.approve`。
- alerts和finance的管理、导入、对账动作也尚未形成统一按钮权限合同。

后端仍会拒绝越权请求，因此未形成直接安全绕过；但不满足 UI-P1 的菜单/按钮/字段展示一致性验收。

## 9. 测试、构建与视觉证据

本次复审独立执行结果：

| 检查 | 结果 | 证据 |
|---|---|---|
| Django check | PASS | 0 issues |
| migration一致性 | PASS | No changes detected |
| 后端全量pytest | PASS | 252 passed，10.59s |
| 前端Vitest | PASS | 3 files，48 passed |
| UI-P1专项测试 | PASS | 15 passed |
| 前端build | PASS | 1872 modules transformed |
| 本地真实JWT login/me | PASS | 浏览器进入finance角色工作台 |
| 本地refresh/me | PASS | refresh生成access，me返回可信上下文 |
| 403路由 | PASS | 无integrations权限进入统一403 |
| 退出 | PASS | 清理客户端会话并返回登录页 |
| 390px响应式 | PASS | 无横向溢出，移动导航生效 |
| Pilot部署账号E2E | 未执行 | 当前未部署该分支，也未使用Pilot账号 |
| 远端CI | 未执行 | 当前实现未提交、未创建PR |

现有 UI-P1 测试主要验证会话工具和源码合同，尚未以axios mock或浏览器自动化覆盖并发401只刷新一次、refresh失败、token过期恢复等运行时分支。

## 10. 安全扫描

结论：**未发现P0安全问题**。

- 未发现被跟踪的 `.env`、私钥、证书、SQLite、日志或运行缓存。
- 高置信密钥扫描唯一命中 `TASK-INVALID-FEEDBACK`，属于字符串中包含 `sk-` 的误报，不是密钥。
- 未发现真实 BigSeller、Shopee、TikTok/TK、银行、支付凭据或真实业务数据。
- 未发现真实平台连接、真实RPA执行、自动采购、自动清仓、自动改价或资金操作。
- 前端finance路径均保持 `/api/finance/*`；未发现 `/admin/` 和RPA Agent执行路径调用。

## 11. P0

无。

## 12. P1

### UI-P1-R1-P1-001 非公开路由合同不完整且未登记路径默认放行

证据：`frontend/src/router/menu.js` 的 `canAccessPath()` 在无匹配条目时返回 `true`；多条非公开路由未进入菜单/能力合同。实际测试证明细分权限不足的用户可直接进入 `/finance/imports` 页面。

整改标准：

1. 为每一条非公开路由声明 capability/permission/user_type，详情路由继承父资源权限。
2. 未登记路由默认拒绝，不得默认放行。
3. 区分 `finance.view`、`finance.import`、`finance.reconcile`、`finance.exception.handle` 等动作。
4. 增加全路由覆盖测试和 internal/external/RPA/finance直接URL测试。

### UI-P1-R1-P1-002 按钮、动作和字段权限未按后端action permission收敛

证据：`hasPermission()` 当前无页面调用；view权限用户仍可看到需要review/export/manage/approve权限的动作。后端拒绝可防止越权执行，但前端权限展示合同未完成。

整改标准：

1. 建立可复用的action capability组件或指令，所有动作声明权限码。
2. 无权动作隐藏或禁用并给出原因，不得发送无权请求。
3. 敏感字段只消费后端脱敏结果，不以CSS隐藏作为保护。
4. 覆盖 replenishment、alerts、reports、config、finance 和 integrations 动作权限测试。

## 13. P2

1. refresh token当前保存在 `sessionStorage`；生产准入前应评审 HttpOnly、Secure、SameSite Cookie 与CSRF方案。
2. 退出仅清理客户端会话；生产前应评估refresh token服务端撤销或黑名单。
3. 并发401单次刷新、refresh失败和过期恢复目前缺少行为级自动化测试。
4. 404与empty语义尚未拆分，connected状态缺少最近验证时间和能力级证据。
5. Vite仍存在第三方PURE注释warning；当前不阻断。Pilot账号E2E与远端CI需在形成PR后执行。

继承风险：`UI-P0-P1-004` MySQL下RPA活动账号锁唯一约束仍应在 UI-P3 前关闭，本轮不纳入UI-P1结论。

## 14. 是否允许UI-P1收尾

**不允许。**

必须先关闭 `UI-P1-R1-P1-001` 和 `UI-P1-R1-P1-002`，补充对应自动化测试，并由架构员执行 UI-P1-R2 复审。当前允许继续在本分支进行UI-P1定向整改，不允许以本报告将UI-P1标记完成。

## 15. 是否允许进入UI-P2

**暂不允许。**

UI-P2涉及组织用户、六层权限和基础档案，依赖完整的路由、按钮、字段和data_scope能力合同。待UI-P1-R2结论为PASS并形成稳定提交后，方可进入UI-P2。
