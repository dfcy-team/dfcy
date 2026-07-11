# P2-ARCH-REVIEW-002 开发B阶段2前端成果审核报告

## 1. 审核对象与方法

- 审核对象：`origin/feature/phase2-b-dashboard-integration`。
- 对比基线：`origin/main`，提交 `ff726fe2e0e5868d9d754c17a797bdded499ec64`。
- 审核 HEAD：`521c065bf3d3b627e39a6e9bc4ad5ef8d4877871`。
- 审核方式：`origin/main...origin/feature/phase2-b-dashboard-integration` 差异审阅，项目目录外 detached worktree 静态扫描及实际 `npm ci`/`npm run build`。
- 未将开发B分支合并到架构审核分支，未修改开发B代码。

## 2. 分支基线与修改范围

目标分支包含 `origin/main` 和阶段2规划基线，相对 `origin/main` 领先 8 个提交、落后 0 个提交。无写入 `merge-tree` 预检未发现与当前 main 的冲突。

修改仅涉及 `frontend/`、前端 API/Mock/页面/路由/Vite 配置、接口映射、构建记录和开发B文档。未修改 `backend/`、`rpa-agent/`、`docs/04_rpa/`、`.env.example`、Docker、依赖清单或后端代码。

## 3. API同步状态页面

已增加集成配置、同步任务、同步运行记录页面和 API/Mock 模块。内部接口统一使用 `/api/internal/integrations/*`；运行 Mock 的动作路径明确为 `run-mock`。映射表将现阶段未合并接口标记为 `pending`，并保留 Mock fallback。

结果：通过（接口联调待开发A合并后复核）。

## 4. 商品状态看板

已增加状态看板、建议列表/详情和流转历史页面。前端调用 `/api/internal/products/status-*`，自动评估使用 `evaluate-mock` 语义；确认/拒绝均是后端接口请求，未将高风险商品状态在前端自动执行。

结果：通过（接口联调待开发A合并后复核）。

## 5. 财务对账差异页面

已增加平台账单、取款、银行回单、匹配与异常页面，所有新增财务 API 调用均为 `/api/finance/*`。页面明确自动匹配只产生建议、最终确认依赖后端财务授权；Mock 银行账号为掩码样例。

结果：通过。

## 6. 供应商绩效页面

内部汇总页面使用 `/api/internal/suppliers/performance/*`，供应商本人页面使用 `/api/external/supplier/performance/*`。供应商本人 API 不传入可越权的 supplier_id；未见供应商页面调用内部或财务接口。

结果：通过。

## 7. RPA失败转人工页面

已增加稳定性看板、尝试、人工队列、账号锁和页面签名页面。前端使用 `/api/internal/rpa/*` 管理口径，静态扫描未发现 `/api/rpa/tasks/claim|heartbeat|logs|screenshots|complete|fail/` Agent 执行调用，也未发现 `/admin/` 调用。RPA 管理页面未访问财务接口；人工接管、重试均为管理页面展示或后端受控动作。

结果：通过（管理端接口在开发A合并前保持 pending/mock）。

## 8. 前端构建和包体优化

在 detached worktree 实际执行：

| 项目 | 结果 |
|---|---|
| `npm ci` | 通过；87 个依赖审计结果为 0 vulnerabilities |
| `npm run build` | 通过；Vite 6.4.3，1757 modules transformed |
| 前端测试 | 未执行；`package.json` 未配置 test 脚本 |
| chunk 对比 | 主入口约 13.47 kB；Vue 约 110.31 kB；Axios 约 46.09 kB；Element Plus 约 923.26 kB |

路由懒加载和 manualChunks 已降低主入口体积。Element Plus 仍触发大于 500 kB 的 Vite warning，为非阻断观察项。

## 9. 真实平台风险提示页面

平台风险、就绪度和安全检查页面均使用 Mock 数据。数据明确显示 `production_disabled`、`sandbox_pending` 或 `mock_ready`，并声明 OAuth、真实账号、Token、Cookie、Session、平台 SDK、生产连接和高风险自动化均保持禁用。未发现真实平台连接按钮、真实 SDK 调用或真实凭据输入/保存逻辑。

结果：通过。

## 10. API映射状态

`frontend_api_mapping.md` 定义了 `connected`、`mock`、`pending` 含义；新增商品状态、供应商绩效、RPA 管理、同步和财务对账条目均为 `pending`，未将后端未合并接口标记为 `connected`。前端请求层保留 Mock fallback。

结果：通过。

## 11. 页面和权限边界

- 前端不承担真实权限判断，依赖后端 roles、permissions、data_scope。
- 财务页面只调用 `/api/finance/*`。
- 供应商本人页面不调用 `/api/internal/*` 或 `/api/finance/*`。
- RPA 管理页面不调用 Agent 执行接口，不调用 finance 或 admin。
- 高风险改价、清仓、补货、上下架和财务确认没有前端自动执行实现。

结果：通过。

## 12. 安全扫描与运行产物

静态扫描未发现真实公网平台 URL、真实 API Key/Secret、真实 Token、Cookie、Session、账号密码、真实供应商、订单、财务或银行数据。出现的 URL 为 localhost、依赖 registry、`example.invalid` 或 Mock 截图占位；凭据词仅用于禁止提示、脱敏提示或 `mock-session-only` 示例。

实际执行 `git check-ignore` 确认 `frontend/dist` 和 `frontend/node_modules` 被 `.gitignore` 忽略；`git ls-files` 未返回这两类运行产物。临时 worktree 的 ignored 状态只显示 `dist/` 和 `node_modules/`，未产生需提交文件。

## 13. P0/P1/P2

### P0

无。

### P1

1. 开发B尚未创建 GitHub PR，也没有针对其 HEAD 的远端 CI 结果。开发A后端接口尚未进入 main，开发B不能在最终合并基线上完成真实 API 路径、权限拒绝和响应结构联调验证。

### P2

1. Element Plus vendor chunk 约 923 kB，仍有 Vite chunk warning，但构建成功。
2. 前端未配置 test 脚本，当前缺少基础组件或页面冒烟自动化测试。
3. `npm ci` 输出两项 allow-scripts 提示（esbuild、vue-demi）；本次安装成功，后续应在依赖治理中明确批准策略。

## 14. 是否建议合并开发B PR

结论：**CONDITIONAL_PASS**。

当前不存在开发B PR，不建议直接合并分支。建议先合并开发A PR #5；随后开发B基于最新 main 更新或 rebase、完成 API 联调与权限拒绝场景验证、创建 PR 并通过远端 CI。P1 关闭后再执行开发B R1 合并审核。

