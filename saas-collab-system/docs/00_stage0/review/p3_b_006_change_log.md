# P3-B-006 配置中心页面变更日志

## 变更范围

- 新增配置中心列表和配置版本历史页面。
- 展示配置草稿、范围、默认值摘要、版本、生效、审批、审计和回滚记录。
- 提交审批与回滚操作仅为 pending 占位。

## API 状态

- `/api/internal/config/items/`：`mock`。
- `/api/internal/config/versions/`：`mock`。
- 开发A接口尚未合并，未标记 `connected`。

## 安全边界

- 不提供真实平台密钥、银行密码、Cookie、Session 或明文 Token 输入框。
- 敏感配置只展示引用状态或脱敏摘要。
- 前端不承担配置权限和系统安全下限判断。

## 验证记录

- `npm install`：成功，`0 vulnerabilities`。
- `npm run build`：成功，耗时约 6.52 秒。
- Element Plus vendor chunk 约 `923.28 kB`，warning 不阻断。
- API边界扫描未发现 external、finance、RPA 或 admin 路径。
- 固定字符串扫描未发现密码、密钥或凭据输入控件。
- `dist`、`node_modules` 和 `.npm-cache` 均被忽略且未跟踪。
