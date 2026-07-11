# P2-B-003 财务对账差异页面变更记录

## 变更

- 新增 `frontend/src/api/financeReconciliation.js`。
- 新增 `frontend/src/mock/financeReconciliation.js`。
- 新增平台账单、取款记录、银行到账、对账匹配、匹配详情和差异异常页面。
- 更新路由、`frontend/README.md` 和接口映射。

## 边界

- 所有财务接口均使用 `/api/finance/*`。
- 不调用 `/api/internal/*`、`/api/external/*`、`/admin/`。
- 仅使用 Mock/脱敏样例，不接真实银行、支付或平台账单。
- 银行账号只显示掩码，不提供付款、转账或提现按钮。

## 验证

- 财务路径和敏感字段扫描：未发现 internal/external/rpa/admin 调用、真实 URL、密钥字段或完整银行账号。
- 禁止目录扫描：`backend/`、`rpa-agent/`、`docs/04_rpa/`、`.env`、`.env.example`、`docker-compose.yml`、`requirements.txt` 无 diff。
- `npm run build`：成功。
- 构建 warning：主 JS chunk 约 `1,154.40 kB`，仍超过 500 kB；阶段2后续由 P2-B-006 处理或记录为观察项。
