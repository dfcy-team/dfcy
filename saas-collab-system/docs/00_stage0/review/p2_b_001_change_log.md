# P2-B-001 API同步状态页面变更记录

## 变更

- 新增通用组件 `frontend/src/components/Phase2DataPage.vue`。
- 扩展 `frontend/src/api/integrations.js`，保留阶段2预期 internal API 路径与 Mock fallback。
- 扩展 `frontend/src/mock/integrations.js`，使用 demo/mock 脱敏数据。
- 新增页面：
  - `IntegrationConfigList.vue`
  - `IntegrationConfigDetail.vue`
  - `SyncJobList.vue`
  - `SyncRunList.vue`
  - `SyncRunDetail.vue`
- 更新路由、`frontend/README.md` 和 `docs/00_stage0/frontend_api_mapping.md`。

## 安全边界

- 不展示 `credential_ciphertext`。
- 不展示明文 API Key、API Secret、Token、Cookie 或 Session。
- 不提供真实平台连接测试。
- 生产环境接入显示需专项安全评审。
- 当前接口状态标记为 `pending`，页面使用 Mock fallback。

## 验证

- 敏感字段扫描：未发现 `credential_ciphertext`、明文 API Key、API Secret、Token、Cookie、Session、password 或 secret。
- 禁止目录扫描：`backend/`、`rpa-agent/`、`docs/04_rpa/`、`.env`、`.env.example`、`docker-compose.yml`、`requirements.txt` 无 diff。
- `npm run build`：成功。
- 构建 warning：主 JS chunk 约 `1,144.50 kB`，仍超过 500 kB；阶段2后续由 P2-B-006 处理或记录为观察项。
