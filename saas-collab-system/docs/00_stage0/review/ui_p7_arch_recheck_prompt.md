# UI-P7-ARCH-R1 独立实现复审提示

只审核，不修复。审核对象为 `feature/ui-p7-governance-pilot-readiness`，对比最新 `main`。

## 必查证据

- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/00_stage0/review/ui_p7_implementation_report.md`
- `docs/00_stage0/review/ui_p7_test_result.md`
- `backend/apps/governance/`、`backend/apps/pilot/`、`backend/apps/permissions/ui_p7_scopes.py`
- `frontend/src/api/governance.js`、`frontend/src/api/pilot.js`
- `frontend/src/views/governance/`、`frontend/src/views/pilot/`

## 复审重点

1. 37 个冻结端点是否唯一实现，未知参数/字段、分页和统一响应是否符合合同。
2. 17 个权限码、permission-specific data_scope、tenant/system scope、external/RPA拒绝是否有效。
3. 固定合同检查、助手评估和拓扑校验是否无外部调用、无工具调用、无业务写入。
4. 恢复/发布双状态机、幂等、version、职责分离、门禁、独立回滚批准和不可变审计是否可防绕过。
5. 页面路由、菜单、动作权限、loading/empty/error、mock/sandbox 状态是否正确。
6. 是否存在 Web Shell、Docker、SQL、真实部署/恢复/回滚、真实平台、真实 RPA 或资金动作。
7. 实际复跑 Django check、迁移一致性、pytest、npm ci/test/build、Compose、RPA JSON 和安全扫描。
8. 在受控账号下执行关键页面浏览器 E2E；未执行必须记录原因，不得标记 connected。

## 输出

创建 `docs/00_stage0/review/ui_p7_arch_r1_recheck.md`，结论仅允许 `PASS`、`CONDITIONAL_PASS` 或 `FAIL`：有 P0 为 FAIL；无 P0 但有 P1 为 CONDITIONAL_PASS；无 P0/P1 为 PASS。
