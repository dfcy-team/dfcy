# PR-A3 销售与库存离线导入测试报告

日期：2026-08-10

Base SHA：`75995f74ec74a3315065ecfcec317edda8b1df73`

分支：`feature/module-a-sales-inventory-import`

能力：normalized synthetic/offline only；Shopee/TikTok Shop `pending/mock`；Production synchronization OFF。

## 1. 自动化结果

| 验证 | 结果 |
|---|---|
| `git diff --check` | PASS |
| Django check | PASS |
| migration drift | PASS，0 changes |
| SQLite fresh migration | PASS |
| SQLite upgrade（unapply/reapply `marketplace_imports.0001`） | PASS |
| focused pytest | PASS，40 passed |
| backend full | PASS，583 passed / 3 MySQL-only skipped |
| frontend full | PASS，13 files / 163 tests |
| frontend production build | PASS，1957 modules |
| CI guard / credential scan | PASS，0 findings |
| forbidden artifact scan | PASS，0 findings |
| API boundary scan | PASS，无 network/task/webhook/live-provider import |
| MySQL 8.4 | BLOCKED：Docker CLI 存在但 daemon 未运行；本机无 mysql CLI |
| Local Sandbox | NOT REQUIRED for this offline-only implementation; no runtime deployment used as evidence |

前端命令最初受受控沙箱的 esbuild 父目录扫描限制阻断，随后在无源码改动的 ASCII 临时副本中、经批准的沙箱外只读构建环境复跑并通过；临时副本、`node_modules` 和 `dist` 已清理。

## 2. 必测场景

| # | 场景 | 结果 |
|---:|---|---|
| 1–2 | initial / incremental orders | PASS |
| 3–6 | 重复、旧事件、同时间冲突、cancelled/terminal 保护 | PASS |
| 7–8 | 五种退款状态、重复/旧事件/terminal 保护 | PASS |
| 9–12 | inventory initial、重复、同时间冲突、负数拒绝 | PASS |
| 13–17 | cursor mismatch、watermark、失败原子性、重放、key/payload 冲突 | PASS |
| 18–20 | tenant/store/platform 隔离 | PASS |
| 21–25 | 空/未知/非法 scope、view/sync/retry、external/RPA/匿名拒绝 | PASS |
| 26–28 | raw credential、unknown field、live/production source 拒绝 | PASS |
| 29 | real adapter 返回 `PLATFORM_RESPONSE_CONTRACT_PENDING` | PASS |
| 30 | 无真实网络请求 | PASS（静态边界与自动化断言） |
| 31 | 无计划任务、webhook 或平台写操作 | PASS（静态边界与自动化断言） |

## 3. 受控结论

离线 normalized contract、领域模型、幂等、游标和隔离测试通过。本报告不证明真实 Shopee/TikTok API adapter 可用，不证明真实订单/库存同步完成，也不批准 Production。MySQL 8.4 结果保持 BLOCKED，必须由后续独立复审环境补跑；不得将 3 个 MySQL-only skip 写为 PASS。

A-REAL-PLATFORM-CONNECTION 仍为 FAIL / REQUEST CHANGES。Shopee 与 TikTok Shop 均为 `pending/mock`。
