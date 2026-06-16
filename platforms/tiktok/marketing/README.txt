鼎峰 TikTok 广告数据分析（Marketing API）
==========================================

OAuth 入口:  https://dingfengchuangyu.top/ads
授权回调:    https://dingfengchuangyu.top/callback  （与 Shop 共用，靠 state=ads 区分）

配置
----
复制 app.env.example 为 app.env，填写 APP_SECRET。

授权后 token 保存在 tokens/marketing_token.json
广告账户列表在 advertisers.json

与 Shop 授权独立，需单独点击「连接广告账户」。
