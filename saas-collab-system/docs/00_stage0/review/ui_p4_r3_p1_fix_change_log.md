# UI-P4 R3 P1 整改变更日志

## 1. 整改目标

关闭 `UI-P4-R3-P1-001`：actor 为空的 `WorkflowAuditEvent` 会随 tenant 级联删除，导致工作流审计记录丢失。

## 2. 修改文件

- `backend/apps/workflows/models.py`
- `backend/apps/workflows/migrations/0002_alter_workflowauditevent_options_and_more.py`
- `backend/tests/test_ui_p4_workflow_collaboration.py`

## 3. 整改内容

1. 将 `WorkflowAuditEvent.tenant` 从 `CASCADE` 改为 `PROTECT`。
2. 将审计专用不可变 Manager 设置为模型 base manager，阻断 `_base_manager` 直接删除绕过。
3. 新增 actor 为空和 actor 非空两种回归场景。
4. 回归测试覆盖 `_base_manager` 直接删除和 tenant Collector 删除，验证 tenant 与审计均保留。
5. 生成迁移 `workflows.0002`，记录 Meta base manager 与外键删除策略变更。

## 4. 验证结果

- Django check：通过。
- migration 一致性：通过，`No changes detected`。
- UI-P4 专项 pytest：`17 passed`。
- 后端全量 pytest：`300 passed`。
- 临时数据库应用全部迁移：通过。
- actor 为空/非空时 `_base_manager` 删除审计：均抛出 `ValidationError`。
- actor 为空/非空时删除 tenant：均抛出 `ProtectedError`。
- 两种场景下 tenant 与工作流审计均继续存在。
- 前端全量 Vitest：`86 passed`；构建通过。
- Docker Compose 配置与 16 个 RPA JSON 校验通过。

## 5. 安全确认

- 未接入真实平台。
- 未提交真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未添加自动采购、自动清仓、自动改价、真实 RPA 或资金操作。
- 未修改 `rpa-agent/` 或 `docs/04_rpa/`。
- 未处理或纳入工作区中的无关 DOCX 文件。

## 6. 待复审事项

需由 `UI-P4-ARCH-R4` 定向复审确认 `UI-P4-R3-P1-001` 是否正式关闭，以及 UI-P4 是否允许收尾、提交和创建 PR。
