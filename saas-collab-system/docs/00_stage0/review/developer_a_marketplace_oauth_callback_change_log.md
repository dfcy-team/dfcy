# A-PR2 Marketplace OAuth / Callback 变更日志

## 状态

- 实现分支：`feature/module-a-platform-oauth-callback`
- 基线：A1 R2 `05308bd`
- 当前能力状态：`mock` / `pending`，未标记 `connected`
- 真实 Shopee、TikTok Shop、Sandbox 和 Production 网络调用：未启用

## 模型与迁移

- 新增 `MarketplaceOAuthAttempt`。
- 仅保存 `state_hash`、`session_hash`、`idempotency_key_hash`、请求指纹哈希、operation ID 哈希、租户/内部用户/配置/店铺/平台/区域/redirect target code、状态和脱敏错误码。
- state 使用 32 字节 CSPRNG，固定 5 分钟 TTL；原始 state 只随服务端生成的 synthetic authorization URL 在请求内存中流转，不落库。
- attempt 模型禁止直接 `save/update/delete/bulk` 绕过 OAuth service。
- 新增 integrations 迁移 `0010_marketplaceoauthattempt`。

## 状态机、幂等与权限

- 状态：`initiated -> callback_received -> exchanged -> succeeded`，错误进入 `failed`，过期进入 `expired`；state 消费使用行锁和一次性 `consumed_at`。
- initiate、refresh、revoke、retry 均要求 `Idempotency-Key`；attempt 使用 tenant + key hash 唯一约束，重复同请求返回缓存的原结果，不同请求返回 409。
- internal API 使用 exact permission：`integrations.store.authorize`、`integrations.store.view`、`integrations.credential.rotate`、`integrations.store.revoke`、`integrations.store.retry`。
- `platforms/store_ids` 与 tenant/store/config scope 由后端校验；前端展示权限不作为安全边界。

## Callback、redirect 与 custody/saga

- callback 只接受 `shopee|tiktok`，严格拒绝未知字段、重复字段、错误签名、错误平台、错误门店、过期/重放 state。
- redirect 只接受服务端 allowlist code `integrations`，只回跳相对路径并携带结果码、attempt 公共 ID 和稳定错误码，不回显 callback query。
- synthetic adapter 覆盖拒绝、签名错误、托管失败、429、5xx 和超时；不建立任何网络连接。
- code 仅在本次请求内传入 synthetic custody gateway；数据库、日志、审计、异常和任务队列只保存脱敏引用/错误码/operation ID hash。
- refresh/revoke 使用 operation ID hash 和现有引用轮换/撤销服务；外部失败保持本地引用不变并记录失败审计，未把外部副作用包装成数据库原子事务。

## 前端

- 新增 `/integrations/oauth` 页面和 integrations API/mock 方法。
- 页面只消费后端返回的 `authorization_url`，不自行构造 endpoint、state 或 callback URL；不写 localStorage/sessionStorage/路由 state/analytics/错误监控。
- 展示 loading、pending、success、expired、failed、replayed、forbidden、offline 语义；不提供 Token/Secret/Cookie/Session 输入。

## 验证结果

- `Django check`：通过。
- `makemigrations --check --dry-run`：通过。
- PR-A2 定向测试：已补充并通过；当前定向文件结果 `34 passed, 1 skipped`。
- 前端 `npm.cmd run build`：通过，1957 modules；无 chunk size warning，仅有上游 `@vueuse/core` PURE 注释移除提示。
- 后端全量 pytest：`443 passed, 1 skipped`。
- 前端 `npm ci`：通过；npm audit 报告 production 依赖 `postcss` 1 个 high advisory，未在本任务内擅自升级。
- 前端 `npm test -- --run --maxWorkers=1`：`160 passed`。
- 前端生产构建：通过，1957 modules；无 chunk size warning，仅有上游 `@vueuse/core` PURE 注释移除提示。
- CI guard：通过；高置信凭据模式扫描：`0` 命中；callback/SSRF/开放重定向静态扫描未发现用户可控 redirect URL 或真实平台 endpoint；dist/node_modules/cache/pyc/.env 未跟踪。
- `sandbox.ps1 verify integration`：未通过，原因是本机 Docker Desktop Linux engine pipe 不存在，Sandbox 无法启动；不得视为 integration PASS。
- MySQL 8.4 全新迁移、升级、失败重跑和并发：未执行，原因同上且本机无 mysql/mysqld 客户端；不得视为 MySQL PASS。

## 未完成项与边界

- 获批应用控制台、精确 endpoint/scope/callback URL、密钥托管和网络出口证据未提供，因此真实 Sandbox adapter 保持关闭，状态不得改为 `sandbox_verified` 或 `connected`。
- Docker/MySQL 环境恢复后，必须重跑 Sandbox integration 与 MySQL 专项，再更新本日志和独立复审证据。
- 不创建订单、退款、库存、采购、付款、RPA 或 webhook 记录，不接入 `/admin/`，不提交真实凭据或真实业务数据。
