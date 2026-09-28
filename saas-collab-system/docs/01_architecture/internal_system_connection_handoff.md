# 内部调用系统接入资料交接清单

管理员在“API 数据接入 → 内部系统数据接口”完成配置后，点击该调用系统的“接入资料”，复制不含密钥的参数。必须先由另一位管理员审核通过，再单独启用；未启用时交接资料仅用于开发准备。

“接入资料”的 `caller_must_configure` 明确列出调用方要修改的环境参数：`CLIENT_ID`、`CLIENT_SECRET`、服务器出口 IP，以及按启用能力出现的 `READONLY_API_BASE_URL`、`READABLE_RESOURCE_CODES`、`LOGIN_AUTHORIZE_URL`、`LOGIN_TOKEN_URL`、`LOGIN_CALLBACK_URL` 和 `LOGIN_PKCE_METHOD`。`CLIENT_SECRET` 只在创建或轮换后的“一次性凭据”窗口可点“复制密钥”；关闭后不能从接入资料或列表重取。

## 双方需要提供的内容

| 内容 | 由谁提供 | 用途 |
| --- | --- | --- |
| 调用系统名称 | 调用方 | 识别登记对象 |
| HTTPS 登录回调地址 | 调用方 | 开启共用登录时，由本系统精确白名单校验；不能有通配符、查询参数或片段 |
| 服务端出口 IP/CIDR | 调用方 | 本系统校验数据查询或授权码兑换请求的来源；单 IP 用 `/32` |
| Client ID | 本系统 | 调用方标识；在“接入资料”和创建结果中查看 |
| Client Secret | 本系统 | 仅创建或轮换后显示一次，须走独立安全渠道交给调用方服务端；丢失后只能轮换 |
| 只读 API 基址与已接入数据块 | 本系统“接入资料” | 仅 `ready_resources` 可实际查询；`pending_resources` 尚未上线 |
| 共用登录授权与兑换地址 | 本系统“接入资料” | 浏览器跳转到授权地址；调用方服务端用一次性授权码兑换基础身份 |

调用方不应填写本系统用户密码，也不应把 Client Secret 放到网页、小程序或客户端安装包。数据查询与授权码兑换使用 HTTP Basic `client_id:client_secret`，从已登记的服务端出口 IP 发起。共用登录需在调用方保存并校验随机 `state` 和 PKCE S256 验证器。返回的身份不含本系统角色权限，调用方自行决定权限；完整流程见 `internal_shared_login.md`。
