# 小程序真实登录与发布合同操作台验收记录

## 1. 本阶段范围

- 微信小程序 `wx.login` 到后端 `code2Session` 的真实模式代码链路。
- 小程序 JWT、租户、权限及发布合同只读接口衔接。
- 内部管理端发布合同操作台。
- 微信开发者工具和管理端浏览器视觉验收。

## 2. 已完成验收

### 2.1 真实登录代码链路

- 小程序只向 `/api/miniapp/auth/login/` 提交一次性 code。
- 后端平台模式固定调用微信 HTTPS `code2Session` 地址。
- AppID/AppSecret 只从后端环境变量读取。
- 原始 openid 只用于即时摘要匹配，不写数据库和响应。
- `session_key` 不进入数据库、JWT、响应或日志。
- 无效/已使用 code 映射为 `MINIAPP_CODE_INVALID`。
- 微信超时、系统繁忙或异常响应映射为 `MINIAPP_PROVIDER_UNAVAILABLE`。
- 生产模式缺失 AppID/AppSecret 时启动失败关闭。

测试状态：后端小程序认证专项 9 项通过；小程序平台登录、配置、请求、会话及只读发布合同测试 18 项通过。

### 2.2 内部发布合同操作台

- 路由和菜单：`/releases/contracts`。
- 权限边界：view/manage/approve/execute 四类权限分别控制。
- 页面能力：概览、筛选、列表、证据链详情、门禁录入、独立审批、构建确认、状态推进和回滚审批。
- 所有写操作携带 `Idempotency-Key` 与合同 `version`。
- 不存在上传代码、平台凭据、微信发布、真实部署或自动回滚入口。

测试状态：生产构建通过；操作台专项 6 项通过；桌面端和 390×844 窄屏浏览器视觉验收通过；页面控制台无 error/warning。

## 3. 微信开发者工具验收状态

验收日期：2026-07-24 至 2026-07-25。

验收环境：

- 微信开发者工具 Stable `2.01.2510290`，已安装并登录。
- 调试基础库 `3.17.0`（灰度/试用基础库）。
- 工程目录：`miniapp/`。
- 仓库公共配置 AppID：`touristappid`；本机私有配置已使用真实 AppID。
- 运行配置：`development + platform + useMock=false`。
- 本机 API：`https://127.0.0.1:9444`，使用 Windows 当前用户信任的
  mkcert 开发 CA，反向代理至 Django `127.0.0.1:8002`。
- 开发者工具服务端口：`51347`，登录状态有效。

### 3.1 模拟器与视觉验收

已通过：

- 工程成功导入并完成普通编译。
- 登录页可见环境、Mock 边界、微信快捷登录及服务端密钥安全说明。
- Mock 登录后首页正确显示演示用户、工程底座、认证、发布合同和真实平台发布禁用状态。
- 发布合同工作台正确显示只读声明、2 条脱敏合同、状态分布及 `6/6` 门禁摘要。
- 合同详情正确显示合同号、候选提交、API 合同、风险、回退版本、观察窗口、对象版本、门禁结果和审批记录。
- 合同详情明确标注“只读详情 · 不提供状态变更操作”，页面不存在审批、发布、回退等写操作按钮。
- iPhone 12/13 模拟器下标题、卡片、标签、滚动和底部安全区显示正常。

首次编译发现 `app.js` 使用 `require("./config")`。Node.js 测试会将其解析到目录入口，但微信运行时只查找 `config.js`，导致 `module 'config.js' is not defined` 和页面未注册。已改为显式引用 `require("./config/index")`，并在工程校验中增加“禁止目录 require”规则。

### 3.2 Console 验收

- 修复后业务代码不再出现模块未定义、页面未注册、WXML 或业务脚本异常。
- Mock 登录日志仅输出环境与事件名称，未发现 AppSecret、openid、`session_key` 或令牌明文。
- 当前仍存在微信开发者工具自身噪声：
  - 游客模式 `wx.operateWXData` 受限警告。
  - 灰度基础库 `3.17.0` 的 `webapi_getwxaasyncsecinfo:fail`。
- 真实 AppID 自动化复验中，小程序 App 通道可执行 Storage 清理、页面
  `reLaunch` 和真实认证服务调用；当前开发者工具版本与官方
  `miniprogram-automator 0.12.1` 的 Page 数据/DOM 通道不兼容，
  `Page.getData` 和元素查询超时，因此未把 DevTools Console 面板计数作为
  最终通过证据。认证结果改由小程序运行上下文返回值和脱敏后端访问日志
  双重确认。

### 3.3 Network 验收

- 真实平台模式已发出并完成以下请求：
  - `POST /api/miniapp/auth/login/`：身份未绑定时受控返回 401；完成安全
    摘要绑定后返回 200。
  - `GET /api/miniapp/auth/me/`：返回 200，用户为 `Torrey_Mock`，租户为
    `Torrey Local Mock Tenant`。
  - `GET /api/miniapp/releases/workbench/`：返回 200，
    `read_only=true`，当前租户合同总数为 1，状态分布为
    `review_pending: 1`。
  - `GET /api/miniapp/releases/contracts/1/`：返回 200，合同环境为
    `test`，6/6 门禁通过，审批数为 0，制品为空，符合“待独立审批且未构建”
    的只读展示边界。
- 首次真实登录发现本地 MySQL 未应用 `accounts.0002_miniappidentity`，
  接口返回 500；应用 accounts、permissions、releases 迁移后恢复为预期的
  401 未绑定响应，再完成受控绑定后登录成功。
- 未在响应、自动化输出、日志或数据库中输出/保存 AppSecret、原始 openid
  或 `session_key`；身份表只保存 SHA-256 摘要。
- 本地验收种子命令重复执行后仍保持同一合同 ID、合同号和 6 项门禁，
  未重复写入合同或门禁。
- 401 自动刷新已通过：在模拟器会话中仅替换访问令牌并保留真实刷新令牌，
  后端访问日志依次记录 `GET /auth/me/ 401`、
  `POST /auth/refresh/ 200`、`GET /auth/me/ 200`；刷新后的访问令牌已轮换，
  随后 `GET /releases/workbench/` 继续返回 200、`read_only=true` 和 1 条合同。

### 3.4 真机预览

- 开发者工具 CLI 服务端口已开启并在重启后持久生效，CLI 可识别真实
  AppID、登录状态和自动化端口。
- 本机模拟器已完成真实微信账号登录。
- 本地 Django 服务继续监听 `127.0.0.1:8002`，真机验收期间通过临时
  Cloudflare Tunnel 提供 HTTPS 转发；该地址不是正式业务域名，不作为发布配置。
- 真机在开启开发调试后完成扫码预览和真实微信登录，正确显示
  `Torrey_Mock` 与 `Torrey Local Mock Tenant`；工程底座和发布合同能力均显示已连接。
- 首页认证能力曾按静态配置错误显示为 `pending`，现已改为依据已建立的真实会话
  显示 `connected`，并增加专项测试。
- 真机发布合同列表验收通过：可见合同总数为 1，状态分布为
  `review_pending: 1`，合同 `RC-20260725-964B6FBA81` 显示风险等级 `low`、
  环境 `test` 和门禁 `6/6`。
- 真机合同详情验收通过：页面明确标注“只读详情 · 不提供状态变更操作”，
  正确显示合同号、候选提交、API 合同版本、风险等级、回退版本、观察窗口、
  对象版本、6 项门禁证据和“暂无审批记录”；未出现审批、上传、发布或回退按钮。
- 本地 `test` 合同的 `6/6` 仅表示工程验收门禁通过；生产合同必须额外满足
  第 7 项 `miniapp-filing-approved`，不得以本地验收结果替代备案审核。
- 未执行小程序上传、正式发布或真实部署。

### 3.5 自动化校验

- `npm run check` 通过。
- 项目结构校验通过：6 个页面、24 个 JavaScript 文件。
- 小程序测试 21 项全部通过。
- 发布合同后端专项测试 7 项全部通过；生产环境新增
  `miniapp-filing-approved` 强制门禁，备案审核证据缺失、失败或过期时阻断合同提交。
- 新增校验会阻止依赖 Node.js 目录入口解析的相对 `require` 再次进入微信运行时。
- 新增 `bind_miniapp_login_code` 安全绑定命令，从标准输入接收一次性 code，
  服务端换取并摘要化身份；专项测试通过，原始 code/openid 不回显。

## 4. 正式发布前外部条件

- 正式发布前配置自有 HTTPS 域名和微信合法 request 域名，替换临时 Tunnel。
- 小程序完成备案审核与微信平台审核前，不开放上传、提交平台审核或发布操作；
  本地验收不得伪造 `miniapp-filing-approved` 生产证据。
- 环境专用运行配置与密钥不得提交仓库；AppSecret 继续只保存在被忽略的
  根目录 `.env`。

当前结论：模拟器与真机真实微信账号登录、发布合同列表、合同详情、6/6 本地
测试门禁和小程序只读边界均已通过；备案审核与微信平台审核完成前，真实上传、
提交审核及发布能力保持禁用。
