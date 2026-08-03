# Shopee / TikTok Shop 授权基础测试报告

测试日期：`2026-08-03`；分支：`feature/module-a-platform-auth-foundation`；基线：`bdad2fed25b3897f3f6aeae67d18d5f7239ca4a1`。

## 覆盖范围

- 两 tenant、Shopee/TikTok、多门店与跨 store scope 隔离。
- 全局平台门店身份跨 tenant 唯一，平台间身份不碰撞。
- StoreMaster tenant、平台类型、区域和 IntegrationConfig 一致性。
- `pending/active/error/revoked` 合法迁移及非法状态冲突；expired/retry 合同由同一状态机约束。
- 直接 save/update/bulk/delete 防绕过与不可变 IntegrationAuditLog。
- synthetic reference 原子轮换、行锁重读和版本连续递增。
- 六个 exact permission 互不替代；missing/empty/unknown/invalid scope 拒绝。
- 401、403、404、409、422 语义，统一列表/详情响应和分页。
- raw credential 字段拒绝且不在响应、异常或审计中回显。
- 历史 ciphertext 迁移守卫不读取或打印原值。

## 自动化结果

| 命令 | 结果 |
|---|---|
| `.venv python -m pytest backend/tests/test_shopee_tiktok_auth_foundation.py -q` | PASS，15 passed |
| integrations/sync/UI-P2 定向回归 | PASS，51 passed |
| `.venv python -m pytest backend/tests -q` | PASS，427 passed |
| `manage.py check` | PASS，0 issues |
| `manage.py makemigrations --check --dry-run` | PASS，No changes detected |
| 内存 SQLite `manage.py migrate --noinput` | PASS，全部迁移成功 |
| `manage.py sync_permissions --check` | PASS，catalog complete |
| `npm test -- --maxWorkers=1 --minWorkers=1` | PASS，12 files / 160 tests |
| `npm run build` | PASS，6.54s；无 chunk-size warning |
| `sandbox.ps1 contract integration` | PASS |
| `sandbox.ps1 verify integration` | BLOCKED，Docker Desktop Linux engine 未运行 |

## 安全结果

- 受控 secret pattern 扫描和真实平台 HTTP code 扫描均 0 命中。
- `pip check` 通过；本机没有 `pip-audit` 或 `gitleaks`。
- npm 依赖审计未通过：完整依赖树 2 high，生产依赖树 1 high；为既有前端依赖风险，本 PR 未修改 frontend。
- 没有跟踪 dist、node_modules、cache、SQLite、日志、截图或 `.env.local`。

## 结论

授权基础的模型、权限、scope、凭据引用和迁移守卫达到本地代码验收要求。由于 Docker verify 尚未执行成功且 npm audit 存在既有 high 风险，结论为 `PASS_WITH_BLOCKERS`；PR 必须保持 Draft，并等待架构、安全和依赖复审。真实平台状态仍为 `pending`。
