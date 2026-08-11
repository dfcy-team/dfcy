# SC-F1 第三轮/最终本地融合审核归档

> 审核结论：`PASS_LOCAL_FINAL`
>
> 审核日期：2026-07-25
>
> 执行环境：架构员主机、本地隔离开发环境
>
> 生产影响：无

## 1. 审核目的

本次审核是供应链业务功能融合 `SC-F1` 的第三轮及最终本地审核，用于确认：

1. 第一、第二轮审核问题已经全部关闭。
2. 供应链采购协同纵向切片满足既定业务、架构、安全和数据边界。
3. 固定提交可以在本地 MySQL、SQLite、Vue 管理端和原生微信小程序中复现。
4. 本地阶段没有连接、查询或修改正式供应链系统。
5. `SC-F1` 没有越权实施装箱、物流、报关、结算等后续波次。

本审核只关闭本地开发和本地融合审核阶段，不构成测试环境、预览环境或生产环境发布授权。

## 2. 固定审核基线

| 项目 | 固定值 |
|---|---|
| 分支 | `codex/scm-f1-local` |
| 最终提交 | `813bd4bd63729c4ccd8c05f60c88e31174bcd408` |
| Tree | `17a0e4e292c30390d34d867da3a1e8587ba35922` |
| 父提交 | `7a2053625bb8bc7a21a2751174d3a7a9a6a86d88` |
| 逻辑比较范围 | `8e03ebd..813bd4b` |
| 审核文件数 | 47 |
| 代码增减 | 5721 行新增、1 行删除 |

逻辑比较基线选用发布模块提交 `8e03ebd`，以便将供应链实现、权限迁移合并和第二轮整改完整纳入同一审核范围，同时排除此前的小程序认证基础和发布模块自身实现。

本次供应链审核提交链：

| 提交 | 内容 |
|---|---|
| `89392bb` | SC-F1 本地供应采购协同实现 |
| `7a20536` | 发布与供应链权限迁移分支合并节点 |
| `813bd4b` | SC-F1 第二轮审核 P1/P2 整改 |

## 3. 最终业务范围

### 3.1 已纳入

- 复用 `SupplierMaster` 供应商主档。
- 复用 `ProductSKU` 商品 SKU。
- 新增 `SupplyPurchaseOrder` 采购单头。
- 新增 `SupplyPurchaseOrderLine` 采购明细。
- 新增 `SupplyProductionProgress` 生产进度记录。
- 新增 `SupplyPurchaseOrderEvent` 幂等业务事件。
- 内部端采购单查询、详情和创建。
- 供应商网页端查询、详情和业务动作。
- 原生微信小程序供应商端查询、详情和业务动作。
- 接单、开始生产、更新生产进度和标记生产完成。
- 租户、角色、权限、DataScope、供应商和 Token Channel 隔离。
- 创建与业务动作幂等、事务、行锁、审计日志和响应快照。
- 本地 MySQL migration、虚构数据种子和自动化测试。
- Vue 管理端多明细采购单录入。

### 3.2 明确排除

- React/Taro/Supabase 运行时合并。
- 生产 Supabase 或正式供应链系统连接。
- 真实生产数据抽取、迁移、同步、双写或切流。
- 真实用户密码、Token、OpenID、会话或业务文件迁移。
- 装箱方案、箱规、箱明细和货柜管理。
- 发货、物流、报关、成本、结算和财务报表。
- 真实微信登录配置、真实通知和小程序发布。
- 未经独立审核的 F2-F5 工作包。

模型中保留的 `ready_to_ship`、`shipping_review_pending`、`shipping` 和 `shipped` 仅用于源状态语义兼容，`SC-F1` 没有开放这些状态的转换服务、API 或界面动作。

## 4. 架构与兼容性审核

审核确认：

- 旧 `purchasing.PurchaseOrder` 模型、字段、状态和 URL 保持不变。
- 新采购单采用独立单头/明细聚合，不覆盖旧模型。
- MySQL 主键继续使用 `BigAutoField`。
- 源 UUID 仅作为 `source_*` 追踪信息，不替换目标主键。
- `tenant + source_system + source_table + source_record_id` 具有唯一约束。
- 采购单号和创建幂等键均按租户唯一。
- 供应商、SKU、创建人、采购单、进度和事件均校验租户一致性。
- 客户端只访问 Django/DRF API，不直连 Supabase 或 MySQL。

最终目标架构保持为：

```text
Vue 内部端 ───────────────┐
供应商网页端 ─────────────┼─> Django/DRF ─> MySQL 8
原生微信小程序 ───────────┘       ├─ 权限/DataScope
                                  ├─ 状态机/事务/幂等
                                  └─ OperationLog
```

## 5. 安全与隔离审核

审核确认：

- 内部用户必须同时满足用户类型、权限代码和 DataScope。
- 所有内部列表、详情和动作先按当前租户过滤。
- 供应商用户只能访问绑定供应商的采购单。
- 外部档案租户必须与用户租户一致。
- 绑定的 `SupplierMaster` 必须属于当前租户且状态为 `active`。
- 停用供应商不能创建关联采购单、查询采购单或执行业务动作。
- 跨租户和跨供应商资源统一按未授权范围拒绝。
- 小程序 Token 不能调用内部端或供应商网页端 API。
- 普通 JWT 不能调用小程序专用 API。
- 供应商响应不暴露单价、源哈希、内部操作者 ID、请求 ID等内部字段。
- 未发现 Service Role、微信 Secret、生产端点或真实凭据。

## 6. 状态、事务、幂等和审计审核

`SC-F1` 开放状态机：

```text
pending
  → accepted
  → in_production
  → production_completed
```

审核确认每项业务动作均：

- 在 `transaction.atomic()` 中执行。
- 使用 `select_for_update()` 锁定采购单。
- 校验当前状态、租户和供应商范围。
- 要求合法的 `Idempotency-Key`。
- 保存请求哈希和原始响应快照。
- 同键同载荷重试返回原结果。
- 同键不同动作、操作者或载荷返回冲突。
- 生产进度只能单调增加且不能超过采购总量。
- 生产完成要求完成数量等于采购总量。
- 写入不可重复的领域事件和操作审计。

模型层同时阻止：

- 普通模型保存绕过受控状态字段。
- QuerySet `update` 或 `bulk_update` 绕过状态服务。
- 接单后新增、修改或删除采购明细。
- 更新或删除追加写的事件和进度记录。
- 删除采购单审计记录。

## 7. 前端和小程序审核

### 7.1 Vue 管理端

- 页面明确展示“仅用于架构员主机”的本地边界。
- 支持服务端分页、筛选、详情和状态动作。
- 新建采购单支持多条明细新增、删除、逐行校验和自动行号。
- Mock 状态机拒绝越级动作、进度回退、超量和未满产完成。
- Mock 行为与后端动作合同保持一致。

### 7.2 原生微信小程序

- 仅使用 `/api/miniapp/supply-chain/*` 专用 API。
- 开发环境默认 Mock，生产配置禁止 Mock。
- 供应商字段保持最小化。
- 支持采购单分页、详情、接单、开始生产、更新进度和生产完成。
- 项目校验通过：8 个页面、28 个 JavaScript 文件。

## 8. 数据库与迁移审核

本地 MySQL：

- 开发库：`scm_f1_local_dev`
- 专用迁移测试库：`scm_f1_migration_test`
- 主机：`127.0.0.1`

已审核迁移：

- `purchasing.0002_supplypurchaseorder_supplyproductionprogress_and_more`
- `purchasing.0003_supplypurchaseorder_creation_idempotency_key_and_more`
- `purchasing.0004_supplypurchaseorderevent_idempotency_snapshot`
- `permissions.0016_seed_supply_chain_f1_permissions`
- `permissions.0017_merge_release_and_supply_permissions`

最终迁移演练：

```text
purchasing 0004
  → 回退到 purchasing 0001
  → 再升级到 purchasing 0004
  → migrate 全部应用
```

全部步骤成功，Django 未检测到 migration drift。

`seed_supply_chain_local` 在专用迁移测试库连续执行两次：

- 第一次创建虚构租户、供应商、SKU、用户和采购单。
- 第二次复用同一批数据。
- 租户、供应商、SKU 和采购单均保持 1 条。
- 示例用户使用不可用密码。
- 内部采购单列表 API 烟测返回 HTTP 200，`count=1`。

该虚构数据只保留在本地 `scm_f1_migration_test`，不涉及正式系统。

## 9. 最终验证结果

| 验证项 | 结果 |
|---|---|
| Django system check | 通过，0 issues |
| Django migration drift | 通过，No changes detected |
| 后端完整 SQLite 回归 | 427 passed，3 个 MySQL-only skipped |
| 本地 MySQL API、并发和 ORM 防绕过 | 14 passed |
| 前端 SC-F1 定向测试 | 7 passed |
| 前端完整 Mock 回归 | 166 passed |
| Vue 生产构建 | 通过 |
| 小程序完整测试 | 26 passed |
| 小程序项目校验 | 通过，8 pages / 28 JavaScript files |
| MySQL 正向迁移 | 通过 |
| MySQL 回退/再升级 | 通过 |
| 本地种子幂等 | 通过 |
| 本地 MySQL API 烟测 | HTTP 200 |
| 固定范围差异检查 | 通过 |

## 10. 历史问题关闭

### 第一轮 P1

- 接单后明细不可变及 ORM 绕过防护：已关闭。
- 事件和进度追加写保护：已关闭。
- MySQL 并发创建幂等：已关闭。
- MySQL 并发动作和原响应重放：已关闭。
- 权限迁移分支合并：已关闭。
- Vue 和小程序分页：已关闭。

### 第二轮 P1/P2

- 停用供应商及外部档案租户边界：已关闭。
- SC-F1 API 测试权限夹具自足：已关闭。
- Vue Mock 严格状态机：已关闭。
- 网页端多明细录入：已关闭。

最终问题统计：

| 等级 | 数量 |
|---|---|
| P0 | 0 |
| P1 | 0 |
| P2 | 0 |

## 11. 工作区和正式系统影响

- SC-F1 固定代码基线与 HEAD 一致。
- 审核时暂存区为空。
- 工作区中已有的试点部署文档和其他未跟踪资料不属于 SC-F1 基线。
- 未连接、查询或修改生产 Supabase。
- 未连接、查询或修改正式供应链系统。
- 未导入真实生产数据。
- 未发送真实微信、短信、邮件或其他外部通知。
- 未上传、审核或发布微信小程序。
- 未推送远端分支。

## 12. 最终审核结论

结论：`PASS_LOCAL_FINAL`

`SC-F1` 满足本地业务功能融合、架构兼容、权限隔离、事务幂等、审计、MySQL 迁移、Vue 管理端和原生微信小程序的既定验收门禁。

同意关闭：

- SC-F1 本机开发阶段。
- SC-F1 本地代码审核阶段。
- SC-F1 本地融合审核阶段。

本结论不授权：

- F2-F5 后续功能开发。
- 测试环境或预览环境部署。
- 真实数据迁移、同步、双写或切流。
- 微信小程序上传、审核或发布。
- 正式供应链系统变更。
- 生产上线。

任何后续阶段必须建立新的固定基线、审核范围、环境授权和验收门禁。
