# 模块化开发验收清单

## 1. 共同准入

- [ ] 分支基于本分发 PR 合并后的最新 `main`。
- [ ] PR 初始为 Draft，变更范围与模块责任矩阵一致。
- [ ] 对应 Local Sandbox profile 基线验证通过。
- [ ] 只使用 synthetic/demo/example.com 数据和值。
- [ ] API、权限、`data_scope`、状态机和审计合同先于实现冻结。
- [ ] 不存在接口标记为 `connected`，除非本地 JWT 联调和 CI 均有证据。
- [ ] 无真实平台、银行、支付、RPA连接或真实凭据。

## 2. 开发A验收

- [ ] analytics、inventory alerts、replenishment 和 finance 路径无同义重复。
- [ ] 销售库存查询按 tenant 和 `analytics_dimensions` 过滤。
- [ ] 财务按 tenant、独立 `finance.*`、platform 和 currency scope 过滤。
- [ ] 普通 internal、external、RPA 及跨 tenant/跨 scope 请求被拒绝。
- [ ] 补货 accept/reject 只改变建议，不创建 PurchaseOrder。
- [ ] 对账只生成或确认建议，不付款、转账或提现。
- [ ] 银行字段掩码，导出与下载独立授权并记录审计。
- [ ] 状态不能经 PATCH、模型 save、bulk、并发或重复请求绕过。

## 3. 开发B验收

- [ ] profiles、collaborations、tasks、performance 使用唯一 creators 路径。
- [ ] 所有核心模型有 tenant，查询执行 `creator_dimensions`。
- [ ] view/manage/review/task/performance 权限逐 action 独立验证。
- [ ] 提交人与审核人职责分离，非法状态迁移被拒绝并审计。
- [ ] 跨 tenant、external、RPA 和超 scope 请求被拒绝。
- [ ] 联系方式、账号和备注等敏感字段不以明文返回或记录。
- [ ] Creator Mock 只读；写请求 405，未知路径 404。
- [ ] 无平台连接、自动触达、真实 RPA、结算或付款能力。

## 4. 自动化验证

- [ ] `python manage.py check` 通过。
- [ ] `python manage.py makemigrations --check --dry-run` 无差异。
- [ ] 模块 pytest 和全量 pytest 通过。
- [ ] 统一响应、分页、400/401/403/404/409/422 测试通过。
- [ ] tenant、权限、scope、敏感字段、状态机和审计负向测试通过。
- [ ] `npm ci`、`npm test`、`npm run build` 通过。
- [ ] 对应 `sandbox.ps1 verify <profile>` 通过。
- [ ] 合并前 `sandbox.ps1 verify integration` 通过。
- [ ] Docker Compose、API路径、connected状态、密钥和真实连接扫描通过。
- [ ] GitHub 必需 CI 对固定审核 HEAD 全部成功。

## 5. 审核与合并

- [ ] 变更日志列出文件、迁移、权限、状态机、测试和安全确认。
- [ ] L3 变更包含回滚、迁移兼容和发布风险说明。
- [ ] 至少一名非作者完成审核；跨模块变更包含受影响模块负责人。
- [ ] P0 为零；未关闭 P1 为零；P2 有责任人和处理期限。
- [ ] 第二个合并分支已同步最新 `main` 并重跑 integration。
