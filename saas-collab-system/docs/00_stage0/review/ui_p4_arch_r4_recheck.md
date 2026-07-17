# UI-P4-ARCH-R4 工作流审计 tenant 保护定向复审报告

## 1. 复审对象

- 任务：`UI-P4-ARCH-R4`
- 复审日期：2026-07-17
- 分支：`feature/ui-p4-approval-report-exception-collab`
- 基线 HEAD：`e7709dbe786f0b4f1559c5316d38584ca5795dde`，整改位于当前未提交工作树
- 原报告：`docs/00_stage0/review/ui_p4_arch_r3_recheck.md`
- 原结论：`CONDITIONAL_PASS`
- 原 P1：`UI-P4-R3-P1-001` 工作流审计可随 tenant 级联删除

本次定向复审核对模型、迁移、自动化测试和临时数据库实际删除结果，不以整改日志自述替代复审证据。

## 2. 复审结论

**PASS**

- P0：无。
- P1：无。`UI-P4-R3-P1-001` 已关闭。
- P2：5 项，均为不阻断观察项。

UI-P4 已满足正式收尾条件，允许在最终文件范围核对后提交当前分支并创建 PR。该结论不代表允许真实平台接入或高风险自动化。

## 3. 原 P1 关闭情况

| 原P1编号 | 问题 | 是否关闭 | 复审证据 | 备注 |
|---|---|---|---|---|
| UI-P4-R3-P1-001 | actor 为空的工作流审计可随 tenant 级联删除 | 是 | tenant 外键已改为 `PROTECT`；迁移存在；actor 空/非空两种临时数据库删除实证均返回 `ProtectedError`，审计继续存在 | 已关闭 |

## 4. 模型与迁移复审

- `WorkflowAuditEvent.tenant` 使用 `on_delete=models.PROTECT`。
- `WorkflowAuditEvent.Meta.base_manager_name` 指向不可变审计 Manager `objects`。
- `WorkflowAuditEventQuerySet.delete()` 拒绝直接和 base manager QuerySet 删除。
- 迁移 `workflows.0002_alter_workflowauditevent_options_and_more` 同时包含：
  - `AlterModelOptions`：设置 `base_manager_name=objects`。
  - `AlterField`：tenant 外键改为 `PROTECT`。
- `makemigrations --check --dry-run` 返回 `No changes detected`，模型与迁移一致。

结论：通过。

## 5. 删除绕过定向验证

在全新内存 SQLite 数据库应用全部迁移后，分别建立 actor 为空和 actor 非空的工作流审计：

| 场景 | `_base_manager` 删除审计 | tenant 删除 | tenant 保留 | 审计保留 |
|---|---|---|---|---|
| actor 为空 | `ValidationError` | `ProtectedError` | 是 | 是 |
| actor 非空 | `ValidationError` | `ProtectedError` | 是 | 是 |

该验证证明保护不依赖 actor 外键，且常规 Manager、base manager 和 tenant Collector 路径均不能清除工作流审计。

## 6. 自动化回归

- 新增参数化测试覆盖 actor 为空和 actor 非空。
- UI-P4 专项 pytest：`17 passed in 13.30s`。
- 后端全量 pytest：`300 passed in 30.65s`。
- Django check：通过，0 issues。
- migration 一致性：通过。
- 临时数据库全部迁移：通过。

原 P1 已由自动化测试和独立临时数据库实证双重覆盖。

## 7. 前端与系统回归

| 检查项 | 结果 |
|---|---|
| UI-P4 专项 Vitest | PASS，`8 passed` |
| 前端全量 Vitest | PASS，6 个测试文件、`86 passed` |
| `npm run build` | PASS，1922 modules，约 5.02 秒 |
| Docker Compose 配置 | PASS；未注入部署变量时仅提示空值 |
| RPA JSON 校验 | PASS，16 个 JSON，0 个无效文件 |

前端构建仍出现两条第三方 `@vueuse/core` PURE 注释提示，不影响构建结果。

## 8. 安全与范围复审

- UI-P4 工作流和报表页面未发现 `/api/rpa/*`、`/api/finance/*` 或 `/admin/` 调用。
- 未发现真实平台 HTTP 地址、真实凭据或真实业务敏感数据。
- 扫描命中仅包括 `not-a-real-password`、`not-a-real-ui-p4-secret`、`not-real` 等测试占位值及 Mock webhook 配置字段。
- 未发现自动采购、清仓、改价、真实 RPA、付款、转账或提现。
- 本次整改只涉及工作流审计模型、迁移、后端回归测试和审核文档。
- 工作区中的无关 DOCX 文件未被读取、修改或纳入整改范围，提交时必须继续排除。

结论：无新增 P0/P1 安全或范围问题。

## 9. P0

无。

## 10. P1

无。

## 11. P2

1. 审批列表撤回按钮尚未按 `requested_by_id` 与当前用户关系做行级隐藏；后端越权保护有效。
2. 前端构建存在两条第三方 `@vueuse/core` PURE 注释提示。
3. 多角色、data_scope、401/403 和动作隐藏矩阵尚未形成浏览器认证态 E2E。
4. 本地开发数据库尚未应用 UI-P4 迁移；临时数据库全迁移及测试数据库验证已通过。
5. UI-P4 实现和审核材料仍在未提交工作树，提交前需再次排除无关 DOCX 并核对范围。

## 12. 是否允许 UI-P4 收尾

**允许。**

R1、R2 和 R3 发现的审计 P1 均已关闭，无未关闭 P0/P1。允许执行 UI-P4 正式收尾、提交 `feature/ui-p4-approval-report-exception-collab`、推送并创建 PR；合并前仍需等待远端 CI 成功并复核 PR 文件范围。

真实平台接入、真实 RPA 和高风险自动化仍不在本次放行范围内。
