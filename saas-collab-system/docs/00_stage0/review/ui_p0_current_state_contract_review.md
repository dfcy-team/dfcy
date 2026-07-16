# UI-P0 现状审核与合同冻结报告

## 1. 审核对象

- 规划依据：V2.1 API安全架构融合优化审核预览。
- 代码基线：`main`，提交 `488a38c`。
- 范围：前端视图、路由、API客户端、Mock、认证、布局、权限展示、后端认证/权限基础、测试和试点部署结果。
- 性质：只审核和冻结合同，不修改业务代码。

## 2. 审核结论

结论：**CONDITIONAL_PASS**。

允许继续进行信息架构、页面流程、低保真原型、统一组件和Mock设计；暂不允许把 UI-P1 判定为完成，也不允许开展真实业务、真实平台或高风险RPA验收。进入 UI-P1 实现前必须接受本报告中的合同；UI-P1结束前必须关闭全部P1。

## 3. 当前基础

- 前端存在67个Vue视图、66条路由声明、23个API文件和Mock/API切换基础。
- Vue Router已使用懒加载，MainLayout具备侧栏、页头、内容区和窄屏抽屉。
- 页面已有loading、empty、error及部分统一数据页组件。
- 后端具备统一响应、JWT登录/刷新、`/auth/me`、tenant、权限、data_scope、财务独立授权和审计基础。
- 应用试点环境已验证Nginx、Django、MySQL、Redis、Celery和前端页面健康链路。

## 4. 合同冻结结果

- 采用 `ui_design_phase_execution_plan.md` 的 UI-P0 至 UI-P7 顺序。
- 采用 `ui_api_interaction_contract.md` 的接口分区、统一响应、错误、认证和能力状态。
- 菜单按业务使用区、RPA协同中心、系统管理、API治理、智能体预留、供应商协同和API数据接入中心规划。
- 页面统一采用页头、查询、列表、详情、状态反馈和操作反馈骨架。
- 权限分为菜单/页面、按钮、字段、data_scope、流程和导出六层。
- Mock、pending、sandbox、connected、degraded、disabled必须基于证据。

## 5. 实测结果

| 项目 | 结果 | 证据摘要 |
|---|---|---|
| 前端测试 | PASS | Vitest 2个文件、33项通过 |
| 前端构建 | PASS | Vite构建成功，1856模块转换 |
| Django check | PASS | 0 issues |
| 后端专项测试 | PASS | auth/common responses/permissions/finance permissions共23项通过 |
| 试点健康链路 | PASS | Nginx 8080代理internal health返回统一成功响应 |
| 真实前端登录 | BLOCKED | 页面仍显示Mock用户，业务API返回AUTH_REQUIRED |
| 真实平台/RPA/资金 | NOT RUN | 安全边界禁止执行 |

## 6. P0问题

无已发现P0。当前未提交真实密钥、未启用真实平台连接，也未发现界面直接执行付款、转账、提现或真实高风险RPA。

## 7. P1问题

### UI-P0-P1-001 真实认证会话未落地

前端auth store默认使用Mock用户并将`isAuthenticated`设为true；登录页仅提供Mock登录；请求层未添加Bearer Token、受控刷新和401退出。试点页面可加载，但真实业务API返回AUTH_REQUIRED。

验收标准：真实登录、Token刷新、`/auth/me`、退出、401处理和认证自动化测试全部通过；production构建不默认登录Mock用户。

责任人：开发B；后端合同协作：开发A；复审：架构员。

### UI-P0-P1-002 路由和菜单权限仍为展示占位

当前路由守卫对所有非公开路由直接放行，菜单静态定义，尚未按`/auth/me`返回的roles、permissions和data_scope形成真实展示合同。

验收标准：菜单/按钮/字段展示与权限码一致；无权直接访问由后端返回403/404；覆盖角色切换和越权测试。

责任人：开发B；权限输出协作：开发A。

### UI-P0-P1-003 统一页面状态未覆盖完整合同

现有公共组件覆盖loading、empty和常规error，但403、409、422、partial、offline及可执行恢复动作尚未形成全局一致组件和测试。

验收标准：所有统一状态具有组件、文案、操作、测试和至少一个页面集成证据。

责任人：开发B。

### UI-P0-P1-004 MySQL下RPA活动账号锁缺少数据库唯一约束

MySQL不支持模型中的条件唯一约束，服务层查询不能完全消除并发插入竞态。该问题不阻断UI-P1设计，但阻断真实并发RPA和UI-P3正式放行。

验收标准：采用MySQL兼容的活动锁模型或等价数据库约束，并通过并发claim、租户隔离、过期释放和人工接管测试。

责任人：开发A；复审：架构员。

## 8. P2问题

- 前端测试目前只有2个测试文件，页面和组件覆盖不足。
- Vite构建存在第三方依赖PURE注释warning，当前不阻断。
- 当前试点仅HTTP内网访问；HTTPS/WAF、MFA、固定IP/VPN和浏览器认证态E2E尚未执行。
- V2.1规划文档和新增架构目录当前为未跟踪文件，提交前需单独审核范围和版本。

## 9. 安全边界

- 允许Mock、Sandbox、低保真原型、组件和只读API设计。
- 不允许真实BigSeller、Shopee、TikTok/TK、飞书、微信、银行或支付接入。
- 不允许自动采购、发布、改价、改库存、清仓、停售、归档或资金动作。
- 前端不得承载可信权限判断；RPA不得访问数据库、finance、internal或admin。

## 10. UI-P1准入建议

建议创建 UI-P1 独立功能分支，首批只处理：真实认证会话、角色菜单、统一页面骨架、完整状态组件和角色工作台。UI-P1开发可以开始，但其PR在 P1-001 至 P1-003关闭并完成架构复审前不得合并为完成；P1-004最迟在UI-P3前关闭。
