# UI-P7-ARCH-CONTRACT-R3 独立复审提示

请独立复审 UI-P7 合同 R2 遗留两项 P1 的定向整改，只生成报告，不修改合同或业务代码。

## 复审依据

- `docs/00_stage0/review/ui_p7_arch_contract_r2_recheck.md`
- `docs/00_stage0/review/ui_p7_contract_r2_p1_fix_change_log.md`
- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/01_architecture/ui_p7_governance_pilot_scope.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/06_release/ui_p7_entry_notes.md`
- 当前 `backend/`、`frontend/`、`rpa-agent/` 实现证据。

## 允许输出

- `docs/00_stage0/review/ui_p7_arch_contract_r3_recheck.md`

## 禁止修改

- 除R3报告外的任何文件。
- `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/`、`deploy/`、环境和依赖配置。

## 必须复审

1. ApiContractDetail 是否不再包含未定义 object[]。
2. RequestFieldSpec、ResponseFieldSpec、ApiErrorSpec、ContractChangeEntry 是否逐字段定义类型、required、nullable、enum/约束和description。
3. 四类item的排序、空数组、null及type/item_type/schema_ref组合规则是否可直接测试。
4. 发布resume是否只处理manual_context=release并要求pilot.release.record。
5. 回滚是否具备独立approve-rollback、resume-rollback、record-rollback，且均要求pilot.release.rollback及该permission的data_scope。
6. 原发布审批是否明确不自动授权回滚；rollback_approval_ref、批准人、批准时间、失效时间是否保存；匹配、过期、替换、离开/重入状态及commit/tag/rollback_point变化的失效和审计语义是否可直接测试。
7. 创建人、发布审批人、回滚批准人和回滚结果记录人是否满足职责分离。
8. 403/404/409/422、版本、幂等、状态冲突和越权测试合同是否完整。
9. 35项原端点加2项回滚专用端点是否唯一且全部保持pending。
10. 是否继续禁止真实平台、真实密钥、Web执行命令和高风险自动化。

## 结论规则

- 有P0：FAIL。
- 无P0但有P1：CONDITIONAL_PASS。
- 无P0/P1：PASS。

报告必须逐项判断两项R2 P1是否关闭，并明确是否允许进入UI-P7实施。
