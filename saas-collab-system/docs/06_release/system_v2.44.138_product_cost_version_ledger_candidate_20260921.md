# V2.44.138 商品成本版本台账候选登记

## 登记结论

- 版本：`V2.44.138`
- 登记日期：`2026-09-21`
- 主题：基础档案新增“商品成本”菜单，支持商品成本人工维护、系统生成回填预览、差异核对和历史版本展示。
- 状态：`READY_FOR_REVIEW`；标准 XLSX 关系路径和 Excel 日期序列解析阻断已修复，已通过真实 openpyxl 工作簿预检与确认入账回归，未部署。
- 直接父基线：`V2.44.137` / `v2.44.137-deployed` / `c228080fa6982a9971c7de06ea0d47fa5312d0f5`。
- 版本占用复核：`V2.44.137` 已完成生产部署并占用不可变标签 `v2.44.137-deployed`，因此本次顺延登记 `V2.44.138`。
- 发布边界：本记录不创建 deployed 标签、不合并主线、不触发虚拟机或生产部署。

## 候选目标

在“基础档案”下新增独立的“商品成本”入口，明确区分采购价格与商品成本。商品成本由采购价格、物流分摊、税费、包装费和其他费用组成，系统生成结果须经人工核对后才能成为生效版本。

同一 SKU 在不同时期允许存在不同成本。成本维护采用追加版本方式，不直接覆盖历史记录；页面展示当前版本、历史版本、生效区间、来源及变动情况。

## 时态成本规则

1. 每次人工维护或系统确认均新增成本版本，不原位更新已生效历史版本。
2. 成本版本至少包含 `sku_id`、`version_no`、`confirmed_cost`、`effective_from`、`effective_to`、`source`、`reason`、`created_by` 和审计时间。
3. 同一 SKU 的已生效版本区间不得重叠；当前版本的 `effective_to` 为空。
4. 业务发生时间为 `occurred_at` 时，匹配规则为 `effective_from <= occurred_at < effective_to`；当前版本按无穷结束时间处理。
5. 订单、利润、达人送样及经营报表等下游业务必须保存 `cost_version_id` 和成本金额快照，后续新增版本不得改变已确认的历史业务结果。
6. 系统回填只生成新的待核对版本，不覆盖当前版本或历史版本；人工确认后才接续生效区间。
7. 补录过去日期的成本版本必须执行区间冲突校验，并通过受控审批或更正流程，禁止静默改写历史快照。

## 页面能力

- 菜单位置：`基础档案 -> 商品成本`。
- 路由：`/products/costs`。
- 列表展示：采购价格、附加费用、系统成本、已确认商品成本、差异、来源、核对状态、当前版本及生效日期。
- 人工维护：展示当前生效成本、拟生效成本、变化金额和变化比例；保存动作定义为“新增版本并确认”。
- 历史追溯：展示版本号、商品成本、生效开始、生效结束和来源。
- 系统回填：支持范围及费用口径选择，先生成 dry-run 预览；不得覆盖历史成本。
- 权限边界：独立拆分 `products.cost.view` / `products.cost.manage` / `products.cost.backfill` / `products.cost.approve`。

## 精确增量范围

| 文件 | 候选增量 |
| --- | --- |
| `frontend/src/router/menu.js` | 在基础档案中登记“商品成本”菜单及受保护路由能力 |
| `frontend/src/router/index.js` | 注册 `/products/costs` 页面路由 |
| `frontend/src/views/products/ProductCostLedger.vue` | 商品成本台账、维护变化预览、历史版本和系统回填预览页面 |
| `frontend/src/api/productCosts.js` | 商品成本查询、追加版本及回填预览接口契约 |
| `frontend/tests/product-cost-ledger.spec.js` | 菜单、成本区分、追加版本、变化预览和回填边界合同测试 |
| `backend/apps/products/*cost*` | 成本版本模型、追加服务、时点解析、真实 API 及迁移 |
| `backend/apps/influencers/*` | 送样时固化 `cost_version_id`、单价和金额，并流入归因与报表 |
| `backend/apps/permissions/*` | 四项独立商品成本权限及菜单快照 |

`frontend/src/router/menu.js` 和 `frontend/src/router/index.js` 当前同时包含其他在制修改。形成干净候选时只能提取本登记涉及的商品成本增量，不得整体提交当前混合工作树。

## 当前验证证据

- 定向前端合同测试：10/10 通过（商品成本 + 菜单基线）。
- 前端生产构建：Vite build 通过。
- Playwright 页面身份：`http://127.0.0.1:5173/products/costs`，标题“业务协同工作台”，页面标题“商品成本”。
- Playwright 交互：菜单入口、历史版本弹窗、系统生成回填弹窗及 dry-run 预览均正常。
- 浏览器控制台：无 error、无 warning。
- `git diff --check`：通过，仅有现有 Windows 换行提示。
- 后端聚焦测试：成本版本与送样快照 8/8 通过。
- 达人履约回归：54/54 通过；旧采购价回退断言已按新成本版本口径更新。
- 数据库迁移一致性：`makemigrations --check --dry-run` 无漂移。
- Django system check：0 问题。

## 当前发布门禁

原 `REGISTERED_BLOCKED` 中的实现型阻断已解除。候选仍需通过常规外部门禁：建立单一候选提交/受保护 PR、获得 CI 与发布审批。本文档不将本地测试冒充为 CI，也不声明已部署。

## 形成正式候选的前置条件

1. 从 `v2.44.137-deployed` 创建干净工作树。
2. 设计并评审后端成本版本模型、时态查询规则、并发控制和数据库约束。
3. 实现真实 API，并将前端从演示数据切换到后端数据。
4. 完成下游成本版本快照接入及跨期间回归测试。
5. 验证同一 SKU 多版本、不同时点取值、区间边界、历史补录和并发确认场景。
6. 重新执行完整前后端测试、生产构建、数据库迁移检查和真实浏览器验收。
7. 形成单一审核提交或 PR，通过 CI 和发布审批后方可部署。

## 回滚边界

候选包含数据库迁移，但未在虚拟机或生产执行。正式上线后，历史成本版本和业务成本快照属于审计数据，不允许通过回滚程序删除或覆盖；应用回滚必须保持数据库向后兼容。

## 虚拟机发布通道审核记录

- 审核日期：`2026-09-21`。
- 通道状态：`REGISTERED_BLOCKED`，仅完成候选登记和范围审查，不具备合并或部署条件。
- 当前生产基线已推进为 `V2.44.137` / `v2.44.137-deployed` / `c228080fa6982a9971c7de06ea0d47fa5312d0f5`。上文的 `V2.44.136` 仅保留为候选设计形成时的历史基线；正式候选必须从 `v2.44.137-deployed` 创建干净工作树并重新核对增量。
- 当前源工作树为 `codex/v24459-api-production-readiness`，包含大量其他在制修改和未跟踪文件；商品成本路由与菜单文件也与其他修改混合，禁止整体提交或据此构建发布镜像。
- 已确认的实现边界仅包括菜单、路由、前端页面、前端 API 契约、Mock 演示数据和合同测试；`productCosts.js` 仍包含 Mock fallback，不代表真实接口可用。
- 后端扫描未发现商品成本版本实体、`cost_version_id` 下游快照字段或商品成本真实接口。数据库区间冲突约束、并发追加版本、审核确认、回填执行、时态解析服务和独立权限均未实现。
- 业务规则继续作为强制发布门禁：同一 SKU 多版本；只追加不覆盖；按 `effective_from <= occurred_at < effective_to` 解析；下游固化 `cost_version_id` 和金额快照；系统回填仅生成待核对版本，人工确认后生效。
- 尚无基于当前生产基线的干净候选提交、受保护 PR、完整后端测试、迁移验证或 10 项 CI 证据。后端能力完成前不得移除本阻断。
- 本次审核未触发任何 workflow deploy，未创建 `v2.44.138-deployed` 标签，未修改虚拟机、数据库或发布账本，也不得宣称该功能已上线。

## 阻断处理补记

- 处理日期：`2026-09-21`。
- 干净候选：`codex/v244138-product-cost`，直接基于 `v2.44.137-deployed`。
- 实现结论：已移除 Mock fallback，补齐后端模型/API/迁移/时态解析/独立权限，送样成本已固化版本和金额并进入归因报表。
- 当前结论：候选已进入复审，但复审结论为 `REVIEW_BLOCKED`；在下列缺口修复并复审通过前不创建 `v2.44.138-deployed`、不执行虚拟机部署。

## 候选复审结论（2026-09-21）

- 候选身份核验通过：分支 `codex/v244138-product-cost`，提交 `1b2fb52aa101cabb1cce1b0636b021ac50182643`，与 `v2.44.137-deployed`（`c228080fa6982a9971c7de06ea0d47fa5312d0f5`）的 merge-base 一致，且候选仅领先 1 个提交。
- 已确认真实 API、时点成本解析、送样 `cost_version_id`/金额快照和四项独立权限存在；前端 `productCosts.js` 已无 Mock fallback。
- 阻断 1：当前只实现 `POST /api/internal/products/costs/backfill-preview/`，没有把系统计算结果持久化为 `pending` 成本版本的回填执行服务或接口，未满足“系统回填只生成新的待核对版本”。
- 阻断 2：没有针对既有 `pending` 版本的审核/确认生效接口；现有新增接口可直接创建 `confirmed` 版本，不能替代“待核对版本经人工确认后接续生效”的受控状态流转。
- 阻断 3：同一租户、SKU 的已确认生效区间防重叠仅由 `append_cost_version()` 服务层检查保证；模型迁移只有版本唯一、区间正向和金额非负约束，没有数据库级区间互斥约束，无法防止绕过服务层的重叠写入。
- 验证复跑：后端聚焦测试 `8 passed`；Django system check 0 问题；`makemigrations --check --dry-run` 无漂移；前端合同测试 `10 passed`；`git diff --check` 通过。
- 发布决定：维持登记但阻断部署。补齐上述三项并增加回填执行、人工确认和绕过服务层重叠写入的测试后，方可重新申请候选复审。

## 阻断修复与导入能力补记（2026-09-21）

- 每期导入：新增 CSV/XLSX 两阶段导入，预检返回行级错误、文件摘要和有时效的确认 token；确认阶段要求 `products.cost.backfill` + `products.cost.approve` 双权限。
- 导入安全：确认导入整批原子追加，使用 `Idempotency-Key` + 文件摘要持久化防重；批次内或已有版本的区间冲突均拒绝入账，不覆盖历史金额。
- 回填闭环：新增 backfill execute，将系统计算结果持久化为 `pending` 版本；相同 SKU/时点/成本重放返回 unchanged。
- 确认闭环：新增待核对版本 confirm API，只有 `products.cost.approve` 可将 pending 版本确认生效，并在事务内结束上一个开放区间。
- 数据库约束：PostgreSQL 迁移新增 `btree_gist` 的确认版本时间区间排斥约束，防止绕过服务层写入重叠区间。
- 验证：后端导入/回填/确认/时态快照 14/14 通过；前端商品成本与菜单契约 11/11 通过；Django check、迁移漂移检查、Vite 生产构建和 `git diff --check` 通过。
- 当前结论：上次复审三项实现型阻断已修复，状态回到 `READY_FOR_REVIEW`；仍需重新复审及 PR/CI/发布审批，不视为已部署。

## 第二次候选复审结论（2026-09-21）

- 候选身份核验通过：分支 `codex/v244138-product-cost`，提交 `fcea1bc79939680f750108a730a71d7d7eaeae9b`；直接基于 `1b2fb52`，相对 `v2.44.137-deployed` 共 2 个候选提交。
- 上次三项阻断已在代码中闭环：backfill execute 会新增 `pending` 版本；独立 confirm API 由 `products.cost.approve` 控制；PostgreSQL 迁移通过 `btree_gist` 为 `confirmed` 区间增加排斥约束。
- 新阻断：当前 `_xlsx_rows()` 对工作簿关系目标的路径拼接不兼容标准 XLSX。以 openpyxl 生成的正常工作簿为例，关系目标为 `/xl/worksheets/sheet1.xml`，解析器会错误拼成 `xl/xl/worksheets/sheet1.xml`，最终返回空行并将有效文件误判为空文件；同时解析器未读取单元格样式并转换 Excel 日期序列值，即使修正路径，正常日期单元格仍不能按日期解析。因此“CSV/XLSX 两阶段导入”中的 XLSX 能力尚不可用；现有测试只覆盖了手工构造的文本单元格和非标准关系路径，未捕获这些问题。
- 验证复跑：后端导入/回填/确认/快照 `14 passed`；前端商品成本与菜单合同 `11 passed`；Django system check 0 问题；迁移无漂移；Vite build 通过；`git diff --check` 通过。另行使用 openpyxl 生成标准 XLSX 的解析复现结果为 `[]`。
- 发布决定：登记保持 `REVIEW_BLOCKED`。修复 XLSX 关系路径解析，并增加由真实 XLSX 库生成、含 Excel 日期单元格的 preview/confirm 回归测试后再复审；本次不部署、不创建 `v2.44.138-deployed` 标签。

## XLSX 阻断修复补记（2026-09-21）

- 已正确处理 `/xl/worksheets/...`、`xl/worksheets/...` 和 `worksheets/...` 三种工作表关系目标，不再重复拼接 `xl/`。
- 已读取 `styles.xml` 的内置及自定义日期格式，将 Excel 日期序列转换为 ISO 日期时间后再进入期间校验。
- 新增 openpyxl 生成的标准 XLSX 回归，覆盖真实日期单元格的 preview、confirm 与最终生效期间；导入套件 5/5 通过。
- 当前结论：XLSX 实现型阻断已解除，恢复 `READY_FOR_REVIEW`；仍不代表已通过发布审批或已部署。
