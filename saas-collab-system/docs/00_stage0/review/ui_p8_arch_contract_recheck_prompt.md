# UI-P8-ARCH-CONTRACT-R1 独立合同前审提示

请对 UI-P8 生产试点运维与专项安全准入合同执行独立架构前审，只生成审核报告，不修改合同或业务代码。

## 审核对象

- `docs/01_architecture/ui_design_phase_execution_plan.md`
- `docs/01_architecture/ui_design_task_split.md`
- `docs/01_architecture/ui_p8_production_pilot_security_scope.md`
- `docs/03_api/ui_p8_production_pilot_security_contract.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/05_test/ui_p8_production_pilot_security_acceptance.md`
- `docs/06_release/ui_p8_entry_notes.md`
- `docs/00_stage0/review/ui_p8_contract_freeze_report.md`
- UI-P7 已合并代码和合同，仅用于检查复用与冲突。

## 1. 基线与范围

1. 分支是否基于 `main@30ba8d8554461d5d0d5b831406f1d12f399d4e8d`。
2. 是否只修改允许的 docs。
3. 是否排除无关 DOCX 和 `docs/00_stage0/architecture/`。
4. UI-P8 是否作为 UI-P7 后受控扩展，而非真实生产上线授权。

## 2. 页面与复用

1. 五个新增页面是否各有唯一任务和用户角色。
2. 是否复用 readiness、topology、capacity、recovery、releases、security operations 和 audit。
3. 是否存在重复拓扑、容量、恢复、发布或安全运维页面。
4. 页面是否冻结 loading/empty/401/403/404/409/422/stale/offline/分页。

## 3. API 精确性

逐端点检查：

- control-room
- security-reviews 的列表、详情、PATCH、submit、approve、reject
- verification-runs 的列表、详情、PATCH、submit、approve、record-result、cancel
- performance-runs 的列表、详情、PATCH、submit、approve、record-result、cancel
- entry-decisions 的列表、详情、PATCH、submit、approve、reject

确认请求字段、响应字段、枚举、分页、排序、日期、幂等、版本、400/401/403/404/409/422 均足以指导实现和测试。

## 4. tenant、permission 与 data_scope

1. 每个 view/plan/review/record 是否有唯一 permission。
2. 每个 permission 是否有明确 scope key。
3. `all`、custom、无 scope、未知 key、非法值和越 scope 的语义是否明确。
4. 列表、详情、请求体引用和 action 的 403/404 语义是否一致。
5. external、RPA、普通 internal、finance 和跨 tenant 越权是否可测试。

## 5. 状态机与职责分离

1. 三类状态机是否有唯一合法迁移矩阵。
2. 通用 PATCH、ORM update/delete 和 bulk 操作是否明确禁止绕过。
3. 创建人、审核人、结果记录人是否职责分离。
4. 终态、失效、重复批准、版本冲突和并发是否有明确处理。
5. 准入 `go` 是否与部署执行严格分离。

## 6. 证据与审计

1. 是否冻结证据快照、哈希、版本、有效期和 stale 规则。
2. 失败、拒绝、校验、幂等和冲突是否留不可变审计。
3. 审计与终态证据是否防 update/delete/bulk 绕过和 tenant 级联删除。
4. 是否禁止证据引用携带凭据或真实敏感数据。

## 7. 高风险与安全边界

确认无：

- 真实平台、AI、银行或支付连接授权。
- 明文凭据、真实平台 URL、完整内部地址或真实业务数据。
- Shell、Docker、SSH、SQL、Redis、部署、恢复、回滚、网络或流量执行端点。
- 自动采购、改库存、刊登、改价、清仓、停售、归档、真实 RPA 或资金动作。
- HTTP 200、Mock、`go` 或路径存在被误解释为 `connected`/已部署。

## 8. 验收可执行性

确认验收清单可以实际覆盖：

- Django、migration、pytest、组件测试、全量测试、build。
- 受限角色 JWT 浏览器 E2E。
- Docker、RPA JSON、API路径、密钥和运行产物扫描。
- 远端 CI 与审核 HEAD 一致性。

## 报告输出

创建：`docs/00_stage0/review/ui_p8_arch_contract_r1_recheck.md`

结构：

```text
# UI-P8-ARCH-CONTRACT-R1 独立合同前审报告

## 1. 审核对象与基线
## 2. 审核结论
## 3. 页面与复用
## 4. API合同
## 5. tenant、权限与data_scope
## 6. 状态机与职责分离
## 7. 证据与不可变审计
## 8. 高风险与安全边界
## 9. 验收可执行性
## 10. P0
## 11. P1
## 12. P2
## 13. 是否允许进入UI-P8实现
```

结论规则：

- 有 P0：FAIL。
- 无 P0 但有 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS。

即使合同 PASS，也不代表允许真实平台接入、生产部署或高风险自动化。
