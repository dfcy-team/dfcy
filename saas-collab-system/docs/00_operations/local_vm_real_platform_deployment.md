# 本地双 VM SaaS 正式平台接入配置放置说明

适用域名：`https://dingfengchuangyu.com`。本说明只覆盖 Shopee / TikTok Shop OAuth、授权店铺发现和最小只读验证，不批准订单、库存、Webhook、定时任务或平台写操作。

## 放置位置

应用 VM 沿用 `deploy/pilot/application/`，数据库位于独立数据库 VM：

1. 从 `env.pilot.example` 复制应用 VM 本地文件 `.env.pilot`；该文件不得提交 Git，权限必须为 `600`。
2. 固定镜像 digest、Git SHA、数据库连接和 TLS 文件路径按现有 pilot 发布流程填写。
3. 平台公开标识、地区、回调地址和域名白名单填写在 `.env.pilot`。
4. App Secret、access token、refresh token、authorization code 不得写入 `.env.pilot`。这里只能填写 custody 返回的 opaque reference。
5. 应用、数据库的完整私网地址、SSH 端口和账号只保留在受控运维移交文件及服务器本地配置中，不写入 Git。

两个平台必须分别在开发者后台精确登记：

```text
Shopee: https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/shopee/
TikTok: https://dingfengchuangyu.com/api/internal/integrations/store-authorizations/oauth/callback/tiktok/
```

Shopee 试点地区为 `PH`、`TH`、`MY`；TikTok Shop 对应应用市场为 `ROW`。每次 OAuth 发起仍必须携带具体店铺地区，不能用一个店铺的验证结果提升其他地区或租户。

## 凭据边界

当前本地受控运行时使用 `LIVE_CUSTODY_BACKEND=file` 与独立宿主机目录。该目录不得挂载给 Nginx、前端或数据库；SaaS 数据库只保存引用、mask、版本、状态和时间戳。批准的 HTTPS custody API 仍可作为替代部署方案。

如果不部署 custody 服务，必须保持：

```text
LIVE_CUSTODY_BACKEND=refuse
PLATFORM_NETWORK_MODE=
LIVE_PLATFORM_SECURITY_APPROVED=false
```

此时系统会安全拒绝真实平台请求，能力状态保持 `pending/mock`，不能宣称已连接。不得改为把秘密写入 `.env`、数据库或代码。

## 受控启用顺序

1. 构建并记录来自 Review SHA 的不可变 backend/frontend 镜像 digest。
2. 在本地双 VM 环境部署 MySQL 8.4、Redis、TLS 和批准的 custody 服务，确认数据库仅允许应用 VM 访问，custody 域名进入应用出口白名单。
3. 将平台后台当前合同中的 Shopee endpoint、TikTok revoke endpoint、最小 scopes 及公开应用标识写入应用 VM 本地 `.env.pilot`；秘密只由授权管理员注入 custody。
4. 确认两个 callback URL 从公网到 Django 均不再返回 404，并确认 Nginx 不记录 callback query。
5. 独立复核后才把 custody backend、合同批准和 live-test 两个开关改为启用值。
6. 按单平台、单试点店铺依次执行 OAuth、主体绑定、最小只读、refresh、并发 refresh、revoke、reauthorization 和全链路凭据扫描。

任一失败立即关闭 `PLATFORM_NETWORK_MODE` 和安全批准开关、阻断平台出口，并通过 custody/平台后台撤销对应引用或授权。Production 全量同步始终保持关闭。
