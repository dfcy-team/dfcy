# 小程序工程底座

原生微信小程序工程，作为 SaaS 协同系统的移动端技术底座。当前阶段只承载公共能力和可验证的示例页面，不自动执行真实生产发布。

## 已实现

- 四环境配置：`development`、`test`、`preview`、`production`
- 默认 Mock 登录，支持 `/api/miniapp/auth/*` 沙箱及微信 `code2Session` 专用认证端点
- 统一请求头、请求 ID、响应信封、错误模型和写操作幂等键
- 401 单次刷新与并发刷新收敛基础
- 会话恢复、过期判断和退出清理
- 结构化日志及 Token、密码、`session_key` 等敏感字段脱敏
- 启动页、登录页、工作台、运行诊断页
- 发布合同只读工作台与合同详情页
- loading、empty、error、offline、degraded 状态组件
- Node 内置测试与工程静态校验，无第三方构建依赖

## 本地检查

需要 Node.js 18 或更高版本：

```bash
cd miniapp
npm run check
```

该命令会检查 JSON、页面声明、JavaScript 语法、真实 AppID、越界 API 路径并执行单元测试。

## 微信开发者工具

1. 导入 `miniapp/` 目录。
2. 仓库内 `project.config.json` 固定使用 `touristappid`，真实 AppID 只写入被忽略的 `project.private.config.json`。
3. 默认环境在 `config/runtime.js` 中为 `development`，默认启用 Mock。
4. 真实环境必须由受控流水线注入环境名和 API 域名；代码库不得保存 AppSecret、上传私钥、平台令牌或 `session_key`。

### Windows 本地 HTTPS 联调

本机开发使用受信任的 mkcert 证书，证书及私钥位于被 Git 忽略的
`miniapp/.certs/`。当前端口约定：

- Django API：`http://127.0.0.1:8002`
- 小程序 HTTPS API：`https://127.0.0.1:9444`

当 `.env` 中的 MySQL 主机使用 Docker 服务名 `mysql` 时，从项目根目录
启动本机 Django 前先覆盖当前进程的数据库主机：

```powershell
cd backend
$env:DB_HOST = "127.0.0.1"
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8002 --noreload
```

另开一个 PowerShell 窗口启动 HTTPS 代理：

```powershell
cd miniapp
npm run https:proxy
```

验证地址：

```text
https://127.0.0.1:9444/api/miniapp/health/
```

该回环地址只用于微信开发者工具模拟器，不用于真机。真机联调需要可由手机
访问、证书链受信任并已配置为微信合法域名的 HTTPS 地址。

本地后端沙箱联调时，可将 `config/runtime.js` 改为：

```js
module.exports = Object.freeze({
  environment: "development",
  useMock: false,
  authMode: "sandbox",
  sandboxSubject: "device-001"
});
```

随后由后端管理员预先执行身份绑定。`sandboxSubject` 是测试标识，不得使用真实 openid。

真实微信登录联调时：

1. 将真实 AppID 写入本机的 `project.private.config.json`，不要修改仓库中的 `touristappid`。
2. 参考 `config/runtime.platform.example.js`，临时把 `config/runtime.js` 切换为本地 `platform` 模式。
3. 后端通过部署密钥注入 `MINIAPP_APP_ID`、`MINIAPP_APP_SECRET`，设置 `MINIAPP_AUTH_MODE=platform`。
4. 后端管理员把微信 openid 的 SHA-256 摘要绑定到目标租户用户；数据库和日志均不得保存或输出原始 openid、`session_key`、AppSecret。
5. 在微信开发者工具中重新编译，登录页触发 `wx.login` 后检查 `/api/miniapp/auth/login/`、`/me/` 和发布合同只读接口。

仓库不会保存真实 AppID、AppSecret 或 openid。没有真实凭据和预绑定身份时，只能完成模拟交换测试，不能伪造“真实登录成功”。

## API 边界

- 允许：`/api/miniapp/*`
- 禁止：`/api/internal/*`、`/api/rpa/*`、`/api/finance/*`
- 小程序只提交 `wx.login` 返回的一次性 code；code 换取平台身份和服务端会话必须由后端完成。
- 页面可根据权限结果控制体验，但最终授权、`tenant` 和 `data_scope` 校验必须由服务端完成。

## 当前能力状态

- 工程底座：`connected`
- 小程序认证：默认 `mock`；支持后端 `sandbox` 和受控 `platform/code2Session`
- 发布合同：默认使用脱敏 Mock；后端联调模式提供只读合同、门禁和审批信息
- 真实平台发布：`disabled`；小程序备案与微信平台审核完成前不开放上传、提交审核或发布操作
