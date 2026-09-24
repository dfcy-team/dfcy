# TikTok 回调参数兼容修复

范围仅限本地，未发布到虚拟机或阿里云，未执行真实 Token 兑换。

## 原因与改动

回调包含 `app_key`、`locale`、`shop_region`，原校验仅允许 `code`、`state`、`error`，因此在兑换前拒绝。

- 新增允许上述三个字段。
- 提供 `app_key` 时必须与当前接入配置匹配；提供 `shop_region` 时必须与会话绑定的地区匹配，不用回调覆盖绑定地区。
- `locale` 仅被接受，不传入 Token 兑换或授权记录。
- 保留原有最小回调兼容性；未知参数、空/不匹配身份字段、平台错误、空授权码仍拒绝。
- 不修改 state 消费、权限、配置版本、托管及兑换重试逻辑。

## 验证范围

使用虚构参数测试成功和拒绝分支，内存数据库验证完整回调及重复提交；本地已审批配置另做纯参数校验，无网络兑换。

选定回归集 98 项通过（137.58 秒），Django system check 无问题；并非全仓库测试。已重启本地后端加载修复。

真实平台复测仍需用户重新发起一次授权；已经消费的旧回调不能复用。合成通过不等同于真实平台完整授权成功。

## 后续兑换诊断

新回调通过参数校验后，诊断 `122cdc0efb6f4f928cc681646a93cd39` 记录兑换阶段 HTTP 200、业务错误未分类；没有成功授权。旧诊断未保留原数字错误码，无法反向还原具体拒绝原因。

补充 TikTok 官方已公开错误码的闭集白名单，并将整数错误码规范为字符串；未知码及异常类型仍归为未分类，不保存原始响应或错误消息，也不根据泛化错误猜测密钥是否正确。

来源：[Common errors](https://partner.tiktokshop.com/docv2/page/common-errors)、[Partner Center FAQ](https://partner.tiktokshop.com/doc/faqs/7174708423559305730)。接口及参数核对：[Authorization overview](https://partner.tiktokshop.com/docv2/page/authorization-overview-202407)。

此增量的选定合成测试 65 项通过，包含安全错误码、未知值脱敏和兑换不重试。未重放旧授权码，未改动 App Secret、网络策略或平台配置；本地后端已重新加载。

## 店铺核验网络出口修复

后续诊断 `91ef0ab3a1da4c91a2835584749750d6` 已进入 `verify_store`，分类 `network_uncertain`，未落库成功授权。本地复现 socket 连接被进程出口策略拒绝：数据库已审批 `open-api.tiktokglobalshop.com`，但独立启动器的 network-policy.json 未包含它。

在用户已允许的本地受控联调范围内，仅向该策略新增 `open-api.tiktokglobalshop.com`，仍限定平台连接 443 端口。无凭据测试 TCP/TLS 成功且证书验证通过（TLSv1.3）；禁止端口和非白名单地址仍被拦截。已重启本地后端，未改公网路由、云端配置或部署。

域名依据：[TikTok Shop Get Authorized Shops](https://partner.tiktokshop.com/docv2/page/connecting-shops)。本次连接测试不等于店铺身份核验成功，真实授权仍待新回调复测，不能复用已消费回调。

## 店铺核验 HTTP 400

诊断 `e27ac3e60c4c4f12bf1e3de066663653` 记录 verify_store、HTTP 400、36009004，没有成功授权。原记录未区分授权店铺查询和卖家权限查询，不能据此断言店铺身份不匹配，亦不能确认具体失败接口。

对照 [Get Seller Permissions](https://partner.tiktokshop.com/docv2/page/get-seller-permissions)，其为卖家级跨境权限接口，仅需 app_key/sign/timestamp 查询参数。修正 `_verify_metadata` 多传 shop_cipher 的明确请求问题，保留权限检查本身。此修正尚不能证明就是上述历史请求失败的唯一原因。

新增受限 operation 诊断，仅允许 get_authorized_shops/get_seller_permissions；HTTP 请求错误不再被默认归为身份不匹配。未知操作标签不输出。69 项相关合成测试通过，本地后端重启；没有调用真实平台、修改云端或重新兑换授权码。

## 普通店铺授权不再依赖跨境卖家权限

最新诊断 `f52ff56dff864c2f8165da6bd11e20df` 明确记录 `verify_store / get_seller_permissions / HTTP 401 / authentication_rejected`。平台业务错误码仍为未分类。按照执行顺序，此前的 Token 兑换、托管、授权店铺身份完整性及地区核对已通过，额外的卖家权限查询阻断了落库。

根据 [Get Seller Permissions](https://partner.tiktokshop.com/docv2/page/get-seller-permissions)，该接口用于跨境卖家的全球商品等操作权限，不应作为普通店铺授权必经步骤。普通授权及授权店铺查询改为仅使用 [Get Authorized Shops](https://partner.tiktokshop.com/docv2/page/get-authorized-shops) 核验真实店铺身份，移除原强制卖家权限请求及其孤立方法；并未将跨境能力标记为通过，未来执行跨境业务仍须单独验证所需权限。

保留唯一店铺、店铺 ID/cipher/地区、已请求 scopes、Token 托管、当前用户及店铺绑定、配置版本、一次性 state、防重放及事务回滚。不是捕获并忽略身份接口的认证错误；身份请求或校验失败仍拒绝授权并清理本次新托管引用。

测试先复现普通授权和店铺查询的两项失败，再修正。选定回归集 **107 项通过（128.05 秒）**，含合成平台请求、内存数据库落库、防重放、登录失效、配置变化及已有授权失败回滚。测试没有访问真实平台或业务数据库。无待处理授权会话及同步任务后重启本地后端，Django system check 通过，受保护 API 未登录返回 401；未发布到虚拟机或阿里云。

本次没有重放旧回调、兑换真实授权码或变更凭据。真实完整授权尚待用户重新发起一次新授权验证，合成测试通过不等于真实授权已经完成。
