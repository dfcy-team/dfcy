# UI-P6 合同P1整改记录

## 1. 整改对象

依据 `ui_p6_arch_contract_recheck.md` 的 `CONDITIONAL_PASS` 结论，本次仅修订 UI-P6 页面、API、字段、permission-specific data_scope 和验收合同，不修改业务代码。

## 2. P1关闭情况

| P1 | 整改结果 | 证据 | 待复审确认 |
|---|---|---|---|
| 总接口映射保留阶段3旧路径，integrations PATCH未唯一冻结 | 已整改：旧阶段3表标记废止；移除 `suggestions/history/items/versions` 现行口径；配置 PATCH 唯一冻结为 `/configs/{id}/`；同步资源统一为 `sync-jobs/sync-runs` | `docs/00_stage0/frontend_api_mapping.md`、`docs/03_api/ui_p6_api_analysis_contract.md` | R2确认无冲突或重复路径 |
| analytics与finance请求、响应和质量字段未逐端点定义 | 已整改：冻结查询参数、分页、results字段、metrics/trend、quality、缺失值和旧字段退役规则 | `docs/03_api/ui_p6_api_analysis_contract.md`、`docs/05_test/ui_p6_api_analysis_acceptance.md` | R2确认字段可实施且无端点歧义 |
| permission-specific data_scope语义不完整 | 已整改：冻结exact permission、scope key、ALL/CUSTOM/OWN/DEPARTMENT、OR/AND组合及列表/详情/动作越权响应 | `docs/03_api/ui_p6_api_analysis_contract.md`、`docs/05_test/ui_p6_api_analysis_acceptance.md` | R2确认模块、permission与错误语义完整 |

## 3. 修改文件

- `docs/00_stage0/frontend_api_mapping.md`
- `docs/03_api/ui_p6_api_analysis_contract.md`
- `docs/05_test/ui_p6_api_analysis_acceptance.md`
- `docs/00_stage0/review/ui_p6_contract_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p6_arch_contract_r2_recheck_prompt.md`

## 4. 安全与范围确认

- 未修改 `backend/`、`frontend/` 或 `rpa-agent/` 业务代码。
- 未修改 `docs/04_rpa/`。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未加入真实账号、密码、Token、Cookie、Session、API Key、API Secret 或真实业务数据。
- 未开放自动采购、自动清仓、停售、归档、改价、真实 RPA 或资金操作。

## 5. 下一门禁

三项 P1 仅完成整改，是否正式关闭由独立 `UI-P6-ARCH-CONTRACT-R2` 复审决定。R2 通过前不得进入 UI-P6 业务实施。
