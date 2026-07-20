# UI-P8-ARCH-R2 独立整改复审报告

## 1. 复审对象与基线

- 复审日期：2026-07-20
- 复审分支：`feature/ui-p8-production-pilot-security-readiness`
- 对比基线：本地及远端 `main`，提交 `30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 当前 Git HEAD：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 复审对象：当前工作区中的 UI-P8 实现、迁移、测试、合同、映射和整改证据
- 远端状态：远端不存在 `feature/ui-p8-production-pilot-security-readiness`，GitHub 不存在对应 PR，因此没有可固定的审核 HEAD 和远端 CI 记录

工作区同时存在不属于 UI-P8 提交范围的 DOCX、`docs/00_stage0/architecture/` 和 `docs/04_rpa/协同开发下发/`。本次只读取并排除这些内容，未修改、删除、暂存或纳入审核结论。

## 2. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- 代码、权限、状态机、页面和本地验证层面的原 P1 已关闭。
- 原 `UI-P8-R1-P1-006` 仅部分关闭：接口映射和真实 JWT E2E 已通过，但成果尚未提交为固定 HEAD，远端分支、PR 与 CI 均不存在。
- 按 R2 放行规则，远端 CI 未成功时不得判定 UI-P8 正式收尾门禁完成。

## 3. 原 P1 关闭情况

| 原 P1 编号 | 问题 | 复审结果 | 证据 | 备注 |
|---|---|---|---|---|
| UI-P8-R1-P1-001 | 财务安全评审 PATCH 与受控引用校验不闭合 | 已关闭 | `ui_p8_services.py` 的 `_finance_boundary()`、`_validate_controlled_references()`；`PilotTargetAlias`、`PilotEvidenceReference`；专项测试 | PATCH 对财务/非财务组合、原/目标环境、finance scope、tenant/environment 下受控 target 和 evidence 重新校验；非法组合返回 422/403 且不写入 |
| UI-P8-R1-P1-002 | 准入批准与控制台过期证据未重新验证 | 已关闭 | `_revalidate_entry_snapshot()`、`transition_resource()`、`control_room_payload()`；`test_entry_approval_revalidates_the_frozen_evidence_snapshot` | approve 重新读取证据并比对类型、ID、版本、状态、摘要和有效期；EntryDecision 也执行惰性过期；stale/阻断证据返回 409，不生成有效 go |
| UI-P8-R1-P1-003 | 失败审计合同未实现 | 已关闭 | `UIP8FailureAuditMixin.handle_exception()`、`audit_failure()`、失败审计测试、`PilotAuditEvent` 不可变模型 | collection/detail/action 统一覆盖；已认证 403、422、409 写脱敏失败审计并保留原响应；错误码与实际响应一致，审计不可更新/删除且 tenant 为 PROTECT |
| UI-P8-R1-P1-004 | 状态机创建入口仍可直接绕过 | 已关闭 | `UIP8WorkflowModel.save()`、受控服务创建标记、受保护 QuerySet、直接创建回归测试 | 实例首次 `save()`、`objects.create()`、bulk_create/bulk_update、QuerySet update/delete 均不能绕过服务；正常服务创建保持可用 |
| UI-P8-R1-P1-005 | 前端工作台与组件验收矩阵不完整 | 已关闭 | `P8WorkflowWorkspace.vue`、`frontend/src/api/pilot.js`、`frontend/src/mock/pilot.js`、前端专项 `23 passed` | 已实现 page/page_size、环境/状态筛选、草稿 PATCH；挂载测试覆盖 loading、empty、401、403、404、409、422、stale、offline、逐 action 权限和成功 action 重载 |
| UI-P8-R1-P1-006 | 接口映射与端到端证据不完整 | 部分关闭 | `frontend_api_mapping.md`、`ui_p8_jwt_e2e_result.md`、本次独立浏览器复跑 | 映射和 Mock 路径已纠正；真实 JWT login/me、GET、POST、PATCH 已通过。远端固定 HEAD 和 CI 尚不存在，故本项未完全关闭 |

## 4. 后端模型、API、权限、scope、状态机与审计

- UI-P8 五类工作台均使用 `/api/internal/pilot/*`，collection、detail 和 action view 统一执行认证、exact permission、tenant 与 permission-specific data_scope。
- 财务边界同时要求 pilot action 权限与 `finance.view`；finance scope 只保存脱敏平台、币种代码，非财务评审不允许携带 finance scope。
- 受控 target/evidence 引用按 `tenant + environment` 登记，不接受跨 tenant、跨环境或未登记引用。
- 准入提交冻结证据快照和摘要，批准时重新读取证据；证据变化、过期或 blocker 会拒绝批准。
- 模型创建、状态迁移、取消、过期和结果记录必须经过专用服务；直接模型和批量写入不可绕过。
- 403、422、409 失败审计在业务事务退出后独立写入，不改变原错误响应；审计内容脱敏、不可更新、不可删除，tenant 删除受保护。
- 未发现部署、恢复、回滚、Shell、Docker、SSH、真实 RPA 或资金执行能力。

## 5. 前端页面、权限和 capability 状态

- 路由、菜单和页面使用 exact view permission；plan、review、record、cancel 按 action permission 与合法状态显示。
- 列表支持服务端分页、环境和状态筛选；page 不设错误固定上限，page_size 固定为合同允许的 20。
- 草稿编辑先读取详情，再以 `version` 调用 PATCH；409/422 等错误进入统一页面状态。
- 真实响应只有在 `success/code/message/data` 合同有效时才被接受；UI-P8 真实能力仍标记 `pending`，Mock 标记 `mock`，未误标 `connected`。
- 组件挂载矩阵覆盖 loading、empty、401、403、404、409、422、stale、offline、四类 action permission 和成功 action 后重载。
- 页面不包含真实平台连接、明文凭据、命令输入、Web Shell、生产发布、真实 RPA 或资金操作入口。

## 6. 测试、构建与系统检查

2026-07-20 在当前工作区独立执行：

| 检查 | R2 实际结果 | 备注 |
|---|---|---|
| Django check | PASS | `System check identified no issues (0 silenced)` |
| migration 一致性 | PASS | `No changes detected` |
| 临时数据库迁移 | PASS | pytest 创建测试数据库并应用全部迁移 |
| UI-P8 后端专项 | PASS | `19 passed in 9.87s` |
| 后端全量 pytest | PASS | `397 passed in 38.82s` |
| `npm ci` | PASS | 249 packages，0 vulnerabilities |
| UI-P8 前端专项 | PASS | `23 passed` |
| 前端全量测试 | PASS | 11 files，`153 passed` |
| 前端生产构建 | PASS | 1955 modules transformed |
| Docker Compose 配置 | PASS | `docker compose --env-file .env.example config --quiet` exit 0 |
| RPA JSON | PASS | 两个示例目录共 16 个 JSON，0 invalid |
| `git diff --check` | PASS | 仅 Git 行尾转换提示，无 whitespace error |
| 构建产物 | PASS | `frontend/dist`、`node_modules`、RPA cache/downloads 保持忽略 |
| 高置信密钥扫描 | PASS | 私钥、AWS key、GitHub token、`sk-` 签名 0 matches |
| 禁止路径/动作扫描 | PASS | UI-P8 范围内 RPA Agent、finance/admin、外部 URL、部署及资金动作 0 matches |
| 远端 CI | 未执行 | 远端无分支、PR 和固定 HEAD，不能伪造成功结果 |

## 7. 真实 JWT 浏览器 E2E

在 `VITE_USE_MOCK=false`、本地 Django、Vite 和 demo SQLite 数据下独立复跑：

1. `POST /api/internal/auth/login/`：200。
2. `GET /api/internal/auth/me/`：200，返回受限 internal 角色、tenant、权限和 data_scope。
3. 直接访问 `/pilot/verification-runs`：成功进入受保护页面。
4. 列表 GET：200，页面显示真实后端记录和分页。
5. 创建 POST：201，新建 demo 草稿，列表从 1 条变为 2 条。
6. 详情 GET：200。
7. 草稿 PATCH：200，最新记录版本由 1 更新为 2。
8. 清洁复跑页的浏览器 error/warn：0。

首次启动 Vite 后的第一个标签页在依赖优化热更新时出现一次瞬时 render error；依赖稳定后新标签页从登录到 PATCH 全流程无 error/warn。该现象未在生产构建或清洁复跑中复现。

## 8. 安全扫描结果

- 未发现真实 `.env`、账号密码、Token、Cookie、Session、API Key/API Secret、私钥、数据库密码或证书。
- 未发现真实 BigSeller、Shopee、TikTok/TK、银行、支付、AI provider 或对象存储连接。
- 未发现真实订单、供应商、财务、银行或生产环境数据。
- 未发现自动采购、供应商通知、改库存、刊登、改价、清仓、停售、归档、真实 RPA、付款、转账或提现。
- 本次浏览器 E2E 只使用本地 demo 用户和受控测试数据；测试服务已停止。

## 9. P0

无。

## 10. P1

### UI-P8-R2-P1-001：缺少固定审核 HEAD 和远端 CI

当前 UI-P8 实现仍是未提交工作区变更，当前 HEAD 与 main 相同；远端没有对应分支和 PR，无法确认 CI、文件范围以及 CI HEAD 与复审对象一致。必须排除无关 DOCX 和目录后提交 UI-P8 允许范围、推送分支、创建 PR，并在 HEAD 不变的前提下取得全部必需 CI SUCCESS。

## 11. P2

1. `npm ci` 保留 `esbuild`、`vue-demi` 的 allow-scripts 审核提示。
2. Vite/Rollup 仍报告第三方 `@vueuse/core` PURE 注释位置警告，未阻断构建。
3. 本地 Vite 首次依赖优化热更新出现一次瞬时 render error，稳定后的清洁 JWT E2E 未复现；建议在 PR CI 或后续浏览器 E2E 中持续观察。

## 12. 是否允许 UI-P8 正式收尾

**暂不允许。**

五项原 P1 已关闭，第六项的映射与真实 JWT E2E 已关闭，但固定审核 HEAD 与远端 CI 门禁仍缺失。下一步应仅提交 UI-P8 允许范围并创建 PR；远端 CI 全部成功且 HEAD 未变化后，再进行定向收尾核验。该结论不允许真实平台接入、生产发布、真实 RPA、自动采购或资金操作。
