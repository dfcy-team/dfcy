# UI-P4 P1 整改变更日志

## 1. 整改对象

依据 `ui_p4_arch_r1_recheck.md`，定向整改以下两项 P1：

- `UI-P4-P1-001`：工作流审计仍可通过实例 `save()` 修改。
- `UI-P4-P1-002`：报表下载审计可删除，且失败下载尝试留痕不完整。

R1 报告保持原始 `CONDITIONAL_PASS` 结论，本日志不代替独立 R2 复审。

## 2. 修改文件

- `backend/apps/workflows/models.py`
- `backend/apps/reports/models.py`
- `backend/apps/reports/export_services.py`
- `backend/apps/reports/views.py`
- `backend/tests/test_ui_p4_workflow_collaboration.py`

## 3. P1 整改情况

| P1编号 | 整改结果 | 主要证据 | 待复审点 |
|---|---|---|---|
| UI-P4-P1-001 | 已整改 | 工作流审计拒绝已存在实例保存、同主键替换、QuerySet update/delete、bulk update/create 和实例 delete | 独立验证所有修改入口均不能改变已持久化记录 |
| UI-P4-P1-002 | 已整改 | 报表审计拒绝更新、批量写入和删除；下载成功及可安全识别的失败尝试均写入脱敏结果 | 独立验证失败审计持久化、不可删除且不产生资源存在性侧信道 |

## 4. 不可变审计规则

- 已持久化的 `WorkflowAuditEvent` 与 `ReportExportAuditLog` 不允许再次 `save()`。
- 伪造相同主键的新实例不能覆盖原审计记录，创建路径使用强制插入语义。
- QuerySet `update/delete/bulk_update/bulk_create` 和实例 `delete()` 均被拒绝。
- 工作流审计继续通过受控工作流服务创建；报表审计继续要求 `_export_service_write` 受控标记。

## 5. 下载失败留痕规则

- 已认证 internal 用户请求自己可见的导出对象后，下载权限不足记录 `denied_permission`。
- 导出状态不允许下载时记录 `rejected_status`。
- 缺少报表类型附加权限时记录 `denied_report_permission`。
- 当前 data_scope 与导出时快照不一致时记录 `denied_scope_changed`。
- 成功申请占位下载引用记录 `placeholder_grant`。
- 跨 tenant 或非本人对象继续按不可见资源处理，不在业务审计中写入目标对象信息，避免形成对象存在性侧信道；此类请求应由外围安全遥测承接。
- 失败结果仅保存固定结果码，不记录凭据、完整请求载荷或敏感字段。

## 6. 实际验证

- Django check：PASS，`System check identified no issues`。
- migration 一致性：PASS，`No changes detected`。
- UI-P4 专项 pytest：PASS，`14 passed`。
- 后端全量 pytest：PASS，`297 passed`。
- `git diff --check`：PASS；仅有工作区行尾格式提示。

## 7. 安全确认

- 未新增真实 `.env`、账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未接入真实微信、飞书、BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未启用自动采购、改价、清仓、真实 RPA、付款、转账或提现。
- 未修改前端、RPA Agent 或真实平台配置。

## 8. 待复审

执行独立 `UI-P4-ARCH-R2`，重点复核两项原 P1 的不可变性、失败下载审计持久化、跨对象 404 边界和回归测试。R2 无新增 P0/P1 后，方可建议 UI-P4 正式收尾。
