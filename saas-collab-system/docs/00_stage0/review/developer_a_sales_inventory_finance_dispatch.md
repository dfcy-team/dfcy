# 开发A节点分发：销售库存财务对账

## 1. 任务信息

- 负责人：开发A。
- 建议分支：`feature/module-a-sales-inventory-finance`。
- 基线：本分发 PR 合并后的最新 `main`。
- Local Sandbox profile：`sales-inventory-finance-reconciliation`。
- 风险：普通分析为 L2；财务、状态、权限、迁移、导出和审计按 L3。

## 2. 开发目标

面向销售库存和财务操作人员，使用合成数据完成“销售与库存观察 -> 库存风险 -> 补货建议 -> 对账建议 -> 差异处理”的最小闭环。系统只提供分析、预警和建议，不自动采购、不执行资金操作。

本地验收样本至少包含两个 tenant、两个平台/店铺范围、两个币种、正常/缺货/超储库存以及匹配/差异对账记录，用于验证隔离和权限。

## 3. 后端内容

1. 复用并完善 analytics 的 overview、sales、inventory、metrics 和 aggregates 查询，不新增同义路径。
2. 完善销售快照、库存读模型、覆盖天数、缺货/超储预警的数据来源、口径版本和缺失值说明。
3. 保持补货 `recommendations` 为建议资源；accept/reject 只修改建议状态，不创建采购订单。
4. 完善财务账单、提现记录、银行到账、匹配建议和异常的合成数据流程。
5. 自动匹配只生成建议；confirm/reject 必须使用 `finance.reconcile`，异常处理使用 `finance.exception.handle`。
6. 财务查询按 tenant、platform、currency scope 过滤，银行账号只返回掩码。
7. 写操作使用服务层、幂等键、状态冲突 409 和不可变审计；禁止通用 PATCH 或模型直接保存绕过。
8. 如新增模型，提交迁移并确保 `makemigrations --check --dry-run` 无差异。

## 4. 前端内容

1. 销售总览、销售趋势和库存分析使用现有 `/api/internal/analytics/*`。
2. 库存预警和补货建议展示 loading、empty、error、forbidden、degraded 和正常状态。
3. 财务对账页面只使用 `/api/finance/*`，非财务用户显示统一 403，不渲染敏感动作。
4. action 按钮分别校验 `replenishment.review`、`finance.reconcile`、`finance.exception.handle` 和导出权限；后端仍做最终判断。
5. 统一解析 `success/code/message/data` 与分页，明确处理 401、403、404、409 和 422。
6. Mock/API 切换保留；未完成本地 JWT 联调的接口不得标记 `connected`。

## 5. 权限和 data_scope

- analytics：`analytics.view/calculate/manage`，CUSTOM key 为 `analytics_dimensions`。
- 预警：`alerts.view/evaluate/manage`。
- 补货：`replenishment.view/evaluate/review`。
- 财务：`finance.view/import/export/reconcile/exception.handle`，每个 action 独立授权。
- 报表：`reports.view/export/download`，导出范围必须与来源模块 scope 取交集。

普通 internal、external、RPA 和只有销售库存权限的用户不能访问财务敏感接口。详情越权不得泄露资源存在性。

## 6. 必须测试

- 两 tenant 的列表、详情和动作隔离。
- analytics dimension 和 finance platform/currency scope 的 ALL、缺失、空、未知、非法及越权值。
- 401、403、404、409、422 和统一分页响应。
- 普通 internal 访问财务接口被拒绝；不同 finance action permission 不能互相替代。
- 补货建议不会创建 PurchaseOrder、通知供应商或触发 RPA。
- 对账不会付款、转账或提现；银行字段掩码且日志无敏感值。
- 状态不能经 PATCH、模型 save、bulk 或重复请求绕过。
- Django check、迁移一致性、模块 pytest、全量 pytest、前端 test/build、Sandbox verify 和安全扫描。

## 7. 启动与验证

```powershell
cd deploy/dev-sandbox
.\sandbox.ps1 init
.\sandbox.ps1 start sales-inventory-finance-reconciliation
.\sandbox.ps1 verify sales-inventory-finance-reconciliation
```

开发结束后同步最新 `main`，再执行：

```powershell
.\sandbox.ps1 verify integration
```

## 8. 交付物

- 模块代码、迁移和测试。
- 更新后的 API 合同与 `frontend_api_mapping.md`。
- 开发A变更日志，列明模型、权限、状态机、测试结果和安全确认。
- `Django check`、迁移、pytest、npm test/build、Sandbox verify 和 CI 证据。
- Draft PR；PR 描述标明风险等级、回滚策略和是否修改公共底座。

## 9. 禁止项

- 不接真实平台、银行或支付系统。
- 不导入真实订单、财务或银行数据。
- 不自动创建采购订单、付款、转账、提现、改价或触发真实 RPA。
- 不修改达人管理、供应链采购或 RPA 业务代码。
- 不向生产主机复制源码或本地构建产物。
