# UI-P7 合同 R2 P1 定向整改单

## 1. 整改对象

依据 `ui_p7_arch_contract_r2_recheck.md`，本次只修复两项合同 P1，不修改业务代码、部署配置或历史审核结论。

## 2. 整改结果

| P1编号 | 原问题 | 定向整改 | 证据 |
|---|---|---|---|
| UI-P7-CONTRACT-R2-P1-001 | ApiContractDetail 四类数组仍为未定义 object[] | 替换为 RequestFieldSpec、ResponseFieldSpec、ApiErrorSpec、ContractChangeEntry；逐字段冻结类型、required、nullable、enum/约束、说明、排序、空数组和组合校验，未知字段固定返回422 | `docs/03_api/ui_p7_governance_pilot_contract.md` 第3.1节 |
| UI-P7-CONTRACT-R2-P1-002 | 回滚人工恢复使用record权限且回滚批准来源未冻结 | `resume`仅处理release上下文；新增approve-rollback与resume-rollback，统一使用pilot.release.rollback及其独立data_scope；增加rollback approval ref、批准人、批准/失效时间、替换与失效规则、批准/记录职责分离和审计字段 | 同合同第7、8.3、8.4、9节；总映射和验收清单 |

## 3. 修改文件

- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/01_architecture/ui_p7_governance_pilot_scope.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/06_release/ui_p7_entry_notes.md`
- `docs/00_stage0/review/ui_p7_contract_freeze_report.md`
- `docs/00_stage0/review/ui_p7_contract_r2_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p7_arch_contract_r3_recheck_prompt.md`

## 4. 安全确认

- 未修改 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/` 或 `deploy/`。
- 未接入真实平台、真实AI、银行、支付或真实RPA。
- 未提交真实密钥、主机信息、连接串、备份内容或业务数据。
- Web API仍只登记计划、批准和受控主机外部执行结果，不执行部署或回滚。
- 未开放自动采购、改价、清仓、上下架或资金动作。

## 5. 待复审

整改状态需由 `UI-P7-ARCH-CONTRACT-R3` 独立确认。R3 PASS 前不允许进入UI-P7实施。
