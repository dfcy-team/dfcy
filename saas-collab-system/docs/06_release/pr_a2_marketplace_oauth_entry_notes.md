# PR-A2 Shopee / TikTok Shop OAuth 与门店映射入场记录

## 任务标识

- 任务编号：`A-PR2-MARKETPLACE-OAUTH`（节点 A-04、A-05、A-06）
- 分支：`feature/module-a-marketplace-oauth`（已创建，本地与远端同步）
- 建议 PR 标题：`A-PR2 add Shopee TikTok OAuth and store mapping`
- 风险等级：L3；PR 初始状态 Draft

## 分支基线（2026-08-07 更新：stacked 分支决策）

任务决策更新：前置 PR #37 / #39 暂不合并，PR-A2 采用 stacked PR 方式直接基于 A-PR1 分支开发。

| 项目 | 值 |
|---|---|
| Base branch | `feature/module-a-platform-auth-foundation`（远端与本地一致） |
| Base SHA（实际 `git rev-parse`） | `05308bd64436ab2ddb1ff67936d1ed328253dfde` |
| Base 提交 | `05308bd A-PR1 confirm R2 integration and CI status` |
| Draft PR Base | 保持 `main`；PR 描述必须注明 stacked dependency：PR #37、PR #39 |

与原任务书第 2/3 节的偏差及缓解：

1. 分支未从 `origin/main` 创建（门禁解除前 stacked 开发，属获批偏差）。
2. PR #39 rebase/合并或 main 更新后，本分支必须重新 rebase/merge 最新基线并重跑全量验证，才能转 Ready。
3. 本分支合入 main 的顺序必须晚于 PR #37 与 PR #39。

## 门禁核查（2026-08-07）

| 检查项 | 结果 |
|---|---|
| `origin/main` 最新提交 | `50224f1 Merge pull request #36` |
| PR #37（销售、库存与财务对账基础）已合并 | 否 |
| PR #39（平台授权基础 A-01～A-03）已合并 | 否；分支 `feature/module-a-platform-auth-foundation` 本地 HEAD `05308bd` |
| A2 分支是否已创建 | 是，stacked 于 A-PR1 `05308bd`（2026-08-07 获批决策） |
| 工作区备注 | 存在 3 个未跟踪本地备份：`db.sqlite3.pre-a2-sandbox-v1.bak`、`db.sqlite3.pre-real-marketplace-access.bak`、`db.sqlite3.stale-backup`，不得提交入库 |

结论：正式编码仍受任务书第 2 节约束——不得接入真实平台、真实账号或真实 Token，不得将能力标记为 `connected`；stacked 分支开发为获批偏差，编码与测试只允许 synthetic/mock 引用。

## 门禁期内已完成的允许工作

1. OAuth/callback 合同冻结稿：`docs/03_api/pr_a2_marketplace_oauth_contract.md`（含 OAuthState 模型增量、provider 抽象、Shopee/TikTok callback 字段与错误码矩阵、刷新/撤销合同、门店与商品映射模型、API 与权限矩阵、安全威胁检查表）。
2. 测试用例与 Sandbox 清单：`docs/05_test/pr_a2_marketplace_oauth_test_plan.md`（对应任务书 11.1～11.6 与第 12 节 Sandbox 场景）。
3. A-PR1 兼容性复核：状态机、凭据引用红线、`marketplace_identity_key`、`store_authorization_service` 服务边界与任务书第 4/9 节一致；A2 设计仅扩展不削弱。

上述两份文档为准备稿，正式编码开始时须从最新 `origin/main` 重新核对并在 A2 分支上随首个 docs 提交入库。

## 转 Ready 前必须满足

- [ ] PR #37 独立审核并合并。
- [ ] PR #39 同步最新 `main`，必需 CI、MySQL Sandbox 与安全复审通过后合并。
- [ ] 本分支已 rebase/merge 到 PR #39 合并后的最新 `main`，并重跑全量验证。
- [ ] A-04～A-06 API、安全与数据模型设计通过架构与安全评审（以准备稿为输入）。

## 后续基线同步命令（PR #37/#39 合并后执行）

```powershell
cd C:\Users\Administrator\Desktop\开发\dfcy
git fetch origin --prune --tags
git switch feature/module-a-marketplace-oauth
git merge origin/main   # 或按评审要求 rebase
git log -1 --oneline
git status --short
```

## 停止条件提醒

出现 raw Token/Secret 入库入日志、callback 可重放、state 未绑定上下文、平台门店跨 tenant 绑定、bulk/Admin 绕过状态机、刷新并发覆盖、撤销失败误覆盖引用、映射跨 tenant 泄露、迁移部分写入、未审批连接真实平台、范围扩展到订单/库存/RPA/资金、未同步最新 main 继续开发等情况，立即停止并提交安全/架构复核。
