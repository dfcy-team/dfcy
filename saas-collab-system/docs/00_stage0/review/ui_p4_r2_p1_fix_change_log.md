# UI-P4 R2 P1 整改变更日志

## 1. 整改对象

依据 `ui_p4_arch_r2_recheck.md`，定向关闭：

- `UI-P4-R2-P1-001`：报表审计可经父级导出请求级联删除。

R2 报告保持原始 `CONDITIONAL_PASS` 结论，本日志不替代后续独立复审。

## 2. 修改文件

- `backend/apps/reports/models.py`
- `backend/apps/reports/migrations/0005_alter_reportexportauditlog_export_request_and_more.py`
- `backend/tests/test_ui_p4_workflow_collaboration.py`

## 3. 删除保护

- `ReportExportRequestQuerySet.delete()` 拒绝删除审计根对象。
- `ReportExportRequest.delete()` 拒绝实例删除。
- `ReportExportAuditLog.export_request` 从 `CASCADE` 改为 `PROTECT`。
- `ReportExportAuditLog.tenant` 从 `CASCADE` 改为 `PROTECT`。
- 即使绕过自定义 Manager，Django Collector 也会因保护外键拒绝删除导出请求或 tenant。
- tenant 生命周期必须采用归档或受控保留，不允许级联清除导出审计。

## 4. 新增测试

新增回归覆盖：

1. 导出请求实例删除返回 `ValidationError`。
2. 自定义 QuerySet 删除返回 `ValidationError`。
3. 通过 `_base_manager` 绕过 QuerySet 防护时返回 `ProtectedError`。
4. 删除 tenant 时返回 `ProtectedError`。
5. 所有删除尝试后，导出请求和审计记录仍存在。

## 5. 实际验证

- Django check：PASS，`System check identified no issues`。
- migration 一致性：PASS，`No changes detected`。
- UI-P4 专项 pytest：PASS，`15 passed`。
- 后端全量 pytest：PASS，`298 passed in 39.53s`。
- 独立内存数据库迁移和删除复测：PASS。
- 内存复测结果：实例/QuerySet 为 `ValidationError`，base manager/tenant 为 `ProtectedError`，`export_exists=True`，`audit_exists=True`。
- `git diff --check`：PASS；仅有工作区行尾格式提示。

## 6. 安全与范围确认

- 未修改前端、RPA Agent、`docs/04_rpa/` 或真实平台配置。
- 未新增真实账号、密码、Token、Cookie、Session、API Key、API Secret 或业务数据。
- 未接入真实微信、飞书、BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未启用自动采购、清仓、改价、真实 RPA 或资金操作。

## 7. 下一步准入判断

本轮代码和测试结果满足进入独立 `UI-P4-ARCH-R3` 的条件，但不直接等同于 UI-P4 正式收尾。R3 必须独立确认原 P1 全部关闭、迁移可应用、无新增 P0/P1，并再次核验最终文件范围后，方可提交和创建 UI-P4 PR。
