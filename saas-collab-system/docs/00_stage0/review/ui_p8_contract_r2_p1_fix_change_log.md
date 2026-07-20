# UI-P8 合同 R2 P1 定向整改单

## 1. 整改对象

依据 `ui_p8_arch_contract_r2_recheck.md`，本次仅整改三项合同 P1，不修改业务代码、历史审核结论、部署配置或依赖。

## 2. 整改结果

| P1编号 | 原问题 | 定向整改 | 证据 |
|---|---|---|---|
| UI-P8-ARCH-CONTRACT-R2-P1-001 | PATCH 修改环境、owner 和 finance_scope 时目标授权校验不完整 | 环境变更同时要求资源 ID、原环境和目标环境 scope；owner_id 改为服务端固定 actor 并从 POST/PATCH 移除；review_type/finance_scope 变化按目标组合重算 finance.view 和 scope | API合同第3.3、3.5、4.2、6节；scope第4节；验收第2节 |
| UI-P8-ARCH-CONTRACT-R2-P1-002 | 创建和结果字段 cardinality、长度、范围、required/nullable 不完整 | 冻结默认 required、PATCH省略/null语义、数组规则；补 success_criteria 数量、alias注册、摘要/错误长度、性能指标范围与p50/p95关系、entry有效期 | API合同第2.1、6至9节；验收第6节 |
| UI-P8-ARCH-CONTRACT-R2-P1-003 | draft 到期和 entry decision 有效期未闭合 | 安全评审与准入决策统一允许 draft/submitted/approved -> expired；entry有效期固定未来30天，安全评审未来180天；过期draft禁止PATCH/submit，system审计后返回409 | API合同第6、9、11.1至11.2节；scope第5节；验收第3节 |

## 3. 修改文件

- `docs/03_api/ui_p8_production_pilot_security_contract.md`
- `docs/01_architecture/ui_p8_production_pilot_security_scope.md`
- `docs/05_test/ui_p8_production_pilot_security_acceptance.md`
- `docs/00_stage0/review/ui_p8_contract_freeze_report.md`
- `docs/06_release/ui_p8_entry_notes.md`
- `docs/00_stage0/review/ui_p8_contract_r2_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p8_arch_contract_r3_recheck_prompt.md`

## 4. 安全确认

- 未修改 backend、frontend、rpa-agent、`docs/04_rpa/`、deploy 或环境配置。
- 未添加真实平台、真实凭据、完整内部地址、连接串或真实业务数据。
- 未开放 Shell、Docker、SSH、SQL、Redis、部署、恢复、回滚、流量、网络或平台连接执行端点。
- 未允许自动采购、供应商通知、库存修改、刊登、改价、清仓、停售、归档、真实 RPA 或资金动作。

## 5. 待复审

三项整改必须由 `UI-P8-ARCH-CONTRACT-R3` 独立确认。R3 PASS 前不允许进入 UI-P8 实现。
