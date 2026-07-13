# P3-A-002 库存预警计算服务变更日志

## 交付

- 新增 `InventoryAlertRule`，支持 tenant、规则编码、预警类型、阈值配置、级别、静默分钟、启用状态、版本和生效时间。
- 新增 `InventoryAlert`，记录 SPU/SKU、库存输入、日均销量、覆盖天数、阈值、去重键、负责人、静默和关闭状态。
- 新增 `InventoryAlertEvent`，记录触发、去重、分配、静默和关闭事件及操作人。
- 支持 `stockout_risk`、`overstock_risk`、`low_coverage`、`slow_moving` Mock 评估。
- 评估只接受当前时间已生效的最新启用规则版本；重复风险按去重键记录事件，静默期抑制通知占位，关闭后风险重新出现会开启新的处理周期。
- 新增 inventory 预警列表、详情、Mock 评估、人工分配、静默和关闭接口。
- 新增 `alerts.view`、`alerts.evaluate`、`alerts.manage` 动作权限，并应用 tenant 与 DataScope。

## 安全边界

- 预警只记录风险和人工处理状态，不创建采购订单、不通知真实供应商、不触发 RPA。
- 只允许授权 internal 用户访问；external 与 RPA 拒绝。
- 只使用 mock/demo/placeholder 数据，不连接真实平台。

## 验证

- P3-A-002 定向测试：`8 passed`。
- 全量 pytest：`180 passed`。
- Django check：通过，`0 issues`。
- 迁移一致性：通过，`No changes detected`。
- 全新临时数据库迁移与权限目录检查：通过，`Permission catalog is complete`。
- 安全文件扫描与 Docker Compose 配置：通过。
- `git diff --check`：通过。
