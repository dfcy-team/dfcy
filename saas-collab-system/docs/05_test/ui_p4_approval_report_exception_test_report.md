# UI-P4 审批、报表、异常与协同回填测试报告

## 1. 测试范围

- 审批状态机、幂等、自审阻断、撤回和终态冲突。
- 异常分配、解决、关闭、tenant/data_scope 与审计。
- 微信/飞书 Mock 回调签名、时间窗、重放和生产禁用。
- 报表下载二次授权、占位下载引用和下载审计。
- 前端路由、动作权限、Mock/API 切换、离线读取恢复和高风险边界。
- 桌面与移动端页面响应式呈现。

## 2. 后端验证

| 检查项 | 结果 | 证据摘要 |
|---|---|---|
| Django check | PASS | `System check identified no issues` |
| migration 一致性 | PASS | `makemigrations --check --dry-run` 无变更 |
| 临时数据库迁移 | PASS | SQLite 临时库完整应用迁移，验证后删除临时库 |
| UI-P4 专项 pytest | PASS | 13 passed |
| 全量 pytest | PASS | 296 passed |

专项测试覆盖审批越权、请求人自审、终态重复操作、异常状态机、external/RPA 拒绝、回调 HMAC/过期/重放、生产禁用、协同确认、报表下载审计和审计不可变约束。

## 3. 前端验证

| 检查项 | 结果 | 证据摘要 |
|---|---|---|
| UI-P4 专项 Vitest | PASS | 8 passed |
| 全量 Vitest | PASS | 86 passed |
| `npm run build` | PASS | 1922 modules，约 5.81 秒 |
| API/权限路径扫描 | PASS | 工作流页面未调用 `/api/rpa/*`、`/api/finance/*` 或 `/admin/` |

专项测试覆盖显式路由和动作权限、未登记路径默认拒绝、离线读取 Mock fallback、异常分配、分页结构、Mock 写操作拒绝和高风险动作边界。

## 4. 浏览器验证

本地地址：`http://localhost:4174/`

| 视口 | 页面 | 结果 |
|---|---|---|
| 1440 x 900 | 审批中心、异常中心、报表导出 | 正常渲染，无页面级横向溢出 |
| 390 x 844 | 审批中心、异常中心、协同回填、报表导出 | 正常渲染，无页面级横向溢出 |

页面动作核验：审批页显示详情/通过/驳回/撤回；异常页显示详情/分配给我/解决/关闭；协同页显示确认/驳回；报表页按状态和权限控制申请下载。有效合同路径未发现控制台错误。测试过程中人工输入过一次未登记路径 `/workflow/collaboration`，产生一条预期的 Vue Router 无匹配警告；正式路径为 `/workflow/collaboration-events`，复测正常。

## 5. 系统与安全检查

| 检查项 | 结果 |
|---|---|
| Docker Compose 配置 | PASS |
| RPA JSON 格式 | PASS，16 个文件，0 个无效 |
| `git diff --check` | PASS |
| 真实平台连接扫描 | 未发现 |
| 真实密钥和运行产物扫描 | 未发现；`.gitkeep` 为允许的空目录占位 |

## 6. 非阻断观察项

- Vite 构建存在两条第三方 `@vueuse` PURE annotation 警告，不影响构建结果。
- 本阶段协同回调和报表下载均为 Mock/占位合同，生产执行保持禁用。
- 浏览器认证态端到端自动化仍可在后续 CI 浏览器测试中补充。

## 7. 测试结论

UI-P4 实施侧验证通过，满足提交独立架构 R1 复审的条件。本报告不替代架构复审结论。
