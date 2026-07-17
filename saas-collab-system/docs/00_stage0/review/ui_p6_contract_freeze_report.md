# UI-P6 页面、API、权限与验收合同冻结报告

## 1. 检查对象

- 基线：`main` / `8c05228c77c262a9041e0f4c78d467819ba6efb2`
- 规划分支：`feature/ui-p6-api-analytics-review`
- 阶段：UI-P6 API接入与分析复盘
- 性质：合同冻结，不修改业务代码

## 2. 冻结结果

结论：**PASS（允许进入独立合同前审）**。

已冻结页面范围、现有与待验证 API、路由和动作权限、tenant/data_scope、数据质量、敏感字段、连接证据状态、高风险动作边界及验收命令。

## 3. 页面合同

覆盖角色工作台、经营总览、销售归因、库存分析、财务只读、生命周期复盘、清仓申请、API接入中心、平台准入和报表导出。新增页面均先标记 `pending` 或 `mock`，不得仅因后端路径存在而标记 `connected`。

## 4. API合同

沿用阶段3已冻结的 analytics、lifecycle、finance analytics 和 report exports 路径，并沿用阶段2 integrations 与 UI-P4 workflow 路径。未新增同义重复接口。清仓申请复用 `approval_type=clearance`，当前只允许 Mock 创建，不直接改变商品状态。

## 5. 权限合同

- 路由默认拒绝，所有非公开路由登记 `routeCapabilities`。
- 分析、财务、生命周期、审批、接入和报表分别使用独立权限。
- 所有写动作使用 action permission，前端隐藏与处理器二次拒绝不替代后端校验。
- 高风险生命周期确认追加 `products.lifecycle.high_risk_confirm`。
- 清仓申请和审批执行 `approval_types=clearance` data_scope。

## 6. 验收合同

覆盖统一响应、分页、401/403/404/409/422、加载/空/错误/降级/离线、tenant、data_scope、财务独立权限、脱敏、审计、Mock/API状态、窄屏、后端检查、pytest、前端测试与构建、Docker配置及安全扫描。

## 7. 高风险边界

指标和建议不自动采购、补货、刊登、改价、清仓、停售、归档、修改库存或触发RPA。财务只读页不执行付款、转账、提现或自动确认对账。production adapter 和真实平台连接继续禁用。

## 8. 修改范围

本次仅新增或更新 `docs/01_architecture/`、`docs/03_api/`、`docs/05_test/`、`docs/06_release/` 和 `docs/00_stage0/review/` 文档；未修改 backend、frontend、rpa-agent、docs/04_rpa 或部署配置。独立前审入口为 `ui_p6_arch_contract_recheck_prompt.md`。

## 9. P0/P1/P2

- P0：无。
- P1：无。
- P2：归因专用后端字段、清仓真实业务联动和受控 Pilot 联调证据尚待实施；当前均明确保持 pending/mock，不阻断合同前审。

## 10. 下一步

先执行独立 UI-P6 合同前审。通过后按 `ui_p6_api_analysis_acceptance.md` 实施页面与最小接口补充；完成测试后再执行 UI-P6-ARCH-R1，不在本次合同冻结阶段直接提交业务代码。
