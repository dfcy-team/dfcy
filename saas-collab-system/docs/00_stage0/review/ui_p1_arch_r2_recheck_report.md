# UI-P1-ARCH-R2 架构复审报告

## 1. 复审对象

- 项目：`saas-collab-system/`
- 分支：`feature/ui-p1-foundation-auth-layout`
- 复审基线HEAD：`488a38c`
- 复审日期：2026-07-16
- 复审范围：`UI-P1-R1-P1-001` 路由能力合同与 `UI-P1-R1-P1-002` 动作权限合同的定向整改。
- 复审依据：R1报告、P1整改日志、前端接口映射、UI-P1测试报告及当前代码工作树。
- 复审性质：只审核，不修复；本次除本报告外未修改业务代码或既有文档。

当前UI-P1实现仍位于未提交工作树，HEAD未包含本次整改。本文结论仅对应复审时工作树快照；创建PR前必须固定提交并复核文件范围和CI结果。

## 2. 复审结论

结论：**PASS**。

- P0：无。
- P1：无。
- P2：保留非阻断观察项。
- 两项原P1均已关闭，未发现新增P0/P1。

## 3. 原P1关闭情况

| 原P1编号 | 问题 | 是否关闭 | 复审证据 | 备注 |
|---|---|---|---|---|
| UI-P1-R1-P1-001 | 非公开路由合同不完整且未登记路径默认放行 | 是 | 65条非公开路由全部命中48条route capability规则；缺失0；未知路径拒绝；finance/internal/external/RPA矩阵通过 | `finance.view`不能进入`/finance/imports` |
| UI-P1-R1-P1-002 | 按钮和动作权限未按后端action permission收敛 | 是 | 两个通用动作组件消费`hasPermission()`；无权动作过滤；点击前二次拒绝；全部共享页面可执行动作声明后端权限码 | 后端权限仍为最终边界 |

## 4. 非公开路由合同复审

复审结果：**通过**。

1. `routeCapabilities` 已独立于菜单定义，覆盖 `router/index.js` 中全部非公开路由。
2. 独立脚本解析出65条非公开路由，48条能力规则通过最长路径继承覆盖，未登记路由为0。
3. `canAccessPath()` 对未找到合同的路径返回拒绝，不再默认放行。
4. `/finance/imports` 要求 `finance.import`；`finance.view` 只能访问财务查询页，不能继承导入能力。
5. `finance.import` 用户可进入导入页，但不能因此进入 `/finance/statements`。
6. external用户可访问 `/suppliers/tasks`，不能访问 `/products/master` 或财务页面。
7. internal用户不能进入external供应商任务页面；RPA用户不能进入内部、供应商或财务页面。
8. 详情页使用最长资源路径规则继承父资源能力，未发现短路径错误覆盖。
9. 财务菜单按 `finance.view` 与 `finance.import` 分别展示入口，与直接URL合同一致。

独立访问矩阵：

| 用户能力 | `/finance/imports` | `/finance/statements` | `/suppliers/tasks` | `/products/master` | 未登记路径 |
|---|---:|---:|---:|---:|---:|
| internal + `finance.view` | 拒绝 | 允许 | 拒绝 | 允许 | 拒绝 |
| internal + `finance.import` | 允许 | 拒绝 | 拒绝 | 允许 | 拒绝 |
| basic internal | 拒绝 | 拒绝 | 拒绝 | 允许 | 拒绝 |
| external | 拒绝 | 拒绝 | 允许 | 拒绝 | 拒绝 |
| rpa | 拒绝 | 拒绝 | 拒绝 | 拒绝 | 拒绝 |

说明：商品主数据后端当前合同为 `IsInternalUser`，因此basic internal可访问，与现有后端边界一致。

## 5. 动作权限合同复审

复审结果：**通过**。

- `actionAccess.js` 统一解析 `permission/permissions`、用户类型、显示策略、禁用状态和拒绝原因。
- `Phase2DataPage` 与 `Phase3DecisionPage` 均通过认证store的 `hasPermission()` 计算动作可见性。
- 无权动作默认隐藏；显式使用 `unauthorizedBehavior=disable` 时可禁用并显示缺失权限原因。
- 两个通用组件均在调用 `handler/execute` 前再次检查 `access.allowed`，无权时不发送请求。
- `view-only` 测试覆盖 review、confirm、manage、rollback、export、reconcile和run权限，不再因具备view权限展示写动作。

动作与后端权限码核验：

| 模块 | 动作 | 前端权限码 | 后端证据 | 结果 |
|---|---|---|---|---|
| replenishment | 接受/拒绝建议 | `replenishment.review` | permission catalog、service检查 | 通过 |
| lifecycle | 确认/拒绝建议 | `products.lifecycle.confirm` | permission catalog、service检查 | 通过 |
| alerts | 处理/关闭预警 | `alerts.manage` | permission catalog、permission/service检查 | 通过 |
| config | 提交审批流程 | `config.manage` | permission catalog、service检查 | 通过 |
| config | 回滚 | `config.rollback` | permission catalog、service检查 | 通过 |
| reports | 申请导出 | `reports.export` | permission catalog、export service检查 | 通过 |
| finance | Mock对账、确认、拒绝 | `finance.reconcile` | API permission、permission catalog | 通过 |
| product status | 确认/拒绝建议 | `products.status.confirm` | permission catalog、service检查 | 通过 |
| integrations | run-mock | `integrations.run` | API permission、permission catalog | 通过 |
| integrations | disable | `integrations.manage` | API permission、permission catalog | 通过 |

页面字段仍只消费后端返回的数据和脱敏结果，未发现新增依靠CSS隐藏敏感字段的实现。tenant、data_scope和action permission继续由后端执行最终校验。

## 6. 测试与构建结果

本次复审实际执行：

| 检查 | 结果 | 实际证据 |
|---|---|---|
| UI-P1专项测试 | PASS | 1 file，28 passed |
| 前端全量Vitest | PASS | 3 files，61 passed |
| 前端生产构建 | PASS | Vite 6.4.3，1873 modules transformed |
| 全路由静态扫描 | PASS | 65条非公开路由，48条规则，缺失0 |
| 直接URL权限矩阵 | PASS | finance view/import、basic internal、external、rpa结果符合合同 |
| 动作权限静态扫描 | PASS | 所有共享页面`handler/execute`动作均声明对应后端权限码 |
| 通用动作防护扫描 | PASS | 可见性过滤与点击前二次拒绝均存在 |
| `git diff --check` | PASS | 退出码0；仅有LF/CRLF提示 |
| Pilot认证态浏览器E2E | 本轮未执行 | R1已执行；本次为代码级定向R2，且工作树尚未部署 |
| 远端CI | 未执行 | 当前整改尚未提交、未创建PR |

构建继续出现第三方 `@vueuse/core` PURE注释位置提示，Rollup移除该注释后构建成功，不阻断本次复审。

## 7. 安全扫描

结论：**通过**。

- 未发现高置信私钥、OpenAI样式密钥或AWS访问密钥模式。
- 跟踪的环境文件仅为根目录、frontend和rpa-agent的 `.env.example`，未发现真实 `.env`。
- 未发现前端访问 `/admin/` 或RPA Agent claim、heartbeat、logs、screenshots、complete、fail执行接口。
- 未发现真实平台连接、真实银行或支付接入、真实凭据或真实业务数据。
- `frontend/dist`、`frontend/node_modules` 和npm缓存未进入Git状态。
- 本轮未启用自动采购、自动清仓、自动改价、真实RPA或资金操作。

## 8. P0

无。

## 9. P1

无。R1两项P1均已关闭。

## 10. P2

1. 商品编码冻结当前后端合同仅使用 `IsInternalUser`，没有独立action permission；本次前端按现有后端合同控制。UI-P2细化基础档案权限时建议新增专用权限码和测试。
2. 当前动作测试覆盖权限工具、源码合同和防护分支，尚未增加组件挂载或浏览器级“按钮不可见且请求未发出”测试。
3. 当前整改尚未形成提交和PR，远端CI、Pilot部署回归需在提交后执行。
4. 继承R1的refresh token存储、服务端撤销、404/empty语义和能力级connected证据等P2观察项仍未变化。
5. Vite第三方PURE注释提示继续保留为构建观察项。

## 11. 是否允许UI-P1正式收尾

**允许。**

架构复审层面两项阻断P1已经关闭，UI-P1结论提升为PASS。正式合并前仍须将当前工作树形成可审计提交，确认PR文件范围，并通过远端CI；该工程动作不改变本次架构PASS结论。

## 12. 是否允许进入UI-P2

**允许进入准备，正式开发应基于UI-P1合并后的最新main。**

UI-P2可以开展组织用户、角色、权限和基础档案设计；不得基于当前未提交工作树或未合并feature分支另行发散。真实平台接入、高风险自动化和资金操作仍不在UI-P2默认权限范围内。
