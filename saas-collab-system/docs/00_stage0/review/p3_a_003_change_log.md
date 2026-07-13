# P3-A-003 补货建议服务变更日志

## 交付

- 新增 tenant 级 `ReplenishmentRecommendation`，记录 SPU/SKU、库存输入、日均销量、安全库存天数、供应商交期、补货周期、建议数量/日期、置信度、原因、状态和审核信息。
- 使用阶段3冻结公式生成 Mock 建议，相同输入快照使用稳定哈希幂等。
- 数据缺失时生成 `insufficient_sales_data`、数量为 0、置信度为 0 的明确建议，不静默推断。
- 新增列表、详情、Mock 评估、接受和拒绝接口，并应用 tenant、DataScope 和动作级权限。

## 安全边界

- `accepted` 仅改变建议状态并写审计，不创建 PurchaseOrder、供应商任务或 RPA 任务。
- 不通知真实供应商，不连接真实平台，只使用 mock/demo/placeholder 输入。
- external、supplier 和 RPA 用户不能访问 internal 补货接口。

## 验证

- P3-A-003 定向测试：`13 passed`。
- 全量 pytest：`193 passed`。
- Django check：通过，`0 issues`。
- 迁移一致性：通过，`No changes detected`。
- 全新临时数据库迁移与权限目录检查：通过，`Permission catalog is complete`。
- 安全文件扫描、Docker Compose 配置与 `git diff --check`：通过。
