# UI-P8-ARCH-CONTRACT-R2 独立合同复审提示

请对 UI-P8 合同 R1 三项 P1 整改执行独立复审，只生成审核报告，不修改合同或业务代码。

## 复审依据

- `docs/00_stage0/review/ui_p8_arch_contract_r1_recheck.md`
- `docs/00_stage0/review/ui_p8_contract_r1_p1_fix_change_log.md`
- `docs/01_architecture/ui_p8_production_pilot_security_scope.md`
- `docs/03_api/ui_p8_production_pilot_security_contract.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/05_test/ui_p8_production_pilot_security_acceptance.md`
- `docs/06_release/ui_p8_entry_notes.md`
- UI-P7 permission/data_scope、恢复、发布和审计合同，仅用于复用一致性核对。

## 允许输出

- `docs/00_stage0/review/ui_p8_arch_contract_r2_recheck.md`

## 禁止修改

- 除上述复审报告外的任何文件。
- backend、frontend、rpa-agent、`docs/04_rpa/`、deploy、环境和依赖配置。

## 必须复审

### 1. 创建、跨资源与财务 data_scope

1. 创建是否固定使用 exact plan permission + `pilot_environments`，且不依赖尚未产生的资源 ID。
2. 详情、PATCH 和 action 是否使用各 exact permission 的资源 ID scope。
3. entry decision 引用五类证据是否逐类校验 view permission、scope、tenant 和 environment。
4. `finance_boundary` 是否固定叠加 `finance.view` 及其 scope，且只返回脱敏状态。
5. ALL、CUSTOM、缺失、未知、非法、超 scope 的 403/404 语义是否唯一可测试。

### 2. 逐端点合同

1. control-room、security-reviews、verification-runs、performance-runs、entry-decisions 是否有唯一方法、路径和 exact permission。
2. 每个 POST、PATCH、submit、approve、reject、record-result、cancel 是否冻结 header、请求体、成功 data、状态和校验。
3. Detail/Summary、分页、枚举、范围、日期、nullability、未知字段和禁止字段是否可直接构造测试。
4. 400/401/403/404/409/422 及其 code 是否无冲突。
5. HTTP 200、Mock、pending 和 connected 是否不会混淆。

### 3. 状态机与职责分离

1. 安全评审、验证、性能和准入决策是否合法迁移矩阵完整且唯一。
2. 创建人是否不能批准自己的安全评审、验证、性能或准入决策。
3. 结果记录人是否与批准人分离。
4. cancel 是否固定使用专用 exact permission，且不同状态的 actor、reason 和终态语义是否明确。
5. submitted/approved 的过期触发、system actor、定时/惰性检查、并发和审计是否闭合。
6. 通用 PATCH、save、QuerySet、bulk、admin 和级联删除是否不能绕过。

### 4. 安全与范围

确认未修改业务代码，未接入真实平台或凭据，未开放执行端点，未允许自动采购、改价、清仓、真实 RPA 或资金动作。无关 DOCX 和 `docs/00_stage0/architecture/` 必须继续排除。

## 报告结构

```text
# UI-P8-ARCH-CONTRACT-R2 独立合同复审报告

## 1. 复审对象与基线
## 2. 复审结论
## 3. 原P1关闭情况
## 4. 创建、跨资源与财务data_scope
## 5. 逐端点请求响应合同
## 6. 状态机、过期、取消与职责分离
## 7. 证据、审计与安全边界
## 8. P0
## 9. P1
## 10. P2
## 11. 是否允许进入UI-P8实现
```

## 结论规则

- 存在 P0：FAIL。
- 无 P0 但仍有 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS。

报告必须逐项判断三项原 P1 是否关闭。即使 PASS，也不代表允许真实平台接入、生产部署或高风险自动化。
