# UI-P8-ARCH-CONTRACT-R3 独立合同复审提示

请对 UI-P8 合同 R2 三项 P1 的定向整改执行独立复审，只生成审核报告，不修改合同或业务代码。

## 复审依据

- `docs/00_stage0/review/ui_p8_arch_contract_r2_recheck.md`
- `docs/00_stage0/review/ui_p8_contract_r2_p1_fix_change_log.md`
- `docs/01_architecture/ui_p8_production_pilot_security_scope.md`
- `docs/03_api/ui_p8_production_pilot_security_contract.md`
- `docs/05_test/ui_p8_production_pilot_security_acceptance.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/06_release/ui_p8_entry_notes.md`

## 允许输出

- `docs/00_stage0/review/ui_p8_arch_contract_r3_recheck.md`

## 禁止修改

- 除上述复审报告外的任何文件。
- backend、frontend、rpa-agent、`docs/04_rpa/`、deploy、环境和依赖配置。

## 必须复审

### 1. PATCH 目标授权属性

1. PATCH 改变 environment 是否同时检查资源 ID、原环境和目标环境 scope，并审计 source/target。
2. owner_id 是否完全由服务端写入，POST/PATCH 是否明确拒绝客户端 owner_id，是否不存在未冻结转移入口。
3. review_type/finance_scope 变化是否按目标组合重算 `finance.view` 和 platforms/currencies scope。
4. entry 引用在环境变化后是否重新执行 permission/scope/tenant/environment 校验。

### 2. 字段精度

1. body 默认 required、optional、nullable、PATCH省略和显式null语义是否唯一。
2. success_criteria 的数量/长度/重复，target_alias 的格式和注册语义是否明确。
3. verification 的 result_summary、error_code、error_message 是否按状态完整约束。
4. performance 的 result_mode、summary、指标 nullable、范围及 `p50 <= p95` 是否完整。
5. security review 与 entry decision 的 expires_at 是否有唯一范围和 PATCH 规则。
6. 上述错误是否可形成唯一 422 测试。

### 3. draft 与过期

1. 安全评审和准入决策是否均允许 `draft/submitted/approved -> expired`。
2. 定时与惰性处理是否使用同一 system service、行锁、版本和不可变审计。
3. 读请求触发过期后是否返回 200 expired/stale；PATCH/submit 等写动作是否先落过期状态再返回 409。
4. 过期与人工 action 并发时是否只允许一个事务成功。

### 4. 范围与安全

确认仅修订允许 docs；未修改业务代码；未接入真实平台、真实凭据、主机执行、高风险自动化或资金动作。无关 DOCX 与 `docs/00_stage0/architecture/` 继续排除。

## 报告结构

```text
# UI-P8-ARCH-CONTRACT-R3 独立合同复审报告

## 1. 复审对象与基线
## 2. 复审结论
## 3. 原P1关闭情况
## 4. PATCH目标授权属性
## 5. 请求与结果字段精度
## 6. draft、过期与职责分离
## 7. 安全与修改范围
## 8. P0
## 9. P1
## 10. P2
## 11. 是否允许进入UI-P8实现
```

## 结论规则

- 存在 P0：FAIL。
- 无 P0 但仍有 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS。

必须逐项判断三项原 P1 是否关闭。即使 PASS，也不代表允许真实平台接入、生产部署或高风险自动化。
