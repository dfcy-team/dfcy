# P3-ARCH-INTEGRATED-FIX 阶段3整体修正报告

## 1. 修正对象

- 统一修正分支：`feature/p3-arch-integrated-fix`
- 合同基线：`docs/03_api/phase3_api_contract_final.md`
- 统一 PR：#15，目标分支 `main`
- 整合对象：开发A后端分支与开发B前端分支，原 PR #12、#10 保留 Draft。

## 2. 原P0/P1/P2

- P0：未发现。
- P1：阶段3前后端路径、资源命名、分页和错误合同不一致；已在统一分支收敛。
- P2：依赖包的 Rollup `#__PURE__` 注释警告、npm `allow-scripts` 提示，以及前端测试覆盖范围仍可继续扩展，均为非阻断观察项。

## 3. 合同冻结结果

`analytics`、`alerts`、`replenishment`、`lifecycle`、`config`、`finance analytics` 和 `report exports` 已按最终合同使用单一正式路径。集合响应统一为 `success/code/message/data`，并在 `data` 中使用 `count/next/previous/results`。

## 4. 开发A成果整合

保留开发A的指标聚合、预警、补货建议、生命周期、配置、财务分析和报表导出提交历史。统一分支补齐了 analytics 的 `overview/sales/inventory` 只读看板端点、合同分页和错误状态映射。

## 5. 开发B成果整合

保留开发B的看板、预警、补货、生命周期、配置、财务分析和报表页面提交历史。前端 API 调用已对齐最终合同，并保留 Mock fallback 与 pending 边界。

## 6. 后端修正

- 所有阶段3集合接口采用冻结分页结构。
- `409 STATE_CONFLICT` 用于重复审核或状态冲突；`422 BUSINESS_RULE_VIOLATION` 用于服务规则失败。
- 请求格式错误仍为 `400`，未认证/无权限/不可见资源仍为 `401/403/404`。
- 补货 accept/reject 只记录人工审核；生命周期 confirm/reject 只记录决策，不直接改变商品状态。

## 7. 前端修正

- 成功真实 API 响应才标记 `connected`。
- Mock、pending 与 fallback 数据不提交人工写操作。
- 前端显示后端错误信封中的错误码和消息，不将 `401/403/404/409/422` 静默降级为 Mock 成功。
- 财务仅使用 `/api/finance/analytics/*`，报表仅使用 `/api/report/*`；RPA Agent 执行接口未被前端调用。

## 8. 接口一致性

接口矩阵已更新：`docs/03_api/phase3_api_alignment_matrix.md`。库存和经营预警分资源；补货使用 `recommendations`；生命周期使用 `reviews/decisions`；配置使用 `definitions/values/change-logs`。

## 9. tenant与data_scope

核心查询按 tenant 过滤，analytics、alerts、replenishment、lifecycle 与报表导出均有 data_scope 或资源范围过滤测试。前端不拼接跨 tenant 数据，可信过滤由后端完成。

## 10. 权限与财务边界

finance analytics 由独立财务权限保护；普通 internal、external 与 RPA 均不能越权访问内部或财务敏感资源。报表导出保留 tenant、数据范围、脱敏和审计边界。

## 11. 高风险动作边界

未启用自动采购、自动清仓、停售、归档、改价、付款、转账、提现或真实 RPA。补货与生命周期页面只可提交人工审核记录，且仍由后端执行权限、状态与审计校验。

## 12. 测试与CI

本地 Django check、迁移一致性、临时数据库迁移、数据质量、阶段3专项 pytest、全量 pytest、npm ci、前端 build 和前端测试均已实际执行并通过。PR #15 的远端 CI 已通过。

## 13. 安全扫描

未发现真实平台连接、真实密钥、真实银行/财务数据或已跟踪的 dist/node_modules/缓存。凭据特征扫描的输出仅涉及 RPA/供应商任务路径文本，经复核不含凭据。

## 14. P0

无。

## 15. P1

无。

## 16. P2

- npm `allow-scripts` 提示需在后续依赖升级时继续审阅。
- Rollup 对第三方依赖 `#__PURE__` 注释给出非阻断警告。
- 浏览器携带真实登录会话的 UI 端到端流程本次未执行；接口层与测试客户端联调已执行。

## 17. 是否建议创建统一PR

建议。无 P0/P1，统一 PR #15 已创建并通过 CI，可进入人工审阅和合并审批。

## 18. 原PR处理建议

PR #10、#12 保持 Draft，不单独合并；以统一 PR #15 作为阶段3整合审计链路。
