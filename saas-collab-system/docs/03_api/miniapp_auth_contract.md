# 小程序认证 API 合同 V1

## 1. 范围与状态

本合同冻结小程序专用认证端点，不复用管理端 `/api/internal/auth/*`。后端支持：

- `disabled`：关闭并拒绝全部 code。
- `sandbox`：仅用于开发测试的预绑定摘要身份。
- `platform`：服务端调用微信 `code2Session`，只使用返回的 openid 摘要查找预绑定用户。

生产环境默认仍为 `disabled`。只有显式设置 `MINIAPP_AUTH_MODE=platform` 且服务端已注入 `MINIAPP_APP_ID`、`MINIAPP_APP_SECRET` 时才能启动；缺失配置会在启动阶段失败关闭。

## 2. 统一响应

所有端点返回：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

失败时 `success=false`，不得返回 `session_key`、AppSecret、原始平台 subject、完整令牌日志或内部异常。

## 3. 端点

### `GET /api/miniapp/health/`

返回非敏感能力状态：`sandbox`、`platform` 或 `disabled`。平台模式只返回 `provider_exchange=wechat-code2session`，不返回 AppID、AppSecret、openid 或 `session_key`。

### `POST /api/miniapp/auth/login/`

请求：

```json
{"code": "one-time-platform-code"}
```

成功 `data`：

- `access_token`
- `refresh_token`
- `expires_in`
- `expires_at`
- `user.id`
- `user.username`
- `user.displayName`
- `user.userType`
- `user.tenant`
- `user.roles`
- `user.permissions`
- `user.dataScope`

沙箱仅接受 `sandbox:<subject>`，且 subject 必须预先绑定。平台模式只接受 `wx.login` 生成的一次性 code，由后端固定访问微信 `code2Session` 地址。两种模式的绑定记录都只保存 SHA-256 摘要，不保存原始 subject/openid。

### `POST /api/miniapp/auth/refresh/`

请求：

```json
{"refresh_token": "..."}
```

仅接受带 `channel=miniapp` 声明的刷新令牌。管理端刷新令牌不得跨通道使用。

### `GET /api/miniapp/auth/me/`

需要小程序通道访问令牌。管理端、RPA 或其他通道令牌返回 403。

## 4. 沙箱绑定

仅由受控运维人员在开发/测试环境执行。生产 openid 也必须通过受控身份绑定流程预绑定：

```bash
python manage.py bind_miniapp_identity --username demo --subject device-001
```

命令输出只显示摘要前缀，不回显原始 subject。RPA 用户禁止绑定。执行记录及终端历史不得留存真实 openid。

## 5. 错误码

- `MINIAPP_AUTH_DISABLED`：能力关闭或平台凭据未配置
- `MINIAPP_CODE_INVALID`：code 格式无效、已使用或微信判定无效
- `MINIAPP_PROVIDER_UNAVAILABLE`：微信服务超时、返回不可解析结果或系统繁忙
- `MINIAPP_IDENTITY_UNBOUND`：身份未绑定、停用或用户不可用
- `MINIAPP_TOKEN_INVALID`：令牌不是小程序通道或用户已不可用
- `AUTH_REQUIRED`：缺少或过期访问令牌
- `PERMISSION_DENIED`：令牌通道不符

## 6. 验收

- 登录、刷新、当前用户均使用统一响应。
- 原始 subject 和 `session_key` 不进入响应、日志和数据库。
- 管理端 JWT 不能访问小程序 `/me`，管理端刷新令牌不能访问小程序刷新端点。
- `disabled` 模式不交换任何 code。
- `platform` 模式使用固定微信 HTTPS 地址和 2–15 秒受控超时，不对无效一次性 code 自动重试。
- 微信 `session_key` 只存在于单次后端内存响应解析过程，不写数据库、不签发给客户端。
- AppSecret 只允许由后端部署密钥注入，小程序包、前端构建、日志和响应中均不得出现。
- 用户、租户、角色、权限和数据范围均来自服务端可信数据。
