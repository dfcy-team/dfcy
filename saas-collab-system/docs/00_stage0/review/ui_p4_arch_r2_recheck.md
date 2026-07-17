# UI-P4-ARCH-R2 审批、报表、异常与协同回填整改复审报告

## 1. 复审对象

- 任务：`UI-P4-ARCH-R2`
- 复审日期：2026-07-17
- 复审角色：架构设计员（独立复审）
- 分支：`feature/ui-p4-approval-report-exception-collab`
- 当前 HEAD：`e7709dbe786f0b4f1559c5316d38584ca5795dde`，UI-P4 实现及整改仍位于未提交工作树
- 原报告：`docs/00_stage0/review/ui_p4_arch_r1_recheck.md`
- 整改记录：`docs/00_stage0/review/ui_p4_p1_fix_change_log.md`
- 原结论：`CONDITIONAL_PASS`

本次只审核两项原 P1 及相关回归范围，不复制整改日志结论作为复审结果，不修改业务代码、配置或迁移。工作区原有未跟踪 DOCX 文件保持不动。

## 2. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：1 项。`UI-P4-P1-001` 已关闭；`UI-P4-P1-002` 的失败下载留痕已完成，但审计仍可通过删除父级导出请求被级联删除，因此未完全关闭。
- P2：4 项，不改变本次 P1 判断。

UI-P4 当前仍不建议正式收尾，应先关闭报表审计级联删除路径，再执行定向 `UI-P4-ARCH-R3` 或 R2 补充复核。

## 3. 原 P1 关闭情况

| 原P1编号 | 问题 | 是否关闭 | 独立证据 | 备注 |
|---|---|---|---|---|
| UI-P4-P1-001 | 工作流审计可通过实例 `save()` 修改 | 是 | 模型拒绝已持久化实例保存和同主键替换；专项测试覆盖 update/delete/bulk update/bulk create、实例 save/delete 和伪造主键 | 不可变性回归通过 |
| UI-P4-P1-002 | 报表下载审计可删除且失败尝试留痕不完整 | 否 | 直接 update/delete/bulk 写入已阻断，四类可识别失败尝试均持久化；但内存数据库实测删除 `ReportExportRequest` 后其审计因 `CASCADE` 一并删除 | 仍保留 1 项 P1 |

## 4. 工作流审计不可变性复审

结论：**PASS**。

- `WorkflowAuditEventQuerySet` 拒绝 `update`、`delete`、`bulk_update` 和 `bulk_create`。
- 已持久化实例再次 `save()` 被拒绝，实例 `delete()` 被拒绝。
- 伪造相同主键的新实例不能覆盖已有记录；创建使用强制插入语义。
- 专项测试实际覆盖上述入口并通过。

原 `UI-P4-P1-001` 已关闭。

## 5. 报表下载失败留痕复审

结论：**PASS**。

- 下载接口先通过 internal 身份和本人可见对象边界，再由服务校验 `reports.download`、导出状态、报表附加权限和当前 data_scope。
- 可安全识别的失败尝试分别记录固定结果码：
  - `denied_permission`
  - `rejected_status`
  - `denied_report_permission`
  - `denied_scope_changed`
- 成功占位下载记录 `placeholder_grant`。
- 失败审计写入不位于会随异常回滚的外层原子事务中，API 返回失败后审计仍可查询。
- 非本人或跨 tenant 对象按不可见资源返回 `404`，不在业务审计中泄露目标对象存在性。
- 审计结果仅包含固定结果码，不记录凭据、完整载荷或敏感字段。

原 P1 中“失败尝试留痕不完整”部分已关闭。

## 6. 报表审计不可删除性复审

结论：**FAIL（P1）**。

已通过的直接防护：

- `ReportExportAuditLog` 拒绝已存在实例保存、同主键替换、实例删除。
- QuerySet 拒绝 update、delete、bulk update 和 bulk create。

仍存在的绕过路径：

- `ReportExportAuditLog.export_request` 使用 `on_delete=CASCADE`。
- `ReportExportRequest` 本身未拒绝实例或 QuerySet 删除。
- 独立内存 SQLite 数据库完成迁移后实测：创建导出请求和下载审计，再执行 `export.delete()`，结果为 `parent_delete_succeeded`，导出请求与审计记录均不存在。

这意味着审计对象虽然不能被直接删除，仍能通过父对象级联删除，不满足“不可篡改、不可删除”的审计合同。

## 7. tenant、权限与对象可见性回归

- 下载仅处理当前 tenant 且本人可见的导出请求。
- 非本人请求返回 `404`，未形成对象枚举侧信道。
- 缺少下载权限、报表附加权限或 data_scope 已变化时返回 `403` 并记录脱敏结果。
- 未完成/被拒绝的导出请求返回 `422` 并记录状态拒绝结果。
- external/RPA 用户仍不能访问 internal 工作流管理和报表下载能力。

结论：通过。

## 8. 独立测试、构建与系统检查

| 检查项 | R2实际结果 |
|---|---|
| Django check | PASS，`System check identified no issues` |
| migration 一致性 | PASS，`No changes detected` |
| UI-P4 专项 pytest | PASS，`14 passed in 14.95s` |
| 后端全量 pytest | PASS，`297 passed in 40.11s` |
| UI-P4 专项 Vitest | PASS，`8 passed` |
| 前端全量 Vitest | PASS，6 个文件、`86 passed` |
| `npm run build` | PASS，1922 modules，约 6.57 秒 |
| Docker Compose 配置 | PASS；未注入部署变量，存在空值提示 |
| RPA JSON 校验 | PASS，16 个 JSON，0 个无效文件 |
| 父对象级联删除实证 | FAIL，父导出请求和审计均被删除 |

自动化测试当前未覆盖父级导出请求删除导致审计级联丢失，因此现有 `297 passed` 不能证明审计不可删除性完全成立。

## 9. 安全扫描

- UI-P4 前端未发现 `/api/rpa/*`、`/api/finance/*` 或 `/admin/` 调用。
- 未发现真实微信、飞书、BigSeller、Shopee、TikTok/TK 平台 HTTP 调用。
- 未发现真实账号、密码、Token、Cookie、Session、API Key、API Secret、银行或财务数据。
- 被跟踪的环境文件仅为 `.env.example` 示例文件。
- 未发现自动采购、清仓、改价、真实 RPA、付款、转账或提现。

结论：无新增 P0 安全风险。

## 10. P0

无。

## 11. P1

### UI-P4-R2-P1-001 报表审计可经父级导出请求级联删除

- 对应原问题：`UI-P4-P1-002` 未完全关闭。
- 证据：`ReportExportAuditLog.export_request` 为 `CASCADE`，且 `ReportExportRequest.delete()` 未阻断；内存数据库实测审计随父对象删除。
- 风险：下载、查看和导出申请审计均可被间接清除，破坏审计追踪和事后核验能力。
- 验收标准：
  1. 审计与导出请求的外键删除策略改为保护语义，或将导出请求定义为不可删除审计根对象。
  2. 同时拒绝 `ReportExportRequest` 的实例和 QuerySet 删除，避免 ORM 常规入口绕过。
  3. tenant 生命周期采用归档或受控保护策略，不得级联丢失审计。
  4. 新增实例删除、QuerySet 删除和父对象级联删除回归测试，均须证明审计仍存在。
  5. 生成并检查必要迁移，重新执行专项与全量测试。

## 12. P2

1. 审批列表撤回按钮仍未按 `requested_by_id` 与当前用户关系进行行级隐藏；后端会拒绝越权，属于交互适用性问题。
2. 前端构建仍有 2 条第三方 `@vueuse/core` PURE 注释警告，不阻断构建。
3. 不同真实认证角色、data_scope、401/403 与动作隐藏矩阵尚未形成浏览器自动化 E2E。
4. UI-P4 实现、整改及审核文档仍位于未提交工作树；最终提交前必须再次核对文件范围。

## 13. 是否建议 UI-P4 收尾

**暂不建议。**

工作流审计实例修改问题及失败下载留痕问题已通过复审，但报表审计仍可通过父级导出请求级联删除。关闭 `UI-P4-R2-P1-001`、补充父对象删除回归测试并通过下一次独立复核后，方可建议 UI-P4 收尾、提交和创建 PR。

本次 R2 未修改任何业务代码，也不代表允许真实平台接入或高风险自动化。
