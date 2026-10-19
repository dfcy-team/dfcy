# TikTok Shop 令牌托管与达人查询试点

## 范围与边界

- 仅覆盖同一租户的 `TK1PH`、`TKKJ1PH` 两家 TikTok Shop 店铺；广告授权、Temu 和其他店铺不在本次范围内。
- SaaS 是两家店的唯一自动续期方。`dfcy` 只通过 HTTPS 的受控接口领取短期有效的 access token，不领取 refresh token，不在本地轮换试点店令牌。
- 达人查询只接受档案中已有的可信数字 `external_influencer_id`。缺失、非数字或重复 ID 只返回待人工确认，不按昵称/handle 自动绑定。
- 查询结果写入独立的 `TikTokCreatorProfileSnapshot`，不会自动覆盖达人主档案、送样记录或历史合作数据。

## SaaS 开关与权限

运行配置的 TikTok 节点需逐项审批后设置：

1. `auto_refresh_bindings`: 每家店一条精确绑定，包含 `tenant_id`、`store_code`、`region`、`platform_store_id`。默认空列表；不要为试点打开全平台 `auto_refresh_enabled`。
2. `affiliate_seller_creator_read_approved`: TikTok Partner Center 已批准卖家侧达人查询后才能打开；`affiliate_seller_creator_scope` 必须是平台实际授予的精确 scope。授权记录中的 `scopes` 也须包含该 scope，否则查询在发出网络请求前就拒绝。旧记录的空 scopes 需要经 SaaS 重新授权，不要猜测或手工填充。
3. `access_handoff_approved`: 两家店的机器取令牌接口通过安全审查后再打开。另需原有 `contract_approved`、`api_integrations` 模块和网络只读同步开关。
4. 查询用户还需 `influencers.manage`、`integrations.run_live_readonly` 及对应店铺的数据范围；读取查询快照需 `influencers.view`。

每家店单独创建一个 `InternalAPIClient`，只绑定本租户的目标店铺，`resources={}`、禁用 SSO、设置精确出口 CIDR 和速率限制。创建人不能审批自己的配置；审批后再启用。接口为 `GET /api/internal-readonly/v1/tiktok-shop-token/`，要求 HTTPS 与 Basic 机器认证，只返回绑定店铺的 access token、过期时间、店铺代号、app key 和 shop cipher；响应禁止缓存，发放动作留审计记录。

TikTok 官方的 [Get Marketplace Creator Performance](https://partner.tiktokshop.com/docv2/page/get-marketplace-creator-performance-202406) 文档列出 `16032012: only affiliate partner cipher can access this api`。当前代码使用店铺授权的 shop cipher，尚未证明其身份满足该接口要求。因此即使拿到一个看似匹配的 scope，也必须先用 Partner Center 的应用类型、授权主体和官方接口测试工具核实；若需要 Affiliate Partner 独立授权，不得拿 Seller access token 或 Seller shop cipher 硬试、也不得直接打开开关。

## dfcy 调用方

试点店铺需要为各自进程分别提供 `TTS_SAAS_TOKEN_URL`、`TTS_SAAS_CLIENT_ID`、`TTS_SAAS_CLIENT_SECRET`；私有 CA 才设置 `TTS_SAAS_CA_BUNDLE`。这些值只放受控运行环境，不提交 Git。`TTS_SAAS_SHOP_CODE` 可显式指定，但必须与所选 `config_TK1PH.env` 或 `config_TKKJ1PH.env` 一致。

客户端校验 HTTPS、返回的店铺代号、app key、shop cipher 以及令牌过期时间。任一校验失败时不回退本地旧令牌或旧 refresh token。商品、促销和广告报表的店铺商品目录读取也已走同一受控入口；其他店铺保留原有取令牌行为。

## 部署顺序与验收

1. 先在测试库验证迁移，再部署 SaaS 后端、Celery/Beat 与前端；首次部署保持新增开关关闭。迁移为达人 `0027`，集成 `0042` 合并节点与 `0043` 机器客户端/令牌审计表。
2. 在 34 主机只读核对两家店的租户、店铺代码、region、平台店铺 ID、shop cipher、开发者 app key、授权状态和现有续期状态。不要用模糊店名绑定。
3. 审批精确续期绑定；若授权已过期或上次轮换状态不确定，先从 SaaS 完成人工重新授权，不用 dfcy 本地刷新尝试恢复。
4. 单店依次验证 SaaS 自动续期状态，再审批其机器客户端和 access handoff。使用受控机器凭据做只读领取，核对返回身份和审计，不打印 token。
5. 取得平台 Affiliate Seller 权限证据并让店铺在 SaaS 重新授权后，配置真实 scope，先查询一条已核准数字达人 ID；检查独立快照与原档案不变。缺 ID、重复 ID、handle/region 不一致分别走人工处理。
6. 两家店分别观察一次正常续期与只读查询后，才切换 dfcy 作业使用 SaaS 接口。确认旧本地续期作业不再负责这两家店。

当前代码及合成数据测试通过不等于 34 主机已完成上述验收。尤其授权记录 `scopes=[]` 时达人真实查询会按设计拒绝。回退时先停用机器客户端并关闭 `access_handoff_approved` / `affiliate_seller_creator_read_approved`；不要同时恢复 dfcy 本地刷新，以免双写轮换令牌。
