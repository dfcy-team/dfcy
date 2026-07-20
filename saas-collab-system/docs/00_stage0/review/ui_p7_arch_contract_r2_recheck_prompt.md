# UI-P7-ARCH-CONTRACT-R2 独立复审提示

请对 UI-P7 合同 R1 三项 P1 整改执行独立复审，只生成审核报告，不修改合同或业务代码。

## 复审依据

- `docs/00_stage0/review/ui_p7_arch_contract_r1_recheck.md`
- `docs/00_stage0/review/ui_p7_contract_p1_fix_change_log.md`
- `docs/01_architecture/ui_p7_governance_pilot_scope.md`
- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/06_release/ui_p7_entry_notes.md`
- `docs/00_stage0/frontend_api_mapping.md`
- 当前 `backend/`、`frontend/`、`rpa-agent/` 实现证据。

## 允许输出

- `docs/00_stage0/review/ui_p7_arch_contract_r2_recheck.md`

## 禁止修改

- 除上述复审报告外的任何文件。
- `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/`、`deploy/`、环境或依赖配置。

## 必须复审

1. 当前无 UI-P7 实现时，所有能力是否为 pending，planned mock 是否未误标 mock/connected。
2. 状态升级是否要求 handler、自动化、会话、联调和验收证据。
3. 每个端点是否有唯一方法/路径、exact permission、查询/请求字段、字段类型、枚举、nullability、data模型和状态。
4. page/page_size、Idempotency-Key、version、reason、approval_ref及未知字段语义是否逐端点可判定。
5. 400/401/403/404/409/422 是否能据合同构造测试。
6. 恢复与发布是否有完整专用动作端点和合法迁移矩阵。
7. 创建人与审批人是否分离，review/record/rollback 是否独立 permission/data_scope。
8. 是否明确禁止通用状态 PATCH、直接save、QuerySet update/delete、admin和批处理绕过。
9. 成功与失败动作是否写不可修改、不可删除且关联删除受保护的审计事件。
10. Web API 是否仍只记录计划和受控主机外部执行结果，不执行shell、Docker、SQL、部署、恢复或回滚。
11. 是否无真实密钥、真实主机信息、真实平台配置和高风险自动化。

## 结论规则

- 存在 P0：FAIL。
- 无 P0 但仍存在 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS。

报告必须明确三项原 P1 是否逐项关闭，以及是否允许进入 UI-P7 实施。
