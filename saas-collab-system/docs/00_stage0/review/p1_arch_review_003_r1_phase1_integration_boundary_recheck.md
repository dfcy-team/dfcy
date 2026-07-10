# P1-ARCH-REVIEW-003-R1 阶段1集成与边界R1复审报告

## 1. 复审对象

- 复审任务：P1-ARCH-REVIEW-003-R1 阶段1集成与边界 R1 复审
- 项目根目录：`saas-collab-system/`
- 当前分支：`feature/p1-arch-r1-review`
- 复审时间：2026-07-10
- 复审人员：系统架构需求拆分和核实人员 / 架构设计员
- 前置报告：`docs/00_stage0/review/p1_arch_review_002_r1_frontend_fix_recheck.md`
- 复审范围：
  - `backend/`
  - `frontend/`
  - `rpa-agent/`
  - `docs/00_stage0/frontend_api_mapping.md`
  - `docs/00_stage0/review/`
  - `docs/03_api/`
  - `docs/04_rpa/`
  - `docs/05_test/`
  - `docs/06_release/`
  - `README.md`
  - `.env.example`
  - `.gitignore`
  - `docker-compose.yml`
- 复审性质：只审核，不修复；未修改业务代码。

## 2. 复审结论

PASS

判断依据：

- 未发现 P0。
- 原阶段1开发B相关 P1 已由 `P1-ARCH-REVIEW-002-R1` 判定关闭。
- 本次集成与边界复审未发现新的 P1。
- 仅存在 P2 文档链路和 chunk warning 观察项，不阻断阶段1整体收尾。

## 3. 前端R1复审摘要

引用 `docs/00_stage0/review/p1_arch_review_002_r1_frontend_fix_recheck.md` 结论：

- 结论：`PASS`。
- 7 个原 P1 均已关闭。
- 未发现 P0。
- 未发现未关闭 P1。
- 允许阶段1前端收尾。
- 保留 P2：当前 R1 分支缺少原始审核报告文件；Vite chunk size warning 作为阶段2观察项。

## 4. 接口路径一致性

| 检查项 | 结论 | 证据 | 备注 |
|---|---|---|---|
| 内部接口使用 `/api/internal/*` | PASS | `backend/config/urls.py`、`frontend/src/api/products.js`、`frontend/src/api/purchasing.js` | 商品、采购、账号等内部后台接口使用 internal 分区 |
| 供应商接口使用 `/api/external/*` | PASS | `backend/config/urls.py`、`backend/apps/suppliers/urls_external.py`、`frontend/src/api/suppliers.js` | 供应商任务与出货路径为 `/api/external/supplier/*` |
| RPA Agent 执行接口使用 `/api/rpa/*` | PASS | `backend/apps/rpa/urls.py`、`docs/04_rpa/rpa_api_protocol.md`、`rpa-agent/README.md` | claim/heartbeat/logs/screenshots/complete/fail 均在 `/api/rpa/*` |
| 财务接口使用 `/api/finance/*` | PASS | `backend/config/urls.py`、`backend/apps/finance/urls.py` | 财务 health 占位使用 finance 分区并受财务权限保护 |
| 报表接口使用 `/api/report/*` | PASS | `backend/config/urls.py`、`backend/apps/reports/urls.py` | 报表 health 占位使用 report 分区 |
| 前端不调用 `/admin/` | PASS | `rg` 扫描 `frontend/src`、`frontend/README.md` | 未发现业务调用 `/admin/`；README 明确禁止 |
| 供应商页面不访问 `/api/internal/*` | PASS | `frontend/src/api/suppliers.js`、供应商页面 | 供应商页面只使用 `/api/external/supplier/*` |
| RPA 页面不访问 `/api/finance/*` 或 `/admin/` | PASS | `frontend/src/api/rpa.js`、RPA 页面 | RPA 管理页面使用 internal pending/mock 查询，不访问 finance/admin |

## 5. 前后端接口一致性

商品：

- 后端存在 `/api/internal/products/research/`。
- 后端存在 `/api/internal/products/spus/`。
- 后端存在 `/api/internal/products/skus/`。
- 后端存在 `/api/internal/products/spus/{id}/freeze-code/`。
- 前端 `frontend/src/api/products.js` 已按上述路径联调或提供 Mock/API 切换。
- 商品页面具备 loading/error/empty/list/detail 和 freeze-code 操作。

采购：

- 后端存在 `/api/internal/purchasing/orders/`。
- 前端 `frontend/src/api/purchasing.js` 与页面路径一致。
- 采购页面具备 loading/error/empty/list/detail。

供应商：

- 后端存在 `/api/external/supplier/tasks/`。
- 后端存在 `/api/external/supplier/tasks/{id}/feedback/`。
- 后端存在 `/api/external/supplier/shipments/`。
- 前端 `frontend/src/api/suppliers.js` 与页面路径一致。
- 供应商页面未访问 internal/finance/admin。

RPA：

- Agent 执行接口仍为 `/api/rpa/*`。
- 前端管理页面不模拟 Agent token。
- 前端管理页面使用 `/api/internal/rpa/tasks/` pending/mock 查询。
- `docs/00_stage0/frontend_api_mapping.md` 中 RPA 管理查询状态为 `pending`，未误标 `connected`。
- 未发现前端直接触发真实 RPA 执行。

综合结论：PASS。

## 6. tenant与权限边界

结论：PASS。

证据：

- `backend/apps/products/models.py`、`purchasing/models.py`、`suppliers/models.py`、`rpa/models.py` 等核心模型具备 tenant 或 tenant_id。
- `backend/apps/products/views.py` 按 `request.user.tenant` 过滤商品市调、SPU、SKU。
- `backend/apps/purchasing/views.py` 按 `request.user.tenant` 过滤采购订单。
- `backend/apps/suppliers/views.py` 按 tenant + supplier_id 过滤供应商任务和出货。
- `backend/apps/finance/views.py` 使用 `IsFinanceUser`。
- `backend/apps/rpa/views.py` 使用 `IsRPAAgent`，按 tenant 处理 RPA 任务。
- 测试文件覆盖 tenant 隔离、供应商越权、财务权限、RPA权限、external/rpa 拒绝访问业务接口等场景。

确认：

- 普通 internal 不默认访问财务敏感接口。
- external 不能访问 internal。
- rpa 不能访问业务后台和财务接口。

## 7. RPA边界

结论：PASS。

证据：

- `docs/04_rpa/rpa_api_protocol.md` 明确 RPA Agent 只能访问 `/api/rpa/*`。
- `rpa-agent/README.md` 明确禁止访问 `/api/finance/*`、`/api/internal/finance/*`、`/admin/`，禁止直连 MySQL/Redis。
- `backend/apps/rpa/urls.py` 提供 claim、heartbeat、logs、screenshots、complete、fail 执行端点。
- `backend/apps/rpa/views.py` 中 complete/fail 只回写执行结果与错误/人工接管字段，不做业务审批判断。
- `docs/04_rpa/examples/bigseller_update_price_payload.json` 和 `rpa-agent/tasks/examples/bigseller_update_price_payload.json` 包含 `approval_status=approved` 等审批凭证字段。
- `frontend/src/api/rpa.js` 不调用 Agent 执行接口。

确认：

- RPA 不做业务判断。
- 改价、清仓、补货、上下架仍需后端审批。
- 未新增真实 RPA 脚本。
- 未连接真实 BigSeller。

## 8. 安全与密钥扫描

结论：PASS。

扫描结果：

- 未发现真实 `.env`。
- 未发现真实数据库密码。
- 未发现真实 Django SECRET_KEY。
- 未发现真实 API Key。
- 未发现真实 Token/Cookie/Session。
- 未发现真实平台凭据。
- 未发现真实银行/财务数据。
- 未发现真实供应商/订单数据。

命中项说明：

- `.env.example` 中 `change-me-*` 为示例值。
- `rpa-agent/.env.example` 中 `RPA_AGENT_TOKEN=change-me-rpa-token`、`BIGSELLER_LOGIN_URL=https://example.com/bigseller-login` 为示例值。
- 文档中的 BigSeller、Shopee、TikTok、Token、银行等词汇为边界说明、禁止说明或 demo/placeholder。
- `frontend/src/mock/suppliers.js` 中 `MOCK-TRACKING-ONLY` 为占位物流单。
- `frontend/package-lock.json` 中 `integrity` 为依赖校验字段，不是密钥。

## 9. 运行与测试证据

| 项目 | 结果 | 证据 | 备注 |
|---|---|---|---|
| 开发A后端测试记录 | 已记录通过 | `p1_a_001_change_log.md`、`p1_a_002_change_log.md`、`p1_a_003_change_log.md` | 记录 `python manage.py check` 与 pytest 通过，最高记录 `76 passed` |
| 开发B `npm install` | 已记录成功 | `p1_b_fix_007_build_result.md` | 记录 `found 0 vulnerabilities` |
| 开发B `npm run build` | 已记录成功 | `p1_b_fix_007_build_result.md` | 首次因本地权限失败，提升权限后成功 |
| Vite chunk warning | 已记录 | `p1_b_fix_007_build_result.md` | 主 JS chunk 约 `1,134.77 kB`，不阻断，列 P2 观察 |
| `git check-ignore` `.gitkeep` | 本次执行，无输出 | `git check-ignore -v rpa-agent/cache/.gitkeep rpa-agent/downloads/.gitkeep` | 符合验收标准 |
| `frontend/dist` / npm cache 未跟踪 | `frontend/dist/`、`frontend/node_modules/` 为 ignored | `git status --short --ignored frontend rpa-agent` | 不作为提交交付物 |
| Docker compose config | 本次未执行 | 原因：只审核任务，不连接/启动环境，不产生外部依赖副作用 | 需在 CI 或发布验证环境执行 |
| RPA JSON 校验 | 本次未执行 | 原因：本次重点为 R1 边界复审；历史 AR0-004-R1/AR0-007 已记录通过 | 阶段2 CI 中建议固化 |

未伪造未执行命令结果。

## 10. 原P1关闭情况

| 原P1编号 | 是否关闭 | 证据 | 备注 |
|---|---|---|---|
| P1-ARCH-FINAL-P1-001 | 是 | `frontend/src/api/request.js`、`p1_b_fix_001_api_switch_change_log.md` | Mock/API 切换已落地 |
| P1-ARCH-FINAL-P1-002 | 是 | `frontend/src/views/products/`、`purchasing/`、`suppliers/`、`rpa/` | 核心页面不再仅为 Stage0Placeholder |
| P1-ARCH-FINAL-P1-003 | 是 | `docs/00_stage0/frontend_api_mapping.md` | 接口映射已覆盖阶段1核心路径 |
| P1-ARCH-FINAL-P1-004 | 是 | `frontend/src/api/rpa.js`、RPA 页面、`frontend/README.md` | 前端不模拟 Agent，不调用执行端点 |
| P1-ARCH-FINAL-P1-005 | 是 | `git check-ignore` 无输出，两个 `.gitkeep` 存在 | `.gitkeep` 不再被忽略 |
| P1-ARCH-FINAL-P1-006 | 是 | `p1_b_fix_007_build_result.md` | 构建结果与 warning 已记录 |
| P1-ARCH-FINAL-P1-007 | 是 | `p1_b_fix_summary.md`、`p1_b_fix_001` 至 `007` | 变更日志与安全确认已补齐 |

## 11. 新增问题

P0：

- 无。

P1：

- 无。

P2：

| 问题编号 | 问题 | 影响 | 建议 |
|---|---|---|---|
| P1-ARCH-REVIEW-003-R1-P2-001 | 当前 R1 分支未包含原始 `p1_arch_review_002_frontend_result_review.md`、`p1_arch_review_003_phase1_integration_boundary_review.md`、`p1_arch_final_phase1_closure_report.md` | 不阻断 R1 复审，但影响审核链路完整性 | 合并前确认原始审核报告是否需要补入当前分支或由 PR 历史关联 |
| P1-ARCH-REVIEW-003-R1-P2-002 | Vite chunk size warning 仍存在 | 不阻断阶段1整体收尾 | 阶段2评估路由懒加载或 manualChunks |
| P1-ARCH-REVIEW-003-R1-P2-003 | Docker compose config 与 RPA JSON 校验本次未执行 | 不阻断本次只审核复审 | 在 CI 或发布验证环境固化执行记录 |

## 12. 是否允许阶段1整体收尾

允许阶段1整体收尾。

依据：

- 开发A后端已 PASS。
- 开发B前端 P1 整改 R1 已 PASS。
- 集成与边界 R1 未发现 P0/P1。
- 剩余问题均为 P2，不阻断阶段1整体收尾。

## 13. 是否允许进入阶段2准备

允许进入阶段2准备。

建议阶段2优先准备：

- 平台 API 接入安全评审。
- 前端路由懒加载或 chunk 拆分优化。
- CI 固化：后端 check、pytest、前端 build、Docker config、RPA JSON 校验、安全扫描。
- 真实平台凭据托管方案。
- 高风险 RPA 动作审批和回滚机制。

## 14. 是否允许接入真实平台

不允许直接接入真实平台。

即使阶段1 R1 结论为 `PASS`，也不代表允许直接接入真实 BigSeller、Shopee、TK/TikTok、银行、支付或其他生产平台。

真实平台接入必须单独评审，至少覆盖：

- 密钥托管和轮换。
- 网络隔离与生产环境访问控制。
- 权限审计与操作审计。
- 高风险动作审批、回滚和人工接管。
- RPA 页面变化、验证码、失败截图和日志策略。
- 财务数据脱敏、独立授权和访问审计。
