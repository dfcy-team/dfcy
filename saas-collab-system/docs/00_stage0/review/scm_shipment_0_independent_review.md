# SC-SHIPMENT-0 独立审核

- 日期：2026-08-08
- 结论：`APPROVED_FOR_LOCAL_IMPLEMENTATION`

## 审核发现与关闭

1. `P1-001` 复用 `SupplierShipment` 会让供应商自报记录成为权威发运单：合同明确新建 shipping 聚合，关闭。
2. `P1-002` 任意 shipment ID 可形成孤立或跨租户消费：合同要求 typed aggregate、同租户/版本/状态校验，关闭。
3. `P1-003` consolidation transfer 可能提前增加 shipped：合同冻结只有 shipment dispatch commit 增加 shipped，关闭。
4. `P1-004` 部分转移会错误把 consolidation 标为全部 transferred：合同要求按 allocation 派生，仅全部完成才更新聚合终态，关闭。
5. `P1-005` 多次发货可能重复计数：合同要求结构化箱集合、独立动作幂等和每箱单次 shipment commit，关闭。
6. `P1-006` 报关/清货状态混淆：合同冻结 customs_declared 与 warehouse_cleared 为不同顺序节点，关闭。
7. `P1-007` 多供应商 shipment 使用 OWN/DEPARTMENT 泄漏数据：合同只允许 ALL/完整 CUSTOM，并以全部当前及历史箱维度鉴权，关闭。

## P2 决定

- 自动承运商/报关同步：延期，首期人工受控引用。
- 已 transfer 未 dispatch 的反向转移：延期到独立补偿合同，首期禁止。
- 费用、税费和结算：不纳入 shipment 首期。
- 供应商查看同柜进度：只允许本人裁剪状态，不返回同柜参与方或汇总。

## 准入结论

允许进入 `SC-SHIPMENT-1` 本地模型、迁移、领域服务、权限种子和 MySQL 并发门禁。暂不准入 API、Web/小程序页面、第三方连接或生产数据。
