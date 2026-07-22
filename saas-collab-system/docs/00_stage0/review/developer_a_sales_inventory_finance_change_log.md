# 开发A销售库存财务对账模块变更日志

## 1. 基线与范围

- 分支：`feature/module-a-sales-inventory-finance`
- 基线：`origin/main@50224f11a4a674b569dba346998edfe3994004fd`
- 模块：销售分析、库存预警、补货建议、财务对账和差异处理。
- 风险：普通查询为 L2；财务状态、权限、迁移、审计和导出边界按 L3。

## 2. 主要变更

- 财务账单、提现记录、银行到账、匹配建议和异常列表统一为 `count/next/previous/results` 分页，并按 tenant、platform、currency 及 exact permission scope 过滤。
- 新增匹配详情 `GET /api/finance/reconciliation/matches/{id}/` 和异常处理 `POST /api/finance/reconciliation/exceptions/{id}/resolve/`。
- `run-mock` 支持 `Idempotency-Key`；缺失时按合成来源快照派生稳定键。重复确认、拒绝和异常处理返回 `409 STATE_CONFLICT`。
- `finance.view`、`finance.import`、`finance.reconcile`、`finance.exception.handle` 独立求值，不能互相替代。
- 对账和异常状态只能通过加锁服务层修改；模型 `save`、queryset `update`、`bulk_update`、非法 `bulk_create` 均不能绕过。财务审计日志不可修改或删除。
- 库存预警和补货建议改为 permission-specific `data_scope`，无关角色的 `ALL` 不再扩大资源范围。
- 前端财务列表增加可用筛选、分页、详情和独立异常处理动作；银行账号保持掩码；库存预警补齐 `VITE_USE_MOCK` fallback。
- Local Sandbox seed/fixture 覆盖两个 tenant、两个平台、USD/EUR、正常/缺货/超储库存及匹配/差异对账。

## 3. 迁移

- `finance.0002_reconciliationmatch_idempotency_key_and_more`
- 新增 `ReconciliationMatch.idempotency_key`，并对非空键增加 tenant 内条件唯一约束。
- 兼容性：字段允许空值，既有数据无需回填；回退迁移仅移除约束和字段，不触及账单、到账或审计记录。

## 4. 公共影响

- `apps.common.data_scope` 增加可选 `permission_code`，旧调用保持兼容。
- alerts/replenishment 权限过滤改为 exact permission scope，并在权限缺少 scope 时返回统一拒绝。
- 未修改达人管理、供应链采购或 RPA 业务实现。

## 5. API状态

- analytics、inventory alerts、replenishment、finance 和 reports 路径均已实现并通过单元/合同测试。
- 总映射仍标记 `pending`：Local Sandbox JWT 复验尚未完成，不因路径存在或单元测试通过而标记 `connected`。
- `evaluate-mock`、`run-mock` 和所有前端 Mock 数据继续标记 `mock` 或 synthetic。

## 6. 验证结果

- `python -m pytest backend/tests -q`：410 passed。
- `python manage.py check`：通过，0 issues。
- `python manage.py makemigrations --check --dry-run`：No changes detected。
- `npm.cmd ci`：通过，250 packages，0 vulnerabilities。
- `npm.cmd test -- --maxWorkers=1 --minWorkers=1`：通过，12 个测试文件、160 个测试全部通过。默认并行 worker 曾在本机触发 Node OOM；单 worker 复跑通过，属于本机并发资源限制，不阻断模块代码验收。
- `npm.cmd run build`：通过；存在两条 `@vueuse/core` PURE 注释位置告警，不阻断。
- `npm.cmd audit --audit-level=high`：0 vulnerabilities。
- `validate_fixtures.py`：PASS，4 fixtures。
- `git diff --check`：通过，仅有 Windows LF/CRLF 提示。
- API 路径扫描：财务页面仅使用 `/api/finance/*`；销售库存使用冻结 internal 路径。
- 敏感信息扫描：本次 diff 未发现私钥、真实 Token、Cookie、Session、API Key、API Secret 或明文凭据。
- 浏览器 Mock 冒烟：库存预警、对账匹配列表、对账异常列表和匹配详情均正常渲染，页面控制台无错误；Mock 用户保持只读，不授予 `finance.reconcile` 或 `finance.exception.handle`。

## 7. 未关闭验证项

- `sandbox.ps1 start sales-inventory-finance-reconciliation` 未完成：Docker 无法连接 `auth.docker.io:443` 拉取基础镜像。命令失败已保留原始证据，不伪造 PASS。
- 待镜像注册表网络恢复后执行模块 `verify`、本地 JWT 正负向联调及合并前 `verify integration`。

## 8. 安全确认

- 未连接真实平台、银行或支付系统。
- 未提交真实订单、供应商、财务或银行数据。
- 补货建议不创建采购订单、不通知供应商、不触发 RPA。
- 对账和异常处理不付款、不转账、不提现。
- 未提交真实账号、密码、Token、Cookie、Session、API Key、API Secret 或生产 `.env`。
