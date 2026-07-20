# UI-P7-ARCH-CONTRACT-R1 独立前审提示

请对 UI-P7 治理与受控试点合同执行独立架构前审，只生成审核报告，不修改业务代码或合同内容。

## 审核依据

- `docs/01_architecture/ui_design_phase_execution_plan.md`
- `docs/01_architecture/ui_p7_governance_pilot_scope.md`
- `docs/03_api/ui_api_interaction_contract.md`
- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/05_test/ui_design_acceptance_test_plan.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/06_release/ui_p7_entry_notes.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/00_stage0/review/ui_p7_contract_freeze_report.md`
- `deploy/pilot/`
- 当前 `backend/`、`frontend/`、`rpa-agent/` 路径和权限实现。

## 允许输出

- `docs/00_stage0/review/ui_p7_arch_contract_r1_recheck.md`

## 禁止修改

- `backend/`
- `frontend/`
- `rpa-agent/`
- `docs/04_rpa/`
- `deploy/`
- `.env`、`.env.example`、Docker/依赖配置和任何业务代码。

## 重点审核

1. 分支是否基于 UI-P6 merge commit `17fc2a2`，修改是否仅为允许文档。
2. 页面是否覆盖 API治理、智能体占位、试点就绪、拓扑、恢复、发布和容量，且不重复现有页面。
3. `/api/internal/governance/*` 与 `/api/internal/pilot/*` 是否唯一、语义清晰且均正确标记 pending/mock。
4. 通用响应、分页、400/401/403/404/409/422 和非法 HTTP 200 处理是否完整。
5. `governance.*`、`pilot.*` 是否按页面/动作精确授权；external/RPA/普通 internal 是否默认拒绝。
6. permission-specific data_scope 是否明确允许 key、ALL/无 scope、列表/详情/请求体越权语义。
7. API合同、试点门禁、恢复、发布和智能体状态机是否单一且可审计。
8. 恢复/发布 API 是否仅记录计划和结果，而非直接执行 shell、Docker、SQL、部署或回滚。
9. 双主机合同是否避免暴露完整 IP、端口、连接串、密码、代理或备份秘密。
10. 智能体是否仅为 demo/placeholder，不连接真实模型、不调用工具、不写业务数据、不触发 RPA。
11. connected 是否严格要求真实会话和验收证据，真实平台连接是否仍需专项评审。
12. 自动采购、库存、刊登、改价、清仓、停售、归档、RPA 和资金动作是否继续禁止。
13. 验收是否覆盖 E2E、网络隔离、恢复、回滚、容量、tenant、权限、审计、安全扫描和 CI。
14. 是否存在真实密钥、真实平台配置、真实主机信息或真实业务数据。

## 结论规则

- 存在 P0：FAIL。
- 无 P0 但存在 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS。

## 报告结构

# UI-P7-ARCH-CONTRACT-R1 治理与受控试点合同前审报告

## 1. 审核对象
## 2. 审核结论
## 3. 分支与修改范围
## 4. 页面与信息架构
## 5. API合同
## 6. 权限与data_scope
## 7. 状态机与审计
## 8. 双主机与网络边界
## 9. 备份恢复与回滚
## 10. 智能体占位边界
## 11. 低风险灰度与容量
## 12. 测试与验收
## 13. 安全扫描
## 14. P0
## 15. P1
## 16. P2
## 17. 是否允许进入UI-P7实施

审核人员必须独立核对仓库事实，不得把合同冻结报告直接作为 PASS 证据。未执行项必须写明原因，不得伪造。
