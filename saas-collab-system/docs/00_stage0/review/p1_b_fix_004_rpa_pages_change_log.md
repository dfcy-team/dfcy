# P1-B-FIX-004 RPA管理页面联调整改记录

## 整改内容

- 替换 RPA 页面 `Stage0Placeholder` 展示。
- `RPATaskList.vue`：loading、error、empty、list/table、status 标签。
- `RPATaskDetail.vue`：detail、payload/result JSON 格式化、screenshots 占位、logs 占位。
- 重试/人工接管按钮仅为 pending/mock，占位不触发真实执行。
- 更新 `frontend/src/api/rpa.js` 和 `frontend/src/mock/rpa.js`。

## 边界

- 前端 RPA 页面是 internal 管理后台页面。
- 若 `/api/internal/rpa/tasks/` 尚未实现，则保留 pending/mock。
- 前端不得模拟 RPA Agent token。
- 前端不得调用 `/api/rpa/tasks/claim/`。
- 前端不得调用 heartbeat/logs/screenshots/complete/fail 作为 Agent 执行行为。
- 前端不得访问 `/api/finance/*` 或 `/admin/`。
- 前端不得执行真实 RPA，不连接真实 BigSeller。

## 安全确认

- 未提交真实 RPA 脚本。
- 未提交真实 BigSeller 账号、密码、Cookie、Session。
- 未提交真实截图或真实页面快照。
