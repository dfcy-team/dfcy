# P3-B-003 库存预警与补货建议页面变更日志

## 变更范围

- 新增库存预警与补货建议页面。
- 展示建议数量、日期、置信度、原因、数据质量和证据。
- 新增人工确认占位提示，不执行真实业务动作。

## API 状态

- `/api/internal/replenishment/alerts/`：`mock`。
- `/api/internal/replenishment/suggestions/`：`mock`。
- 开发A接口尚未合并，未标记 `connected`。

## 安全边界

- 不自动生成采购订单。
- 不通知真实供应商。
- 不触发真实 RPA。
- 前端不实现真实权限或 tenant 过滤。

## 验证记录

- `npm install`：成功，`0 vulnerabilities`。
- `npm run build`：成功，耗时约 6.43 秒。
- Element Plus vendor chunk 约 `923.28 kB`，warning 不阻断。
- 扫描未发现 external、finance、RPA、admin 或采购单执行接口。
- `dist`、`node_modules` 和 `.npm-cache` 均被忽略且未跟踪。
