# UI-P4-ARCH-R1 审批、报表、异常与协同回填复审报告

## 1. 复审对象

- 任务：`UI-P4-ARCH-R1`
- 复审日期：2026-07-16
- 复审角色：架构设计员（独立复审）
- 分支：`feature/ui-p4-approval-report-exception-collab`
- 复审 HEAD：`e7709dbe786f0b4f1559c5316d38584ca5795dde`（本次 UI-P4 成果为工作区未提交变更）
- 对比基线：`origin/main`，merge-base 为 `e7709dbe786f0b4f1559c5316d38584ca5795dde`
- 依据：UI-P4 接口合同、前端接口映射、实际代码差异、独立测试与浏览器验证

本次只生成本报告，未修改 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/`、配置、迁移或业务代码。工作区原有未跟踪 DOCX 文件未被处理。

## 2. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：2 项，均涉及审计闭环，关闭前不建议 UI-P4 收尾。
- P2：3 项，不阻断整改，但建议在 R2 前或后续迭代处理。
- 其余页面、路由、tenant/data_scope、权限、状态机、Mock 回调、前端离线边界、测试与构建检查通过。

## 3. 页面与路由合同

以下显式路由均已登记，并由默认拒绝的非公开路由合同约束：

- `/workflow/approvals`
- `/workflow/approvals/{id}`
- `/workflow/exceptions`
- `/workflow/exceptions/{id}`
- `/workflow/collaboration-events`
- `/reports/exports`

菜单、route permission 与 action permission 已分别配置。前端权限仅控制可见性与交互，后端仍执行可信授权。未发现 UI-P4 页面调用 `/api/rpa/*`、`/api/finance/*` 或 `/admin/`。

## 4. tenant、data_scope 与权限

- 工作流查询按 tenant 过滤，并按 `workflow.approvals.view`、`workflow.exceptions.view`、`workflow.collaboration.view` 对应 data_scope 收敛；空 scope 不返回数据。
- 动作接口使用独立权限码，不以普通 internal 身份替代动作授权。
- external 与 RPA 用户不能访问 internal 工作流管理接口。
- 报表导出与下载分别使用 `reports.export`、`reports.download`，下载前重新校验 tenant、owner、data_scope、报表权限和导出状态。
- 财务、RPA、业务后台边界未被 UI-P4 代码放宽。

结论：通过。

## 5. 审批状态机

- 提交、通过、驳回、撤回使用对应动作权限。
- 通过/驳回仅允许 `pending`，重复或冲突操作返回幂等结果或 `409`。
- 请求人不能审核自己的申请；仅请求人可撤回自己的待审申请。
- 状态变更使用事务和行锁，幂等键具备唯一性约束。
- 审批通过只记录授权结果，不直接执行采购、改价、清仓、RPA 或资金操作。

结论：后端边界通过。前端撤回按钮适用性见 P2-001。

## 6. 异常状态机

- 查看、分配、解决、关闭按 tenant、data_scope 和独立动作权限执行。
- 被分配人必须为同 tenant 的有效 internal 用户。
- 非法状态流转返回 `409/422`；external/RPA 不能访问 internal 异常接口。
- 状态变更会创建工作流审计事件。

结论：状态机与权限边界通过；审计对象不可变性见 P1-001。

## 7. 协同回填安全

- 微信/飞书仅实现 Mock 回调，production 模式强制禁用真实执行。
- 回调使用 HMAC-SHA256，要求时间戳、事件 ID 和签名，时间窗口不超过 300 秒。
- tenant、channel、event_id 具备唯一约束；同载荷重放返回幂等结果，冲突载荷返回 `409`。
- 仓库只保存 payload 哈希和脱敏摘要，不记录签名、Token、Cookie、Session 或完整 payload。
- 回调只创建协同事件，不直接改写审批、财务、RPA 或业务状态。
- 人工确认/驳回使用 `workflow.collaboration.confirm`。

结论：通过。

## 8. 报表导出与下载审计

- 创建导出与申请下载使用独立权限，下载会复核 tenant、owner、data_scope、报表权限和完成状态。
- 未完成导出不能下载；返回的是短期占位 grant，不构成真实对象存储凭据。
- 成功下载会写入 `DOWNLOAD` 审计。
- 失败下载尝试未形成完整审计，且审计记录仍可删除，详见 P1-002。

结论：条件通过。

## 9. 审计不可变性

工作流审计 QuerySet 已拒绝 `update/delete/bulk_update`，实例 `delete()` 也被拒绝；但 `WorkflowAuditEvent` 未覆盖实例 `save()`，已持久化记录仍可被加载、修改字段并再次保存。现有测试仅覆盖 QuerySet 修改/删除和实例删除，没有覆盖实例更新。

报表导出审计通过服务标记限制 `save()`，并拒绝 QuerySet `update/bulk_update/bulk_create`；但未拒绝 QuerySet 或实例 `delete()`。因此“不可篡改审计”尚未闭环。

结论：不通过，形成 P1-001 与 P1-002。

## 10. 前端状态与离线边界

- 页面具备 loading、error、empty、list/detail 和分页状态。
- 只有网络错误允许读请求回退 Mock；`401/403/404/409/422` 不会被伪装为成功或 connected。
- 工作流 Mock 写操作默认拒绝；只有真实 API 成功才更新页面状态。
- API 路径、响应结构和动作权限映射与合同一致。
- 未发现模拟 RPA Agent token、真实平台连接或真实凭据输入。

结论：通过。

## 11. 测试、构建与浏览器验证

| 检查项 | 独立执行结果 |
|---|---|
| Django check | 通过，`System check identified no issues` |
| migration 一致性 | 通过，`No changes detected` |
| UI-P4 专项 pytest | 通过，`13 passed` |
| 全量 pytest | 通过，`296 passed` |
| UI-P4 专项 Vitest | 通过，`8 passed` |
| 全量 Vitest | 通过，6 个测试文件、`86 passed` |
| `npm run build` | 通过，1922 modules，约 5.18 秒 |
| Docker Compose 配置 | 通过；仅出现未设置示例环境变量回退为空的提示 |
| RPA JSON 校验 | 通过，16 个 JSON，0 个无效文件 |
| `git diff --check` | 通过；仅有行尾格式提示，无补丁格式错误 |

系统默认 Python 缺少 Django/pytest，首次命令未执行成功；随后使用项目 `backend/.venv` 独立完成上述后端检查，报告采用项目虚拟环境结果。

浏览器在 1440×900 与 390×844 下验证 6 个 UI-P4 路径：均可渲染，列表/详情/动作区可见，无横向溢出，控制台未记录错误。验证使用当前本地 Mock/会话环境；真实认证角色矩阵 E2E 尚未自动化，列为 P2-003。

## 12. 安全扫描

- 未发现真实微信、飞书、BigSeller、Shopee 或 TikTok/TK 连接。
- 未发现真实账号、密码、Token、Cookie、Session、API Key、API Secret、银行或财务数据。
- 跟踪的环境文件仅为 `.env.example` 示例文件。
- 未发现自动采购、自动清仓、自动改价、真实 RPA、付款、转账或提现。
- UI-P4 前端未访问 `/api/rpa/*`、`/api/finance/*` 或 `/admin/`。
- Docker、构建和测试不依赖真实平台凭据。

结论：未发现新增 P0 安全风险。

## 13. P0

无。

## 14. P1

### UI-P4-P1-001 工作流审计仍可通过实例 `save()` 修改

- 证据：`WorkflowAuditEvent` 拒绝 QuerySet update/delete/bulk_update 和实例 delete，但未覆盖已存在实例的 `save()`。
- 风险：审批、异常和协同确认审计可被应用代码事后改写，不满足不可变审计合同。
- 验收：已存在记录再次 `save()` 必须拒绝；补充实例更新、QuerySet/bulk 操作测试，并保证仅受控创建路径可写入。

### UI-P4-P1-002 报表下载审计不可变性与失败尝试留痕不完整

- 证据：`ReportExportAuditLog` 未拒绝 QuerySet/实例 delete；`create_download_grant()` 仅在全部校验成功后写入 DOWNLOAD 审计。
- 风险：下载审计可被删除，且状态、范围或权限校验失败的可识别下载尝试缺少审计证据。
- 验收：拒绝实例和 QuerySet 删除；对可安全识别的已认证失败下载尝试写入脱敏结果审计，对无法安全解析目标的请求进入安全遥测；补充成功、拒绝、冲突与删除防护测试。

## 15. P2

### UI-P4-P2-001 撤回按钮未按行级请求人关系收敛

审批列表对具备 `workflow.approvals.withdraw` 的用户显示所有待审行的撤回按钮，后端会正确拒绝非请求人。建议仅在 `requested_by_id` 等于当前用户时显示或启用，减少无效操作。

### UI-P4-P2-002 前端构建存在第三方 PURE 注释警告

`npm run build` 成功，但 `@vueuse` 依赖产生 2 条 PURE annotation 警告。当前不阻断，可纳入依赖升级与包体观察。

### UI-P4-P2-003 缺少真实认证角色矩阵浏览器 E2E

当前浏览器验证覆盖桌面/移动布局和本地会话页面状态，尚未自动覆盖不同角色、data_scope、401/403 及动作隐藏矩阵。建议后续加入 Playwright E2E。

## 16. 是否建议 UI-P4 收尾

**暂不建议收尾。**

先定向关闭 UI-P4-P1-001 与 UI-P4-P1-002，并补充对应不可变性及失败审计测试；随后执行独立 `UI-P4-ARCH-R2`。两项 P1 关闭且无新增 P0/P1 后，可建议提交 UI-P4 PR 并进入收尾流程。
