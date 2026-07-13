# P3-ARCH-API-CONTRACT-FINALIZE 阶段3最终 API 合同冻结报告

## 1. 冻结对象

- 基线：`origin/main` / `28b3e068a852060092e7f0b3a56c26c2c1290407`
- 合同文档：`docs/03_api/phase3_api_contract_final.md`
- 对齐矩阵：`docs/03_api/phase3_api_alignment_matrix.md`
- 当前开发 PR：开发A #12、开发B #10，均保持 Draft。

## 2. 阻断原因与处理

R2 的阻断不是后端质量失败，而是开发A和开发B没有共同的最终 API 合同基线。本文档冻结后：

1. analytics 看板使用后端 `overview/`、`sales/`、`inventory/` 聚合路径；metrics/aggregates 保留为指标配置与明细资源，前端不得自行拼接跨权限或跨 tenant 数据。
2. alerts 使用 inventory/business 两类资源。
3. replenishment 使用 recommendations；lifecycle 历史使用 decisions；config 使用 definitions、values、change-logs。
4. finance analytics 保持 `/api/finance/*` 独立授权；report exports 保持 `/api/report/*` 与导出审计。
5. 集合响应统一为 `count`、`next`、`previous`、`results`，并采用标准成功/错误语义。

## 3. 冻结后责任

- 开发A：新增 analytics overview/sales/inventory 聚合端点，并在既有资源上完成统一分页/响应、serializer、错误语义、tenant/data_scope/权限与接口测试；不增加兼容性重复 URL。
- 开发B：按合同替换 API 路径，analytics 改为 metrics/aggregates 组合，完成响应/分页/错误处理和字段映射。
- 架构人员：待两方整改提交后执行实际 API 联调 R1 复审。

## 4. 不变边界

- 不修改 backend、frontend、rpa-agent 或 docs/04_rpa 业务内容。
- 不接入真实平台、银行或支付系统；不提交真实凭据或业务敏感数据。
- 不允许自动采购、清仓、停售、归档、改价、付款、转账、提现或真实 RPA 自动化。
- 财务独立授权、tenant/data_scope、导出审计和人工确认边界保持有效。

## 5. 准入结论

本合同分支可作为共同合同基线 PR 提交 main。合同合并后，开发A PR #12 与开发B PR #10 仍不得直接转 Ready 或合并；仅在分别完成合同整改、测试和实际 R1 联调后，才可重新评估。
