# UI-P6-ARCH-CONTRACT-R1 独立合同前审提示

你现在在 `saas-collab-system` 中执行 UI-P6 页面、API、权限与验收合同独立前审。

## 任务性质

只审核，不修复，不修改 backend、frontend、rpa-agent、docs/04_rpa 或部署配置。只允许创建：

`docs/00_stage0/review/ui_p6_arch_contract_recheck.md`

## 审核依据

- `docs/01_architecture/ui_design_phase_execution_plan.md`
- `docs/01_architecture/ui_p6_api_analysis_scope.md`
- `docs/03_api/ui_p6_api_analysis_contract.md`
- `docs/05_test/ui_p6_api_analysis_acceptance.md`
- `docs/06_release/ui_p6_entry_notes.md`
- `docs/00_stage0/frontend_api_mapping.md`
- 最新 main 中的后端 URL、权限类、serializer、前端 router、API 封装和现有页面

## 必审内容

1. 页面范围是否覆盖角色工作台、经营总览、归因、财务只读、生命周期、清仓申请、API接入中心、平台准入和报表导出。
2. 合同路径是否与现有 backend URL 一致，是否存在同义重复接口。
3. 新页面和未验证能力是否保持 pending/mock，是否误标 connected。
4. 非公开路由是否要求 fail-closed 登记，详情路由是否继承权限。
5. action permission 是否覆盖分析计算、生命周期确认、高风险确认、清仓审批、配置维护、凭据轮换、Mock同步、导出和下载。
6. tenant、permission-specific data_scope、财务独立授权和 external/RPA 拒绝边界是否完整。
7. 财务、凭据、日志和导出敏感字段是否要求后端脱敏。
8. 数据质量、口径版本、更新时间、缺失值和来源摘要合同是否可验收。
9. 清仓申请是否只进入 Mock/审批占位，是否可能直接改变商品、价格、库存、采购、刊登或RPA状态。
10. 真实平台、生产凭据、自动采购、自动清仓、资金操作和真实RPA是否继续禁止。
11. 验收清单是否覆盖页面状态、API、权限、tenant、data_scope、浏览器、测试、构建、Docker和安全扫描。
12. 修改范围是否仅为允许的 docs 文档，现有无关 DOCX 是否保持未处理。

## 结论规则

- 有P0：FAIL。
- 无P0但有P1：CONDITIONAL_PASS。
- 无P0/P1：PASS。

## 报告结构

# UI-P6-ARCH-CONTRACT-R1 合同前审报告

## 1. 审核对象
## 2. 分支与基线
## 3. 页面合同
## 4. API合同
## 5. 路由与动作权限
## 6. tenant与data_scope
## 7. 财务与敏感字段
## 8. 清仓与高风险边界
## 9. 接入状态与数据质量
## 10. 验收合同
## 11. 修改范围
## 12. P0
## 13. P1
## 14. P2
## 15. 审核结论
## 16. 是否允许进入UI-P6实施

不得把合同自检报告结论直接复制为独立审核结论；必须以代码和文档实际检查结果为准。
