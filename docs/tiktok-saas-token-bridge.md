# TK1PH / TKKJ1PH SaaS 令牌桥接

这两家 TikTok Shop 店铺的 access token 由 SaaS 托管续期。dfcy 脚本只读领取 access token，不使用本地 refresh token，也不会在 SaaS 失败时回退到 `.env` 中的旧 access token。

每家店单独部署调用进程和机器客户端，设置：

- `TTS_SAAS_TOKEN_URL`: HTTPS 地址，以 `/api/internal-readonly/v1/tiktok-shop-token/` 结尾。
- `TTS_SAAS_CLIENT_ID`、`TTS_SAAS_CLIENT_SECRET`: SaaS 审批通过且仅绑定该店的机器凭据。不要提交 Git。
- `TTS_SAAS_CA_BUNDLE`: 仅当使用私有 CA 时设置证书路径，不能关闭 TLS 验证。
- `TTS_SAAS_SHOP_CODE`: 可选；设置时必须与 `config_TK1PH.env` 或 `config_TKKJ1PH.env` 的店铺代号一致。

调用前会校验 SaaS 返回的店铺代号、app key、shop cipher 和过期时间。配置不一致、续期未完成或接口不可用时会停止当前调用。其他店铺不改变原有取令牌行为。商品、促销及广告报表使用的店铺商品目录查询也包含在桥接范围内；TikTok Ads 广告授权不受此桥接影响。

切换顺序：先验证 SaaS 两家店授权与自动续期，再审批各自机器客户端并允许令牌交接，最后逐店启用 dfcy 调用。不要让 dfcy 与 SaaS 同时为同一家店刷新令牌。此代码本身不会修改店铺 `.env` 凭据文件，也不会自动开启 SaaS 的生产开关。
