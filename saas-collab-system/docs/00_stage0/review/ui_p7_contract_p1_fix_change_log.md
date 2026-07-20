# UI-P7 合同 P1 整改变更日志

## 1. 整改对象

依据 `ui_p7_arch_contract_r1_recheck.md`，本次仅整改合同文档，不修改 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/` 或部署配置。

## 2. P1关闭情况

| P1编号 | 原问题 | 整改结果 | 证据 |
|---|---|---|---|
| UI-P7-CONTRACT-P1-001 | 未实现能力的 mock 状态缺少实现和测试证据 | 已整改：全部未实现能力统一 pending；mock名称端点改为 pending（planned mock），并冻结状态升级所需 handler、测试、会话和验收证据 | `ui_p7_governance_pilot_contract.md` 第1节；`frontend_api_mapping.md` UI-P7节；`ui_p7_governance_pilot_scope.md` 第2、4节 |
| UI-P7-CONTRACT-P1-002 | 逐端点请求、响应、分页及校验字段未精确冻结 | 已整改：冻结标量、公共响应模型、逐端点查询/请求体/data、字段类型、枚举、nullability、分页、header、版本、幂等、禁止字段及400/401/403/404/409/422 | `ui_p7_governance_pilot_contract.md` 第2至7节 |
| UI-P7-CONTRACT-P1-003 | 恢复与发布审批状态机缺少合法迁移矩阵和防绕过约束 | 已整改：增加 review 权限与专用动作端点，冻结 from/to、权限、职责分离和门禁；禁止通用状态PATCH、直接save/update/delete/admin绕过，审计不可变且采用保护语义 | `ui_p7_governance_pilot_contract.md` 第6至9节；`ui_p7_governance_pilot_acceptance.md` 第6、8节 |

## 3. 修改文件

- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/01_architecture/ui_p7_governance_pilot_scope.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/06_release/ui_p7_entry_notes.md`
- `docs/00_stage0/review/ui_p7_contract_freeze_report.md`
- `docs/00_stage0/review/ui_p7_contract_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p7_arch_contract_r2_recheck_prompt.md`

## 4. 安全确认

- 未实现业务代码或真实 Mock handler。
- 未接入真实 AI provider、BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未提交真实账号、密码、Token、Cookie、Session、API Key、API Secret、连接串、代理或备份秘密。
- 未开放 shell、Docker、SQL、备份、恢复、部署或回滚执行端点。
- 未允许自动采购、改库存、刊登、改价、清仓、上下架、RPA或资金动作。

## 5. 待复审事项

三项 P1 的“已整改”仍需 `UI-P7-ARCH-CONTRACT-R2` 独立复审确认。R2 PASS 前不允许进入 UI-P7 实施。
