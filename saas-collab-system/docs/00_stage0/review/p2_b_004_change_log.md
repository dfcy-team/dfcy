# P2-B-004 供应商绩效页面变更记录

## 变更

- 新增 `frontend/src/api/supplierPerformance.js`。
- 新增 `frontend/src/mock/supplierPerformance.js`。
- 新增内部绩效看板、列表、详情和供应商自查/历史页面。
- 更新路由、README 和接口映射。

## 边界

- 内部页面使用 `/api/internal/suppliers/performance/*`。
- 供应商页面使用 `/api/external/supplier/performance/*`。
- 供应商页面不访问 internal/finance/admin，不传入其他 supplier_id。
- 不展示财务敏感信息，不使用真实供应商资料。

## 验证

- external 页面路径扫描：供应商自查页面仅使用 `/api/external/supplier/performance/*` 方法；不传入其他 `supplier_id`。
- 说明：`supplierPerformance.js` 同时包含内部绩效方法和 external 自查方法，页面按路由边界分别引用。
- 禁止目录扫描：`backend/`、`rpa-agent/`、`docs/04_rpa/`、`.env`、`.env.example`、`docker-compose.yml`、`requirements.txt` 无 diff。
- `npm run build`：成功。
- 构建 warning：主 JS chunk 约 `1,159.07 kB`，仍超过 500 kB；阶段2后续由 P2-B-006 处理或记录为观察项。
