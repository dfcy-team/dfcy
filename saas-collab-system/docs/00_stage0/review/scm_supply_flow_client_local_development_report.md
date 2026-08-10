# SC-SUPPLY-FLOW-CLIENT-3/4 本地开发报告

## 范围与边界

本轮在不改变后端领域不变量、Web/小程序之外目录和既有 API 合同的前提下，补齐 API2 的客户端最小适配；仅对 supplier assignment DTO 做了向后兼容的 accepted-evidence 裁剪字段补充：

- 内部 Web 新增集货站点、集货单和发运单控制台；列表、创建、整箱分配/转入、发布、收货、异常、Ready、取消、报关、分批发运、到岸、到仓、清关等动作均调用 `/api/internal/supply-chain/...`，不直接写表。
- Web 动作按后端 exact permission code 显示，写请求携带 `expected_version` 和基于资源/动作/请求体的稳定 `Idempotency-Key`；操作成功后才重新读取状态，409/网络错误保留在错误状态。
- 小程序新增供应商本人 assignment 列表/详情，站点地址和联系信息使用后端裁剪 DTO；后端 DTO 仅补充当前 release 下的 `accepted_evidence_ids`/`accepted_evidence[{id,state}]`，不返回 hash 或业务绑定字段。首次交接从 accepted 集合读取，冻结的历史 `evidence_ids` 不再被误用；未 accepted 不能提交交接。
- shipment 状态严格采用后端 `draft/loading/customs_declared/dispatched/port_arrived/warehouse_arrived/warehouse_cleared/cancelled`；转入时区分集货 allocation ID 与物理箱 ID，dispatch 只提交 `transferred` 的 shipment allocation，支持剩余箱再次 dispatch。
- 下载 ticket、Mock 环境上传成功和生产对象存储均保持关闭。只有 `development + localUploadEnabled=true` 的显式本地开关才显示 JPEG/PNG 选择和 `content_base64` 适配；HEIC、超 10 MiB、相机/相册权限拒绝均给出明确提示。默认只读并提示“功能未启用”。

## 主要文件

- Web：`frontend/src/api/supplyFlow.js`、`frontend/src/mock/supplyFlow.js`、`frontend/src/views/supply-chain/SupplyFlowConsole.vue`、`frontend/src/router/index.js`、`frontend/src/router/menu.js`。
- 小程序：`miniapp/services/consolidations.js`、`miniapp/mock/consolidations.js`、`miniapp/pages/consolidations/*`、`miniapp/pages/consolidation-detail/*`、`miniapp/config/index.js`、`miniapp/app.json`、`miniapp/pages/home/*`。
- API2 DTO 最小调整：`backend/apps/consolidation/api_serializers.py`；回归测试补在 `backend/tests/test_sc_consolidation_attach_1_local.py`。
- 测试：`frontend/tests/supply-flow-client.spec.js`、`miniapp/tests/consolidations.test.js`。

## 验证

```text
cd frontend
npx vitest run tests/supply-flow-client.spec.js       # 3 passed
npm run build                                         # passed

cd miniapp
npm test                                              # 29 passed
npm run validate                                      # passed，10 pages / 32 JavaScript files
```

前端全量 `npm test` 仍有仓库既有失败（与本轮文件无关）：`product-coding.spec.js`、`ui-p5-business-mainflow.spec.js`、`ui-p3-rpa-task-device.spec.js` 的历史断言漂移，以及 `ui-p4-workflow-collaboration.spec.js`、`development-competitor.spec.js` 连接到未启动的旧本地服务导致的网络/超时失败；本轮定向测试和生产构建均通过，未伪造全量通过。

后端 DTO 回归：`tests/test_sc_consolidation_attach_1_local.py` `9 passed`；此前 API2/consolidation/shipment 合并定向回归保持通过。

## 残余风险

- 后端 supplier assignment DTO 当前不返回 `release_version` 时，小程序会禁用交接提交并提示缺少发布版本，避免猜测版本造成错误写入。
- 本轮未连接真实微信平台、相机硬件、对象存储或生产 API；弱网重试依赖统一 request client，写操作在业务服务层使用稳定幂等键。
- Web 页面提供受控动作入口但不替代后端租户、DataScope、版本和状态校验；下载 ticket 仍以 503 fail-closed 呈现。
