# P2-B-005 RPA失败转人工页面变更记录

## 变更

- 新增 `frontend/src/api/rpaStability.js`。
- 新增 `frontend/src/mock/rpaStability.js`。
- 新增 RPA稳定性看板、尝试列表/详情、人工接管队列、账号锁、页面签名异常页面。
- 更新路由、README 和接口映射。

## 边界

- 页面为 internal 管理页面。
- 不调用 `/api/rpa/*` Agent 执行接口。
- 不访问 `/api/finance/*` 或 `/admin/`。
- 不模拟 RPA Agent token。
- 不执行真实RPA，不连接真实BigSeller。
- evidence/screenshot 仅为 demo 或 placeholder。

## 验证

- Agent执行接口和敏感字段扫描：未发现实际请求 `/api/rpa/*`、claim、heartbeat/logs/screenshots/complete/fail、finance/admin、Agent token、Cookie 或 Session。
- 说明：页面展示 `heartbeat_at` 字段和 `/api/rpa/*` 边界说明，不构成 Agent 执行调用。
- 禁止目录扫描：`backend/`、`rpa-agent/`、`docs/04_rpa/`、`.env`、`.env.example`、`docker-compose.yml`、`requirements.txt` 无 diff。
- `npm run build`：成功。
- 构建 warning：主 JS chunk 约 `1,164.29 kB`，仍超过 500 kB；阶段2后续由 P2-B-006 处理或记录为观察项。
