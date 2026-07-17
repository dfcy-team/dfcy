# UI-P6-ARCH-R1 独立架构复审提示

请执行 UI-P6 API接入与分析复盘独立复审。只审核，不修复业务代码；输出：

`docs/00_stage0/review/ui_p6_arch_r1_recheck.md`

## 1. 复审依据

- `docs/01_architecture/ui_p6_api_analysis_scope.md`
- `docs/03_api/ui_p6_api_analysis_contract.md`
- `docs/05_test/ui_p6_api_analysis_acceptance.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/00_stage0/review/ui_p6_arch_contract_r2_recheck.md`
- `docs/00_stage0/review/ui_p6_implementation_change_log.md`
- `docs/00_stage0/review/ui_p6_verification_report.md`
- 本分支 backend/frontend 实际差异和测试。

开发自检结论只能作为线索，不得直接复制为架构实际执行结果。

## 2. 必查项

1. analytics overview/sales/inventory、metrics、aggregates 和 aggregate-mock 是否使用唯一冻结路径、逐端点参数、分页和 DTO。
2. finance analytics 三个端点是否独立授权、只读、脱敏，且无付款、转账、提现或自动确认能力。
3. exact permission data_scope 是否按 analytics、lifecycle、workflow、integrations、finance、reports 独立计算，ALL/CUSTOM/OWN/DEPARTMENT 和 400/403/404 语义是否正确。
4. reports view/export/download 是否分别计算 report_types，并与来源模块权限和 data_scope 取交集；拒绝下载是否留审计。
5. integrations PATCH 是否只有详情路径；verify/run-mock 是否只允许 Mock/Sandbox；是否没有真实连接或 production 启用。
6. 清仓申请是否只创建 Mock 审批，不能改变商品、价格、刊登、采购或 RPA 状态。
7. 前端是否统一处理 success/code/message/data、分页、loading/error/empty、degraded 和权限动作。
8. Mock 用户是否只具备查看和 Mock-safe 权限，不包含高风险生命周期确认或财务资金权限。
9. `frontend_api_mapping.md` 是否没有把未完成真实 JWT Pilot 联调的接口标为 connected。
10. 是否没有真实平台、真实密钥、真实数据、真实 RPA 或高风险自动化。

## 3. 实际执行

环境允许时重新执行并记录：

- Django check。
- migration 一致性检查。
- UI-P6 定向 pytest 与全量 pytest。
- 前端定向测试、全量测试和 build。
- Docker Compose 配置检查。
- RPA JSON 校验。
- API路径、权限、状态标记和安全扫描。
- 桌面与移动端浏览器检查；若未执行真实认证态 Pilot 联调，必须明确记录且保持 pending。

未执行项必须写明原因，不得伪造。

## 4. 报告结构

# UI-P6-ARCH-R1 API接入与分析复盘独立复审报告

## 1. 复审对象
## 2. 复审结论
## 3. API合同一致性
## 4. analytics与数据质量
## 5. finance只读与脱敏
## 6. integrations与平台边界
## 7. lifecycle、workflow与高风险边界
## 8. reports导出与审计
## 9. tenant、permission与data_scope
## 10. 前端状态与权限
## 11. 测试、构建与浏览器证据
## 12. 安全扫描
## 13. P0
## 14. P1
## 15. P2
## 16. 是否允许UI-P6正式收尾

## 5. 结论规则

- 有 P0：FAIL。
- 无 P0 但有 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS。

即使 PASS，也不表示允许接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台，不允许自动采购、自动清仓/停售/归档/改价、真实 RPA 或资金操作。
