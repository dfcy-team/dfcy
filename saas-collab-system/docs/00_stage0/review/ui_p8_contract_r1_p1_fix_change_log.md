# UI-P8 合同 R1 P1 整改变更日志

## 1. 整改对象

依据 `ui_p8_arch_contract_r1_recheck.md`，本次只修订 UI-P8 合同、范围、映射、验收和进入说明，不修改 backend、frontend、rpa-agent、`docs/04_rpa/`、部署配置或历史审核结论。

## 2. P1 关闭情况

| P1编号 | 原问题 | 整改结果 | 证据 |
|---|---|---|---|
| UI-P8-ARCH-R1-P1-001 | 创建授权、跨资源证据及财务权限的 data_scope 未精确冻结 | 创建固定使用 plan permission + `pilot_environments`；存量资源 action 使用 exact permission 的资源 ID scope；准入引用逐类校验 view permission/scope/tenant/environment；财务边界固定叠加 `finance.view` 及其 scope | `ui_p8_production_pilot_security_contract.md` 第3节；scope 第4至5节；验收第2节 |
| UI-P8-ARCH-R1-P1-002 | 各 action 端点请求、响应、校验和错误合同不完整 | 增加公共类型、Detail/Summary 模型和逐端点矩阵；冻结 POST/PATCH/submit/approve/reject/record-result/cancel 的 header、body、成功 data、状态、未知/禁止字段与400/401/403/404/409/422 | API合同第2、4至10节；验收第6节 |
| UI-P8-ARCH-R1-P1-003 | 过期、取消及职责分离状态机未完全闭合 | 增加逐资源迁移矩阵；创建人不得批准验证/性能；记录人与批准人分离；取消固定使用专用 cancel permission 且已提交计划拒绝创建人取消；冻结system过期、惰性检查、并发、审计和防绕过 | API合同第11至12节；scope第5节；验收第3至4节 |

## 3. 修改文件

- `docs/03_api/ui_p8_production_pilot_security_contract.md`
- `docs/01_architecture/ui_p8_production_pilot_security_scope.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/05_test/ui_p8_production_pilot_security_acceptance.md`
- `docs/06_release/ui_p8_entry_notes.md`
- `docs/00_stage0/review/ui_p8_contract_freeze_report.md`
- `docs/00_stage0/review/ui_p8_contract_r1_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p8_arch_contract_r2_recheck_prompt.md`

## 4. 安全确认

- 未修改业务代码、依赖、环境或部署配置。
- 未接入真实平台、AI、银行、支付或真实 RPA。
- 未提交真实账号、密码、Token、Cookie、Session、API Key、API Secret、私钥、主机地址、连接串或真实业务数据。
- 未开放 Shell、Docker、SSH、SQL、Redis、部署、恢复、回滚、网络或流量执行端点。
- 未允许自动采购、供应商通知、库存修改、刊登、改价、清仓、停售、归档或资金动作。

## 5. 待复审

三项 P1 的整改状态仍需 `UI-P8-ARCH-CONTRACT-R2` 独立复审确认。R2 PASS 前不允许进入 UI-P8 实现。
