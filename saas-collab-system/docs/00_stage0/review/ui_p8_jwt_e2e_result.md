# UI-P8 真实 JWT 浏览器 E2E 结果

## 1. 执行信息

- 日期：2026-07-20
- 分支：`feature/ui-p8-production-pilot-security-readiness`
- 模式：`VITE_USE_MOCK=false`
- 前端：本地 Vite 受控测试服务
- 后端：本地 Django 受控测试服务与本地 SQLite 测试数据
- 数据：仅 demo tenant、受控环境、受控 target alias 和 placeholder evidence reference

## 2. 实际结果

| 场景 | 结果 | 证据 |
|---|---|---|
| JWT 登录 | PASS | `/api/internal/auth/login/` 返回统一成功结构 |
| 当前用户 | PASS | `/api/internal/auth/me/` 返回当前 tenant、角色、权限和 data_scope |
| 受保护路由 | PASS | 成功进入 `/pilot/verification-runs`，未回退登录页 |
| 真实列表 GET | PASS | 页面从后端读取空列表并显示 empty 状态 |
| 真实创建 POST | PASS | 创建 demo 验证草稿并显示 `VER-*` 编号、pilot 环境和版本 1 |
| 真实编辑 PATCH | PASS | 编辑受控 target alias 后列表版本由 1 更新为 2 |
| 浏览器日志 | PASS | 最终页面无 error/warn |
| Mock 回退 | PASS | 修正 CORS 自定义头后，真实请求不再因预检失败回退 Mock |

## 3. 修正记录

浏览器首次创建时发现 `Idempotency-Key` 和 `X-Request-ID` 未列入 CORS 允许头，预检失败导致前端回退 Mock。已在 Django CORS 配置中加入两个合同头，重启后真实 POST/PATCH 均成功。

## 4. 边界确认

- 未连接真实平台、生产数据库、银行、支付、对象存储或 RPA Agent。
- 未使用真实账号、Token、Cookie、Session、API Key、API Secret 或业务数据。
- 本结果仅证明本地 JWT 与 UI-P8 API 合同链路可运行，不代表远端 CI、生产发布或真实平台准入通过。
- 远端 CI 状态：待提交当前分支并创建 PR 后验证。
