# UI-P7-ARCH-R3 独立整改复审报告

## 1. 复审对象与基线

- 任务：`UI-P7-ARCH-R3`
- 分支：`feature/ui-p7-governance-pilot-readiness`
- 工作树 HEAD：`17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`
- 对比基线：`origin/main@17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`
- 复审日期：2026-07-20
- 原结论：`UI-P7-ARCH-R2 = CONDITIONAL_PASS`
- 原未关闭问题：`UI-P7-R2-P1-001` 至 `UI-P7-R2-P1-003`
- 复审方式：独立静态检查、实际后端与前端测试、临时数据库迁移、受控 JWT 浏览器验证、Docker/RPA/安全扫描。
- 复审性质：只审核，不修复；本报告之外未因 R3 复审修改业务代码。

当前 UI-P7 实现仍位于未提交工作树中。本报告审核的是当前工作树快照，不替代提交范围复核、PR 审核或远端 CI。

## 2. 复审结论

**PASS**

- P0：无。
- P1：无，R2 的 3 项 P1 均已关闭。
- P2：3 项非阻断观察项。
- 允许 UI-P7 正式收尾并进入提交、CI 和 PR 流程。
- 合并前仍须确认提交范围排除无关 DOCX、`docs/00_stage0/architecture/` 和运行产物，并要求远端 CI 成功。

## 3. 原 P1 关闭情况

| 原 P1 编号 | 问题 | 是否关闭 | 独立证据 | 备注 |
|---|---|---|---|---|
| UI-P7-R2-P1-001 | 容量状态及阈值映射不完整 | 是 | `CapacityObservation` 已原生支持 `normal/warning/critical/unknown/stale`；序列化器分别返回 warning/critical 阈值；筛选按精确状态执行；专项测试覆盖五种状态和阈值语义 | 不再通过损失映射表达 `critical` |
| UI-P7-R2-P1-002 | 回滚批准唯一性、批量创建防绕过及创建失败审计未闭合 | 是 | 数据库唯一约束、`bulk_create` 拒绝、事务冲突映射、计划创建失败不可变审计及回归测试均存在 | 数据库约束作为并发竞争的最终防线 |
| UI-P7-R2-P1-003 | 缺少真实组件状态矩阵测试，无效详情 URL 未显示 404 | 是 | 新增 Vue 挂载测试 20 项；受控浏览器验证受限角色、授权数据范围和无效详情 404；页面使用统一 `AppState` | 未使用真实平台或生产数据 |

## 4. 容量状态与阈值复审

结论：**通过**。

1. 模型状态完整包含 `normal`、`warning`、`critical`、`unknown`、`stale`。
2. `warning` 与 `critical` 可独立存储、筛选和返回，不再映射为同一中间状态。
3. 序列化器在 `critical` 时返回 `critical_threshold`，在 `normal/warning` 时返回 `warning_threshold`，`unknown/stale` 不伪造阈值。
4. 数据迁移将旧状态转换到冻结合同并建立新枚举约束。
5. 后端回归测试创建五种状态，验证列表筛选和阈值字段；前端 Mock 和测试同时覆盖 normal/critical。

主要证据：

- `backend/apps/pilot/models.py`
- `backend/apps/pilot/serializers.py`
- `backend/apps/pilot/migrations/0003_capacity_status_and_rollback_approval_unique.py`
- `backend/tests/test_ui_p7_governance_pilot.py::test_capacity_status_and_threshold_contract_preserves_critical_semantics`
- `frontend/src/mock/pilot.js`
- `frontend/tests/ui-p7-governance-pilot.spec.js`

## 5. 回滚批准与不可变审计复审

结论：**通过**。

1. `ReleasePlan.rollback_approval_ref` 具备数据库唯一约束，迁移先将空字符串规范化为 `NULL`，避免空值冲突。
2. 服务层在批准写入时处理数据库唯一冲突，并返回统一策略错误；数据库约束可兜底并发竞态。
3. 受保护工作流 QuerySet 禁止 `update/delete/bulk_update/bulk_create`，实例 `save/delete` 同样受保护，无法通过通用 ORM 批量路径绕过工作流。
4. 恢复计划和发布计划创建的请求格式、data_scope、幂等及数据库冲突失败均写入不可变失败审计。
5. 审计记录禁止修改和删除；关联 tenant 使用保护语义，避免级联删除破坏审计链。
6. 回归测试覆盖批量创建绕过、创建失败审计、跨计划回滚批准重复和数据库唯一约束。

主要证据：

- `backend/apps/pilot/models.py`
- `backend/apps/pilot/services.py`
- `backend/apps/pilot/views.py`
- `backend/apps/pilot/migrations/0003_capacity_status_and_rollback_approval_unique.py`
- `backend/tests/test_ui_p7_governance_pilot.py::test_workflow_bulk_create_is_rejected`
- `backend/tests/test_ui_p7_governance_pilot.py::test_plan_creation_failures_are_immutably_audited`
- `backend/tests/test_ui_p7_governance_pilot.py::test_rollback_approval_reference_is_unique_across_plans`
- `backend/tests/test_ui_p7_governance_pilot.py::test_rollback_approval_reference_has_database_uniqueness`

## 6. 前端状态、权限与详情复审

结论：**通过**。

1. `statusFromApiResponse()` 明确映射 401、403、404、409、422，并保留 stale/offline/partial 状态。
2. `AppState` 提供 loading、empty、unauthenticated、forbidden、not_found、conflict、invalid、partial、stale、offline 和 error 的可见呈现。
3. `GovernanceCatalog` 的详情加载失败会切换到统一状态；无效详情 URL 显示“资源不存在”，不再保持 ready 或静默失败。
4. 分页组件实际触发下一页请求，不再只做静态源码断言。
5. 受限角色浏览器验证中，只返回 permission-specific data_scope 内的合同，未显示合同检查动作。
6. UI-P7 前端未访问 `/api/rpa/*`、`/api/finance/*` 或 `/admin/`，也未模拟 Agent token。

## 7. 测试、构建与受控浏览器验证

| 检查项 | R3 实际结果 | 说明 |
|---|---|---|
| Django check | PASS | `System check identified no issues (0 silenced)` |
| migration 一致性 | PASS | `No changes detected` |
| 临时数据库迁移 | PASS | 从空临时 SQLite 数据库执行迁移，包含 `pilot.0003` |
| UI-P7 后端专项 pytest | PASS | `56 passed in 5.92s` |
| 后端全量 pytest | PASS | `378 passed in 29.43s` |
| `npm ci` | PASS | 249 packages，0 vulnerabilities；清理独立测试服务占用后复跑成功 |
| UI-P7 Vue 组件专项测试 | PASS | 1 file / 20 passed |
| 前端全量测试 | PASS | 10 files / 130 passed |
| `npm run build` | PASS | 1947 modules transformed；构建成功 |
| Docker Compose 静态解析 | PASS | `docker compose config -q` exit 0；未加载真实环境变量，仅有空变量提示 |
| RPA JSON 校验 | PASS | 16 files 均可解析 |
| 受控 JWT 浏览器验证 | PASS | 受限角色、data_scope、动作隐藏、有效列表和无效详情 404 均通过；控制台无 error/warn |
| 远端 CI | 未执行 | 当前成果尚未提交且未创建 PR，不能伪造远端 CI 结果 |

受控浏览器验证使用临时 SQLite、demo 用户和本地临时端口，不连接真实双主机、真实平台或生产数据。验证后已关闭临时浏览器会话与服务，并删除临时数据库。

## 8. 安全与范围扫描

- 高置信真实私钥、GitHub/OpenAI/AWS/Slack Token 模式：0。
- UI-P7 业务代码中的 `/api/rpa/*`、`/api/finance/*`、`/admin/` 调用：0。
- governance/pilot 模块中的 Docker、Shell、SSH、SQL 或 Redis 执行入口：0。
- RPA JSON 样例仍为 demo/placeholder，未执行真实 RPA。
- `frontend/dist`、`node_modules` 与 RPA 运行产物未被 Git 跟踪；仅 `.gitkeep` 被跟踪。
- `git diff --check` 未发现空白错误，仅报告 Windows 工作树 LF/CRLF 转换提示。
- 未发现真实平台连接、真实密钥、真实银行/支付连接、真实业务敏感数据或高风险自动化。
- 工作树中两份 DOCX 和 `docs/00_stage0/architecture/` 不属于 UI-P7 提交范围，复审未读取、修改或纳入结论。

## 9. P0 问题

无。

## 10. P1 问题

无。

## 11. P2 问题

1. `npm ci` 继续提示 `esbuild`、`vue-demi` 的 allow-scripts 审批观察项；本次安装、测试和构建均成功，不阻断 UI-P7。
2. Vite/Rollup 对第三方 `@vueuse/core` PURE 注释位置给出警告；构建成功，不属于项目业务代码错误。
3. 当前成果仍是未提交工作树快照，尚无远端 CI。提交前应严格选择 UI-P7 文件并排除无关 DOCX 与 `docs/00_stage0/architecture/`；PR 合并前必须要求远端 CI 成功。

## 12. 是否允许 UI-P7 正式收尾

**允许。**

R2 的 3 项 P1 已由独立代码检查、数据库约束、回归测试、真实组件测试和受控浏览器验证关闭。UI-P7 可以正式收尾、提交分支并创建 PR；远端 CI 成功且提交范围复核通过后方可合并。

本结论不允许真实平台接入、生产发布、真实恢复/回滚执行、真实 RPA、自动采购、自动改价、自动清仓、自动停售/归档或任何付款、转账、提现动作。
