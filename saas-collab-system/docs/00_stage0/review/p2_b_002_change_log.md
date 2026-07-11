# P2-B-002 商品状态看板变更记录

## 变更

- 新增 `frontend/src/api/productStatus.js`。
- 新增 `frontend/src/mock/productStatus.js`。
- 新增页面：
  - `ProductStatusDashboard.vue`
  - `ProductStatusRecommendationList.vue`
  - `ProductStatusRecommendationDetail.vue`
  - `ProductStatusTransitionHistory.vue`
- 更新路由、`frontend/README.md` 和接口映射。

## 边界

- API/RPA/人工来源只形成状态建议。
- 前端不自动确认状态。
- 清仓、停售、归档必须显示高风险确认提示。
- 确认/拒绝接口保留预期路径和 Mock fallback，未标记 connected。
- 不连接真实平台，不写入真实销售数据。

## 验证

- 敏感字段和越界路径扫描：未发现 external、finance、admin、真实 URL 或密钥字段。
- 禁止目录扫描：`backend/`、`rpa-agent/`、`docs/04_rpa/`、`.env`、`.env.example`、`docker-compose.yml`、`requirements.txt` 无 diff。
- `npm run build`：成功。
- 构建 warning：主 JS chunk 约 `1,149.04 kB`，仍超过 500 kB；阶段2后续由 P2-B-006 处理或记录为观察项。
