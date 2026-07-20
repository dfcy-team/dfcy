# UI-P8 生产试点运维与专项安全准入合同冻结报告

## 1. 冻结对象

- 分支：`feature/ui-p8-production-pilot-security-readiness`
- 基线：`main@30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 前置结论：`UI-P7-ARCH-R3 = PASS`，PR #25 已合并。
- 范围：试点控制台、专项安全评审、受控验证、性能容量证据和人工准入决策。

## 2. 页面冻结

新增五个工作面：

1. `/pilot/control-room`
2. `/pilot/security-reviews`
3. `/pilot/verification-runs`
4. `/pilot/performance-runs`
5. `/pilot/entry-decisions`

复用 UI-P7 的 readiness、topology、capacity、recovery、releases，以及现有 security operations 和 audit 页面。未新增同义拓扑、容量、恢复或发布页面。

## 3. API 冻结

统一使用：

- `/api/internal/pilot/control-room/`
- `/api/internal/pilot/security-reviews/*`
- `/api/internal/pilot/verification-runs/*`
- `/api/internal/pilot/performance-runs/*`
- `/api/internal/pilot/entry-decisions/*`

API 只登记计划、证据、评审和结果，不提供 start/execute/shell/deploy/restore/rollback/platform-connect 等执行端点。

## 4. 权限与 data_scope 冻结

- 控制台：`pilot.control.view` + `pilot_environments`。
- 安全评审：`pilot.security_review.view/plan/review` + `pilot_environments/security_review_ids`。
- 受控验证：`pilot.verification.view/plan/review/record/cancel` + `pilot_environments/verification_run_ids`。
- 性能验证：`pilot.performance.view/plan/review/record/cancel` + `pilot_environments/performance_run_ids`。
- 准入决策：`pilot.entry.view/plan/review` + `pilot_environments/entry_decision_ids`。

创建按 exact plan permission 的 `pilot_environments` 授权；存量资源 action 按 exact permission 的资源 ID scope 授权。PATCH 改变 environment 时同时校验原环境和目标环境；owner_id 由后端固定为 actor，不接受客户端转移。准入证据引用逐类检查来源 view permission/scope/tenant/environment；财务边界及 finance_scope 变化叠加 `finance.view`。缺失、未知、非法、空、重复、未登记和超限 scope 返回 `403 DATA_SCOPE_INVALID`。

## 5. 状态机冻结

- 安全评审：`draft -> submitted -> approved/rejected`，以及 `draft/submitted/approved -> expired`。
- 验证与性能：`draft -> submitted -> approved -> passed/failed/manual_required`，未完成计划可取消。
- 准入决策：`draft -> submitted -> approved/rejected`，以及 `draft/submitted/approved -> expired`，决策值另存 `go/no_go`。

所有状态迁移由逐资源矩阵约束，并由后端服务、事务、版本和幂等控制。取消使用专用 cancel permission；过期由 system 定时/惰性处理。通用 PATCH、ORM update、bulk_update 和 bulk_create 不得绕过；终态和证据不可修改或删除。

## 6. 职责分离冻结

- 创建人不能审核自己的安全评审或准入决策。
- 创建人不能批准自己的验证或性能计划。
- 验证/性能结果记录人不能是计划批准人。
- submitted/approved 验证或性能计划不能由创建人取消。
- 审核动作必须同时满足 review permission、对应 scope 和有效状态。
- 财务边界评审必须具备独立财务权限，且只读取脱敏状态。

## 7. 响应与错误冻结

- 成功：`success/code/message/data`。
- 列表：`count/next/previous/results`。
- `page` 不设固定最大页码，`page_size` 为 1 至 100。
- 错误：400、401、403、404、409、422，非统一 HTTP 200 不得包装为成功。
- capability：合同阶段全部 `pending`；Mock 为 `mock`，受控实测后最多为 `sandbox/degraded/disabled`，不得提前标 `connected`。

## 8. 证据与审计冻结

- 准入提交生成证据快照、哈希和合同版本。
- 证据 stale、过期或缺失时不能返回 `ready` 或有效 `go`。
- 成功、失败、校验、权限、scope、幂等和状态冲突均留不可变审计。
- 审计及终态证据使用保护删除语义，禁止批量绕过。

## 9. 高风险边界冻结

- 不接入真实 BigSeller、Shopee、TikTok/TK、AI、银行或支付平台。
- 不提交或显示真实凭据、完整内部地址或真实业务数据。
- 不执行 Shell、Docker、SSH、SQL、Redis、部署、恢复、回滚、网络或流量命令。
- 不自动采购、通知供应商、改库存、刊登、改价、清仓、停售、归档。
- 不触发真实 RPA、付款、转账或提现。
- `go` 只是一项有时效的人工准入结论，不代表已部署或已连接。

## 10. 修改范围

本次合同冻结只修改：

- `docs/01_architecture/`
- `docs/03_api/`
- `docs/05_test/`
- `docs/06_release/`
- `docs/00_stage0/`

未修改 backend、frontend、rpa-agent、docs/04_rpa、环境配置或业务代码。无关 DOCX 与 `docs/00_stage0/architecture/` 继续排除。

## 11. P0/P1/P2

- P0：无。
- P1：待独立合同前审确认。
- P2：待独立合同前审确认。

## 12. 下一步

`UI-P8-ARCH-CONTRACT-R2` 结论为 `CONDITIONAL_PASS`。已进一步补齐 PATCH 目标授权属性、逐字段 required/nullability/范围，以及 draft/entry decision 到期规则。整改结果仍需 `UI-P8-ARCH-CONTRACT-R3` 独立复审确认；R3 达到 PASS 且无未关闭 P0/P1 后，才允许进入 UI-P8 实现、Mock/sandbox 和测试阶段。
