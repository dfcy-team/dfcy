# UI-P4-ARCH-R3 最终整改复审报告

## 1. 复审对象

- 任务：`UI-P4-ARCH-R3`
- 复审日期：2026-07-17
- 复审角色：架构设计员（独立复审）
- 项目根目录：`saas-collab-system/`
- 分支：`feature/ui-p4-approval-report-exception-collab`
- 基线 HEAD：`e7709dbe786f0b4f1559c5316d38584ca5795dde`
- 复审依据：`ui_p4_arch_r1_recheck.md`、`ui_p4_p1_fix_change_log.md`、`ui_p4_arch_r2_recheck.md`、`ui_p4_r2_p1_fix_change_log.md`、UI-P4 API 合同和当前代码

本次复审只生成本报告，不修改业务代码、配置、迁移或测试。结论来自代码检查、独立命令执行及临时数据库实证，不直接采用整改日志自述。

## 2. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：1 项。R1/R2 指定的两项原 P1 均已按其直接整改目标关闭，但 R3 按提示进一步验证 tenant 生命周期时发现：无 actor 的 `WorkflowAuditEvent` 仍会随 tenant 级联删除。
- P2：5 项，均不改变本次 P1 判断。

UI-P4 暂不允许正式收尾、提交分支或创建 PR。应先关闭 `UI-P4-R3-P1-001`，再执行定向复审。

## 3. 原 P1 关闭情况

| 原P1编号 | 问题 | 是否关闭 | 独立证据 | 备注 |
|---|---|---|---|---|
| UI-P4-P1-001 | 工作流审计记录可通过实例 `save()` 修改 | 是 | 模型拒绝持久化实例保存、同主键覆盖、实例删除及 QuerySet 批量修改/删除；专项与全量测试通过 | 直接不可变入口已关闭 |
| UI-P4-P1-002 | 报表下载审计可删除，失败下载尝试留痕不完整 | 是 | 报表导出请求与审计拒绝直接/QuerySet 删除；外键迁移为保护语义；成功下载和四类安全可识别失败均形成固定脱敏审计 | R2 指定问题已关闭 |

原问题关闭不等于全部审计生命周期边界均已满足。R3 新发现的工作流审计 tenant 级联问题单列为 P1。

## 4. 工作流审计不可变性

直接写入和删除入口复核通过：

- `WorkflowAuditEventQuerySet` 拒绝 `update`、`delete`、`bulk_update` 和 `bulk_create`。
- 已持久化实例再次 `save()` 被拒绝；同主键替换被拒绝；创建强制使用插入语义。
- 实例 `delete()` 被拒绝。
- UI-P4 专项测试覆盖上述入口并通过。

生命周期复核未通过：

- `WorkflowAuditEvent.tenant` 仍使用 `on_delete=CASCADE`。
- `actor` 允许为空，不能依赖 actor 的 `PROTECT` 间接保存全部审计。
- 全新内存 SQLite 数据库应用全部迁移后，创建 actor 为空的工作流审计，再通过 `Tenant._base_manager.filter(...).delete()` 删除 tenant，实测结果为：tenant 删除成功，工作流审计同时消失。

因此工作流审计尚未满足“tenant 删除不得级联清除审计”的完整合同。

## 5. 报表审计不可变性

结论：**PASS**。

- `ReportExportAuditLog` 拒绝实例更新、同主键覆盖、实例删除及 QuerySet 批量修改/删除。
- `ReportExportRequest` 拒绝实例删除和 QuerySet 删除。
- `ReportExportAuditLog` 到导出请求及 tenant 的外键采用保护语义。
- 临时数据库实证结果：
  - 实例删除：`ValidationError`
  - QuerySet 删除：`ValidationError`
  - `_base_manager` 删除父请求：`ProtectedError`
  - tenant 删除：`ProtectedError`
  - 导出请求与审计记录均继续存在

R2 报告指出的父级级联删除路径已关闭。

## 6. 下载成功与失败审计

结论：**PASS**。

- 成功占位下载持久化 `placeholder_grant`。
- 以下四类安全可识别失败尝试均持久化固定脱敏结果：
  - `denied_permission`
  - `rejected_status`
  - `denied_report_permission`
  - `denied_scope_changed`
- 失败审计不会因 API 错误响应而被外层事务回滚。
- 跨 tenant、非本人或不可见对象继续返回 `404`，不通过审计响应泄露对象是否存在。
- 审计内容不记录凭据、完整请求载荷或敏感业务数据。

## 7. tenant 生命周期删除验证

| 对象 | 验证入口 | 实际结果 | 结论 |
|---|---|---|---|
| 报表导出请求 | 实例 `delete()` | `ValidationError` | 通过 |
| 报表导出请求 | QuerySet `delete()` | `ValidationError` | 通过 |
| 报表导出请求/审计 | `_base_manager` / Collector | `ProtectedError`，记录保留 | 通过 |
| 报表审计 tenant | tenant 删除 | `ProtectedError`，记录保留 | 通过 |
| 工作流审计 tenant（actor 为空） | `Tenant._base_manager` 删除 | 删除成功，审计消失 | **未通过（P1）** |

R3 的删除实证使用临时内存数据库，不修改本地开发数据库。

## 8. 测试、构建与迁移

| 检查项 | R3 独立执行结果 |
|---|---|
| Django check | PASS，`System check identified no issues` |
| `makemigrations --check --dry-run` | PASS，`No changes detected` |
| 临时数据库全部迁移 | PASS，内存 SQLite 完成全部迁移 |
| UI-P4 专项 pytest | PASS，`15 passed in 15.18s` |
| 后端全量 pytest | PASS，`298 passed in 41.07s` |
| UI-P4 专项 Vitest | PASS，`8 passed` |
| 前端全量 Vitest | PASS，6 个测试文件、`86 passed` |
| `npm run build` | PASS，1922 modules，约 6.25 秒 |
| Docker Compose 配置 | PASS；未注入部署变量时仅有空值提示 |
| RPA JSON 校验 | PASS，16 个 JSON，0 个无效文件 |
| `git diff --check` | PASS；仅存在 Git 的 LF/CRLF 工作副本提示 |

现有自动化测试尚未覆盖 actor 为空时删除 tenant 导致工作流审计级联丢失；因此测试全绿不能关闭本次新增 P1。

## 9. 安全与文件范围

- UI-P4 工作流与报表前端未发现 `/api/rpa/*`、`/api/finance/*` 或 `/admin/` 调用。
- 未发现真实平台 HTTP 地址或真实 BigSeller、Shopee、TikTok/TK、微信、飞书连接。
- 凭据扫描命中仅为测试占位值 `not-a-real-password`、`not-a-real-ui-p4-secret`、`not-real` 和服务端 Mock webhook 配置字段；未发现真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未发现自动采购、清仓、改价、真实 RPA、付款、转账或提现能力。
- 被跟踪的环境文件仅为 `.env.example` 示例文件；未发现被跟踪的运行日志、数据库、截图、下载、`dist` 或 `node_modules` 产物。
- UI-P4 变更主要位于工作流、报表、权限、Mock 回调、对应前端页面/API/测试及文档范围。
- 工作区中存在与 UI-P4 审核无关的未跟踪 DOCX 文件，本次未读取、修改或纳入报告文件范围；后续提交必须继续排除。

## 10. P0

无。

## 11. P1

### UI-P4-R3-P1-001 工作流审计可随 tenant 级联删除

- 证据：`WorkflowAuditEvent.tenant` 使用 `CASCADE`，且 `actor` 可为空；临时数据库实测 tenant 删除成功，actor 为空的工作流审计随之消失。
- 风险：审批、异常和协同处置审计可在 tenant 生命周期操作中被间接清除，不满足审计不可删除和可追溯要求。
- 验收标准：
  1. 将 `WorkflowAuditEvent.tenant` 改为保护语义，或采用等价的受控归档与强制保留方案。
  2. 生成并检查对应迁移，确保现有审计关系可安全迁移。
  3. 新增 actor 为空和 actor 非空两种审计场景的 tenant 删除回归测试。
  4. 覆盖实例、QuerySet、`_base_manager` 和 Django Collector 删除路径，均须证明审计记录不会丢失。
  5. 重新执行 Django check、迁移一致性、临时数据库全迁移、UI-P4 专项及后端全量 pytest。

## 12. P2

1. 审批列表撤回按钮尚未按 `requested_by_id` 与当前用户关系做行级隐藏；后端会拒绝越权，属于交互准确性观察项。
2. 前端构建有 2 条第三方 `@vueuse/core` PURE 注释警告，不阻断构建。
3. 不同真实认证角色、data_scope、401/403 及动作隐藏矩阵尚未形成浏览器自动化 E2E。
4. 本地开发数据库的 UI-P4 迁移尚未应用；本轮已在临时数据库完成全迁移验证，不影响代码一致性结论。
5. UI-P4 实现与审核材料仍位于未提交工作树；后续提交前必须重新核对范围并排除无关 DOCX。

## 13. 是否允许 UI-P4 收尾

**暂不允许。**

R1/R2 的两项原 P1 已关闭，报表审计保护与失败下载留痕均通过独立复核；但 R3 发现工作流审计仍可随 tenant 级联删除。关闭 `UI-P4-R3-P1-001` 并通过定向复审后，方可正式收尾、提交分支和创建 PR。

本结论不代表允许真实平台接入或高风险自动化。
