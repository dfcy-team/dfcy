# PR-A3 销售与库存离线导入回滚指南

适用范围：`A-PR3-P1-OFFLINE-SALES-INVENTORY-IMPORT` Draft。此指南不授权生产发布。

## 立即停止

1. 设置 `PR_A3_SYNTHETIC_IMPORT_ENABLED=false` 并重启后端。
2. 确认 POST import/retry 返回受控 disabled 错误；查询端仍可保留用于证据检查。
3. 确认没有 scheduler、webhook、真实平台网络或平台写路径需要额外停止。

## 代码回滚

1. 从已批准的前一固定 artifact 恢复应用代码和 URL/settings 注册。
2. 运行 Django check 与 migration plan，确认目标仍为 Production synchronization OFF。
3. 不删除批次、订单、退款、库存或游标证据来掩盖失败。

## 数据库回滚

`marketplace_imports.0001_initial` 的反向迁移会删除本模块全部表，只能在数据负责人确认没有需保留的审计/导入证据、完成受控备份并取得独立批准后执行。通常应保留 schema 与证据，仅关闭开关并回滚应用 artifact。

回滚后重跑 Django check、migration drift、focused test、CI guard 和凭据/禁止制品扫描。任何真实平台 adapter、真实 payload 或 Production 状态均不属于本回滚范围。
