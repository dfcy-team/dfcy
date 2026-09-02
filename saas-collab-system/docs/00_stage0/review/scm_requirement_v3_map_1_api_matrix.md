# SCM-V3-MAP-1 API动作矩阵

`PROPOSED`路径只冻结合同，不表示已实现。所有写请求要求 `Idempotency-Key`；更新/动作同时要求适用的`expected_version`。

| API ID | Method / Path | Channel | permission/capability | 请求→响应、HTTP状态与实现状态 |
| --- | --- | --- | --- | --- |
| `API-PO-001` | POST `/api/internal/purchasing/supply-orders/{id}/actions/assign-shipping-route/` | internal | `supply.purchase_order.assign_shipping_route` | route/mode,expected_version→200 order DTO；冲突409；既有路径/扩展mode |
| `API-PO-002` | POST `/api/miniapp/supply-chain/orders/{id}/actions/complete-production/` | miniapp | supplier binding | items,expected_version→200 order DTO；冲突409；既有路径/适配源7.10 |
| `API-PACK-001` | GET/POST `/api/miniapp/supply-chain/packing/batches/` | miniapp | packing capability | GET→200 page；POST→201 batch；冲突409；既有/扩展开关 |
| `API-PACK-002` | POST `/api/miniapp/supply-chain/packing/batches/{id}/actions/complete/` | miniapp | capability | expected_version→200 frozen batch；冲突409；既有 |
| `API-PACK-003` | POST `/api/miniapp/supply-chain/packing/batches/{id}/actions/generate-label/` | miniapp | capability | snapshot→200 PDF metadata/ticket；既有 |
| `API-DIR-001` | POST `/api/internal/supply-chain/direct-shipments/` | internal | `supply.direct_shipment.create` | box_ids,carrier_id,tracking,dates→201 DirectShipment；409冲突；PROPOSED |
| `API-DIR-002` | POST `/api/external/supplier/direct-shipments/{id}/attachments/upload-sessions/` | supplier_web | supplier capability | type/file metadata→token/session；PROPOSED |
| `API-DIR-003` | POST `/api/external/supplier/direct-shipments/{id}/actions/submit-review/` | supplier_web | supplier capability | evidence_ids,expected_version→pending review；PROPOSED |
| `API-DIR-004` | POST `/api/internal/supply-chain/direct-shipments/{id}/actions/review/` | internal | `supply.direct_shipment.review` | approved/rejected/reason→200 DTO；409冲突；PROPOSED |
| `API-DIR-005` | POST `/api/internal/supply-chain/direct-shipments/{id}/actions/dispatch/` | internal | `supply.direct_shipment.dispatch` | expected_version→200 in_transit；409冲突；PROPOSED |
| `API-DIR-006` | POST `/api/internal/supply-chain/direct-shipments/{id}/actions/deliver/` | internal | `supply.direct_shipment.deliver` | delivered_at/evidence→200 delivered；409冲突；PROPOSED |
| `API-CONS-001` | `/api/internal/supply-chain/consolidations/...`及miniapp assignments | existing channels | `supply.consolidation.*`/binding | 沿用当前真实路径和裁剪DTO |
| `API-SHIP-001` | POST `/api/internal/supply-chain/shipments/{id}/actions/{customs-declare|dispatch|port-arrival|warehouse-arrival|warehouse-clearance}/` | internal | 对应独立`supply.shipment.*` | expected_version/evidence→200 Shipment DTO；409冲突；既有 |
| `API-CONT-001` | GET/POST `/api/internal/supply-chain/containers/` | internal | view/create | filters/body→page/detail；PROPOSED |
| `API-CONT-002` | POST `/api/internal/supply-chain/containers/{id}/boxes/` | internal | allocate | box_ids,expected_version→allocations；PROPOSED |
| `API-CONT-003` | POST `/api/internal/supply-chain/containers/{id}/actions/{review|customs|dispatch|arrival|clearance}/` | internal | 对应container permission | action DTO→Container；PROPOSED |
| `API-CHG-001` | GET/POST `/api/external/supplier/containers/{id}/box-change-requests/` | supplier_web | submit/view capability | box_ids,reason>=10→request；PROPOSED，源7.7 |
| `API-CHG-002` | POST `/api/internal/supply-chain/container-box-change-requests/{id}/actions/review/` | internal | `supply.container.box_change.review` | decision/reason/version→request；PROPOSED |
| `API-ACC-001` | POST `/api/miniapp/auth/login/` | miniapp | platform code | wx code→200 tokens；401/403认证失败；既有，替代Taro/Supabase |
| `API-ACC-002` | POST `/api/miniapp/account/password/` | miniapp | authenticated self | old/new→204并吊销会话；400校验失败；PROPOSED，源7.8 |
| `API-ACC-003` | POST `/api/miniapp/account/wechat-binding/` | miniapp | authenticated self | one-time code→binding status；PROPOSED |
| `API-NOT-001` | GET/PUT `/api/miniapp/notification-preferences/` | miniapp | authenticated self | notify_order/announcement→preference；PROPOSED，源7.9 |
| `API-COST-001` | POST `/api/internal/supply-chain/cost-allocations/actions/recalculate/` | internal | `supply.cost.allocate` | scope,basis,formula_version→preview/commit；PROPOSED |
| `API-CLEAR-001` | GET/POST `/api/internal/supply-chain/clearances/`及`/{id}/actions/complete/` | internal | clearance permissions | source/items/version→DTO；PROPOSED |
| `API-REPORT-001` | GET `/api/internal/supply-chain/reports/supplier-rating/` | internal | `supply.report.supplier_rating.view` | filters/sort/page→200 rows+summary；PROPOSED |
| `API-REPORT-002` | POST `/api/internal/supply-chain/reports/supplier-rating/exports/` | internal | `supply.report.supplier_rating.export` | filter snapshot→202 job/ticket；PROPOSED |

未在单行另列时，GET成功200、创建成功201、无响应动作204、异步任务202；校验400、未认证401、通道/能力拒绝403、对象越权或不存在404、版本/幂等/状态冲突409、限流429。锁等待/死锁使用确定性可重试冲突且客户端保持同一幂等键。所有读取按permission-specific DataScope过滤；响应不得泄露其他供应商、内部备注、token、hash或完整PII。
