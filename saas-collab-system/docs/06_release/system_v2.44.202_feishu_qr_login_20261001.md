# V2.44.202 飞书扫码登录候选

基线为 V2.44.201 / `ce8a74be74936f7cfed47e3447e4a26e07fbe4f6`。用户明确要求完整飞书扫码登录、未绑定用户保留账号密码登录，并按虚拟机部署验收登记、阿里云发布、缺失飞书权限申请的顺序交付。本文件是候选说明，不代表已经部署。

## 行为与边界

登录页在服务器已配置且只有一个符合条件的飞书应用连接时展示扫码区域，原密码表单始终可用。飞书认证仅以当前应用返回的 open_id 查找既有身份绑定；不按姓名、手机号、邮箱自动绑定，不创建用户。登录要求绑定、用户、租户均可用，用户属于同一租户且为内部用户；保留原账号角色、权限、数据范围和 UAT 凭据有效期检查。

新增匿名接口为 `/api/feishu/login/config/`、`start/`、`callback/`、`complete/`。state 与浏览器 HttpOnly/SameSite=Lax cookie 关联，仅存 SHA-256 摘要，5 分钟过期，通过数据库条件更新跨进程一次消费。授权码只在服务器内存交换；不会存储飞书 access/refresh token，也不申请 offline_access。回调只跳转 `/login?feishu=complete`，随后通过 60 秒的一次 HttpOnly cookie 交换原系统 JWT。完成交换前再次校验配置、身份摘要、账号和租户状态。失败只展示固定中文提示，不回显远端错误或凭据。

前端使用固定官方 1.0.3 SDK，保留服务器提供的完整授权 URL，仅追加已编码 tmp_code。SDK 的 matchOrigin、matchData 和 iframe source 都必须符合。刷新、过期、SDK 加载失败和页面卸载均清理监听；失败后仍可使用密码。授权网址中的任何系统令牌均被禁止。

## 路由、权限、部署差异

- 无菜单、原菜单路由、系统权限目录或角色分配变更；只增加上面的公开登录接口及登录页面扫码区。
- 数据库仅新增 `integrations.0036_feishuloginsession` 的临时认证记录表，不修改已有业务数据或身份绑定。
- App Secret 沿用现有 FeishuConnection 的 custody 引用，不写入源码或环境变量。
- 新增两个非敏感环境变量：`FEISHU_LOGIN_APP_ID`、`FEISHU_LOGIN_REDIRECT_URI`。任一未设置时关闭扫码入口。
- 回调必须与访问环境同源，路径严格为 `/api/feishu/login/callback/`。生产要求 HTTPS，禁止外部任意回跳。
- Gunicorn 访问日志改为只记录 URL path；镜像 Nginx 对飞书回调关闭 access log，防止一次授权码/state 入日志。`/api/` 保留原 Host 端口，支持 VM 的 HTTPS 端口。同样需要核对云端外层代理不记录回调查询参数。

## 验证

后端定向测试 57 项通过，包含原密码登录和既有飞书身份管理回归，以及浏览器关联、过期、重放、重复绑定、跨租户、停用、绑定/应用配置变化、UAT 租约、远端失败脱敏及官方端点契约。`makemigrations --check --dry-run` 无差异。

前端 146 个测试文件、857 项通过，扫码相关 9 项行为/校验测试通过。生产构建使用 `VITE_USE_MOCK=false`，菜单权限快照 108 菜单/142 路由一致。浏览器验收用本地非生产 API 预览检查官方 SDK 渲染与密码回退；真实已绑定用户扫码、生产回调登记和环境配置需在受控发布阶段完成，不能将模拟响应当成线上认证验收。

## 飞书配置与权限

阿里云正式回调为 `https://xtsy.dingfengchuangyu.com/api/feishu/login/callback/`，应用为 `cli_aa3e3f5b6a79dcb9`。VM 必须使用其真实同源入口对应的回调，不可直接套用云端 URI。只登记实现过的 OAuth 回调，不使用 mock-callback 或事件回调替代。

当前官方 `/authen/v1/user_info` 接口权限要求为“无”，仅使用用户 token 返回的 open_id，扫码本身不新增通讯录 scope。通讯录手机号和部门字段的 `contact:user.phone:readonly`、`contact:user.department:readonly` 是资料字段权限，是否申请须结合后续六页签实际调用汇总，不申请历史 `contact:contact:readonly_as_app` 代替当前权限。应用主页已保存草稿，配置需按开放平台发布流程生效。

官方依据：[二维码 SDK](https://open.feishu.cn/document/sso/web-application-sso/qr-sdk-documentation)、[user token v2](https://open.feishu.cn/document/authentication-management/access-token/get-user-access-token)、[登录用户信息](https://open.feishu.cn/document/server-docs/authentication-management/login-state-management/get)。

## 发布与回退

先完成独立审查及最新提交 CI，使用主分支可达的 SHA 与 CI 不可变镜像，备份并应用唯一新增迁移，验收 VM 后登记双账本，再推广阿里云。版本 203 必须接续 202 最终源码，避免覆盖扫码实现。

应用回退至 V2.44.201 镜像，并移除/留空这两个扫码环境变量。新增临时认证表可保留；无需回滚既有业务或绑定数据。飞书开放平台回调如需移除，应按平台可审阅配置变更执行。所有登记记录必须保留真实 SHA、镜像摘要、迁移树 hash、验收证据、备份与回滚点，不能用候选号冒充已部署版本。
