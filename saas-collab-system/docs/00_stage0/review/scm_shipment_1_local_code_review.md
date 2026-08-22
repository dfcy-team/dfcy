# SC-SHIPMENT-1 本地代码审核

- 日期：2026-08-08
- 结论：`PASS_FOR_API_GATE`

## 范围与路由

`luna-worker` 实现 shipping 模型、服务、迁移、权限种子和测试；主代理完成合同边界、P1 审核与复核。未实现 API、页面或第三方连接，未复用 `SupplierShipment` 作为权威发运聚合。

## P1 复核

1. typed shipment 现校验 region、route 及显式 origin site 与来源 consolidation site 一致，跨站点转移拒绝。
2. 报关引用 trim 后必须非空且不超过 128 字符；失败时状态和版本不变。
3. 第二批不同幂等键 dispatch 剩余箱已实证；显式箱集合全或无，未全 dispatch 不得到岸，全部 dispatch 后才允许推进。

## 验证

- SQLite shipment：`6 passed`。
- MySQL 8.4 shipment：`4 passed`。
- fresh MySQL migrations（含 shipping.0002）：通过。
- Django check 与 shipping/consolidation migration drift：通过。
- 临时数据库、容器、卷、缓存已清理，13312 空闲。

## 结论边界

允许进入 shipment/consolidation/attachment API、权限、DataScope 与三通道实现。未授权生产部署、自动报关、第三方货代/承运连接或其他公司货物明细入库。
