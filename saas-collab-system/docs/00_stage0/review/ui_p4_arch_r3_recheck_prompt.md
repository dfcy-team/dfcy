# UI-P4-ARCH-R3 最终整改复审提示

请执行 `UI-P4-ARCH-R3`，只审核 UI-P4 审计整改和必要回归，不修改业务代码。

## 1. 复审依据

- `docs/00_stage0/review/ui_p4_arch_r1_recheck.md`
- `docs/00_stage0/review/ui_p4_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p4_arch_r2_recheck.md`
- `docs/00_stage0/review/ui_p4_r2_p1_fix_change_log.md`
- `docs/03_api/ui_p4_approval_report_exception_collaboration_contract.md`

不得直接复制整改日志结论作为独立复审结果。

## 2. 原 P1 复核

确认：

1. `WorkflowAuditEvent` 拒绝实例更新、同主键覆盖、直接删除和批量修改。
2. `ReportExportAuditLog` 拒绝实例更新、同主键覆盖、直接删除和批量修改。
3. `ReportExportRequest` 拒绝实例和 QuerySet 删除。
4. 审计到导出请求和 tenant 的外键使用保护语义。
5. 通过 `_base_manager` 或父对象 Collector 删除不能清除审计。
6. tenant 删除不能级联清除审计，生命周期应采用归档或受控保留。
7. 成功下载及四类可安全识别的失败尝试均持久化固定脱敏结果。
8. 跨 tenant 或非本人对象继续按不可见资源处理，不泄露对象存在性。

## 3. 必须执行

- Django check
- `makemigrations --check --dry-run`
- 在临时数据库应用全部迁移
- UI-P4 专项 pytest
- 后端全量 pytest
- UI-P4 专项 Vitest
- 前端全量 Vitest
- `npm run build`
- Docker Compose 配置检查
- RPA JSON 校验
- API 路径、真实平台连接和真实凭据扫描
- 直接删除、QuerySet 删除、base manager 绕过和 tenant 删除实证
- `git diff --check` 与最终文件范围检查

未执行项必须记录原因，不得伪造。

## 4. 输出

创建：

`docs/00_stage0/review/ui_p4_arch_r3_recheck.md`

结论只能为：

- 存在 P0：`FAIL`
- 无 P0 但仍有 P1：`CONDITIONAL_PASS`
- 无 P0/P1：`PASS`

报告必须逐项确认 R1/R2 原 P1 是否关闭，并明确是否允许 UI-P4 正式收尾、提交分支和创建 PR。即使 PASS，也不代表允许真实平台接入或高风险自动化。
