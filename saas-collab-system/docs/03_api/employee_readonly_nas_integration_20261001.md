# NAS 员工实时只读接入合同（候选）

当前未生产发布、未启用。原 `/api/internal-readonly/v1/` 机器同步和原共用登录接口保持不变，不得用机器凭据替代员工授权。

员工委托仅接受有明确租户、与调用方同租户的内部非 Django 超管账号。`is_superuser=true` 账号不得授权、交换或使用员工委托凭据，不能继承原生“所有字段/全部范围”的特殊权限；普通账号变为超管后旧授权码/令牌也拒绝。原系统超管、身份 SSO 与机器 API 行为不变；本人仍可用原系统登录调用 revoke-all 撤销旧委托。

OpenAPI：同目录 `employee_readonly_v1.openapi.yaml`。接口根路径 `/api/employee-readonly/v1/`；受众固定 `employee-readonly-v1`。员工授权码有效 90 秒，一次性消耗；查询凭据最长 300 秒，无 refresh。权限、范围、调用方配置或账户状态变化使旧凭据失效，需重新授权。

## NAS 需要填写与实现的参数

使用既有批准调用方的 client_id/client_secret；不会轮换或新增机器密钥。新增委托必须由管理员审阅后单独开启，不是勾选现有数据块或共用登录即可生效。

回调须为服务端精确登记的完整 HTTPS 地址。NAS 已提出 `https://knowledge.dxp4800-dfcy.lan.ug.link/api/auth/shared-login/callback`，尚需确认这个处理器能区分员工委托与原身份登录流程。公司 DNS 解析和员工浏览器可达性仍需 NAS 验收。不能只替换 URL 就自动开通查询。

NAS 生成随机 state（16–256 字符）及 PKCE verifier（43–128 字符），计算 SHA-256 的无填充 base64url challenge。将 state/verifier 按员工登录会话隔离保存，原系统登录后向 `POST authorize/` 提交 client_id、redirect_uri、state、code_challenge、audience。该授权步骤使用原系统本人登录，不把原系统业务 JWT 交给 NAS。

浏览器授权入口沿用原系统 `/sso/authorize`，但必须额外提供 `purpose=employee_readonly` 和 `audience=employee-readonly-v1`，再加上 client_id、redirect_uri、state、code_challenge 的 URL 编码查询参数。页面显示“确认员工只读委托”，用户确认后才调用独立员工 authorize 接口。缺失/错误 purpose 或 audience 拒绝，不退化成身份 SSO；没有这些参数的旧登录流程保持不变。

回调收到 code/state 后，NAS 必须先匹配本地会话 state，再由服务端 `POST exchange/` 发送 code、redirect_uri、state、code_verifier、audience，使用 `Authorization: Basic <client_id:client_secret 的 base64>`。返回 data.access_token、token_type=Bearer、expires_in=300、audience。短时令牌加密保存，不能进入浏览器、问答上下文、日志或分享链接。

查询每次同时提供两个头：既有 `Authorization: Basic ...` 和 `X-Employee-Delegation: Bearer <access_token>`。先查询 `GET capabilities/`，仅使用它给本人的 ready_resources 与 fields。禁止读取机器公开目录后推断员工能力。

## 首批读取范围

候选仅实现 products（商品主数据）、product_details（商品明细）、stores（店铺）、warehouses（仓库）。是否实际返回取决于调用方已有数据块授权、本人原生查看权限、DataScope、委托开关和逐字段权限的交集。字段定义全部为显式非敏感投影，不包含成本、联系电话、凭据或角色权限。

新增字段权限采用 `field.employee_readonly.{resource}.{field}.view`，目录定义无自动角色分配。配置 `EMPLOYEE_READONLY_FIELD_POLICIES` 将各 resource 的字段映射到对应目录代码；资源和字段元数据必须匹配，不能借用系统管理字段权限。全局 `EMPLOYEE_READONLY_ENABLED` 默认 false；`EMPLOYEE_READONLY_CLIENT_IDS` 和字段策略默认空。配置、更改角色字段授予均是待审阅的生产最后一步，本次不执行。

销售订单、采购订单、库存快照、财务聚合仍待独立员工范围接入，不使用机器接口兜底。金额总额、同比和趋势没有正式合同，不可依据局部商品或订单行推算。

| 数据块 | 最大可配置字段集合（实际仍以本人 capabilities 为准） | 原生权限 |
| --- | --- | --- |
| products | id, spu_code, legacy_spu_code, product_name, brand, category, lifecycle_status, sales_status, updated_at | products.master.view |
| product_details | id, spu_id, sku_code, legacy_sku_code, product_name, color_code, specification, size, material, image_url, is_active, updated_at | products.master.view |
| stores | id, platform_id, platform_site_id, code, name, country_code, currency, status, updated_at | masterdata.view |
| warehouses | id, code, name, country_code, warehouse_type, status, updated_at | masterdata.view |

products 复用 filter_product_spus，product_details 复用 filter_product_skus 并限定关联 SPU 同租户；stores/warehouses 复用 filter_master_data 的直接业务维度及父级派生范围。任一资源没有适用的本人范围，不扩大为全部租户数据。

字段策略示例（仅演示，不是生产授权）：`{"products":{"id":"field.employee_readonly.products.id.view","product_name":"field.employee_readonly.products.product_name.view"}}`。还需要给受控测试角色显式授予这两个 FIELD 权限，以及原生查看权限和 DataScope；仅填配置不会授予角色权限。

租户管理员自动同步和初始化已排除新增员工委托字段，避免新增目录导致隐式权限扩张；已显式授予的委托字段保持不变。商品 image_url 只是当前图片引用，实际图片服务继续遵循原访问规则，本合同不提供员工保护的图片下载代理。

## 筛选、分页与时效

`GET resources/{resource}/` 只接受 id（正整数精确匹配）、limit（1–100 且不超过调用方上限）、cursor；未知条件拒绝。所有范围先应用再分页。不透明游标按返回值原样传回，绑定本人授权、资源及 id 条件，不可跨员工或查询复用。不支持 total。

返回 data.resource、items、query_time、business_updated_at、filters、returned_count、has_more、next_cursor、source_path、request_id。source_path 是原系统相应原生只读 API 的相对路径，不是通用代理。business_updated_at 仅描述当前页记录的最大更新时间；无记录或本人无更新时间字段授权时为 null，不能当作全库最新更新时间或上游同步水位。

NAS 应同时展示查询时间、来源更新时间/未知、筛选及是否仍有后页。不能把 has_more=true 的局部结果当作全部。缓存必须按 client/subject/tenant/授权版本隔离，撤销和权限变化后不得继续回答缓存的实时业务数据。

## 错误、退出与超时

401 表示调用方或委托凭据失效/不匹配，清除对应令牌后重新授权；403 表示资源/员工/字段权限拒绝；404 为待接入；400 为无效请求或游标；429 为调用方限流。错误不得转成服务账号重试。网络超时/5xx 应明确显示实时查询不可用，不返回过期快照作为当前结果；NAS 配置有限连接/读取超时和有限重试。

NAS 退出先调用 `POST revoke/`（双头），撤销同员工/调用方的全部委托，然后清除本地凭据和缓存。原系统本人可用原生登录调用 `POST revoke-all/`（空 JSON 对象），撤销自己的全部委托/未交换授权码，不接受指定他人 user_id。

当前未改动原系统前端退出按钮，NAS 与原系统退出流程仍须显式调用以上撤销接口。不能宣称单纯关闭浏览器或普通业务 JWT 退出已自动注销委托；未显式撤销时上限仍为 300 秒。生产开启前需补齐退出集成验收。

## 最后一步与验收

当前为代码候选。用户已授权默认关闭代码按虚拟机→阿里云发布通道登记发布；须通过正确前序版本、迁移图、最终 HEAD CI、独立安全审阅、保护审批和实际环境验收，不代表现在可部署或启用。调用方开关、字段策略/角色分配及启用实时查询仍需提交具体资源与岗位矩阵另行确认。隔离 A/B 自动测试不能替代实际岗位与原系统页面对照。NAS 员工查询必须继续关闭，待发布与双端联调、退出集成验收及单独启用批准后才能开放。
