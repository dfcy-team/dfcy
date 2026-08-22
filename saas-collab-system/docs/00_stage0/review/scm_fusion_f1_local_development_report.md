# SCM-FUSION-F1 本机阶段开发报告

> 状态：`LOCAL_DEVELOPMENT_COMPLETE — READY_FOR_CODE_REVIEW`
> 日期：2026-07-25
> 分支：`codex/scm-f1-local`
> Git 基线：`446bf221106df334b7a8e91ca93a0be026895f28`
> 执行主机：架构员主机
> 生产影响：无

## 1. 本轮结论

SC-F1 首批供应链纵向切片已经在本机完成：

- 新版采购单头/明细模型。
- 供应商主档和 SKU 主数据引用。
- 接单、开始生产、更新进度、生产完成状态机。
- 内部管理端 API 和 Vue 工作台。
- 供应商网页端 API。
- 原生微信小程序供应商页面和 API。
- 租户、DataScope、供应商和 Token Channel 隔离。
- 创建与动作幂等。
- 业务事件和操作日志。
- MySQL 8 迁移、回退/再升级演练。
- 本地虚构数据生成器。

本轮没有连接或修改线上供应链系统、生产 Supabase、真实微信平台或任何真实通知渠道。

## 2. 实际范围

### 已完成

| 能力 | 实现 |
|---|---|
| 新版采购单 | `SupplyPurchaseOrder`，与旧 `PurchaseOrder` 并存 |
| 采购明细 | `SupplyPurchaseOrderLine`，关系型头/明细 |
| 生产进度 | `SupplyProductionProgress` |
| 幂等事件 | `SupplyPurchaseOrderEvent` |
| 供应商映射 | 复用 `masterdata.SupplierMaster` |
| SKU 映射 | 复用 `products.ProductSKU` |
| 内部权限 | 六项 `supply.*` 权限 + DataScope |
| 内部端 | Vue“供应链采购协同”本地工作台 |
| 供应商网页端 | 供应商专属查询和动作 API |
| 小程序 | 采购单列表、详情、接单和生产进度 |
| 本地数据 | `seed_supply_chain_local` 幂等生成器 |

### 仍未纳入

- Supabase 生产数据抽取或迁移。
- React/Taro 运行时合并。
- 装箱、标签、货柜、装柜和发运。
- 文件/图片/视频迁移。
- 报关、成本、结算和财务报表。
- 微信真实登录配置和真实外部通知。
- 生产双写、增量同步、切流或停机窗口。
- 微信小程序上传、审核或发布。

## 3. 架构实现

```text
Vue 内部端 ────────────────┐
供应商网页端 ──────────────┼─> Django/DRF ─> MySQL 8
原生微信小程序 ────────────┘        │
                                     ├─ 权限/DataScope
                                     ├─ 状态机/事务/幂等
                                     └─ OperationLog
```

源 React/Taro/Supabase 没有成为目标运行时依赖。

## 4. 数据与兼容策略

- 保留旧 `purchasing.PurchaseOrder`，没有修改旧字段、状态或 URL。
- 新采购单单头和明细采用独立表。
- 所有新记录显式绑定租户。
- 供应商和 SKU 必须与采购单属于同一租户。
- MySQL 主键保持 BigAutoField。
- 源 Supabase UUID 仅作为 `source_*` 追踪字段。
- `tenant + source_system + source_table + source_record_id` 唯一。
- 创建幂等键按租户唯一，并保存规范化请求哈希。
- 接单后采购明细不可修改或删除。

## 5. API 与安全

API 合同见 `docs/03_api/supply_chain_f1_api.md`。

已验证：

- 内部端要求内部用户、权限和 DataScope。
- 供应商只能访问绑定供应商的采购单。
- 跨租户和跨供应商详情返回 `404`。
- 小程序专用 Token 不能调用内部端或供应商网页端 API。
- 普通 JWT 不能调用小程序 API。
- 供应商和小程序响应不包含单价、源哈希、进度请求 ID或操作者 ID。
- 客户端没有 Supabase/MySQL 直连代码。
- 没有 Service Role、微信 Secret 或真实凭据。

## 6. 状态与事务

本轮开放：

```text
pending → accepted → in_production → production_completed
```

每个动作：

- 使用 `transaction.atomic()`。
- 对采购单执行 `select_for_update()`。
- 校验当前状态。
- 校验租户和供应商范围。
- 要求 `Idempotency-Key`。
- 单调校验生产进度。
- 写入不可重复的领域事件。
- 写入操作审计。

模型普通保存和 QuerySet `update` 不能直接修改状态。

## 7. 本地 MySQL 证据

本机 MySQL：

- Docker MySQL 8 健康。
- 端口只绑定 `127.0.0.1:3306`。
- 开发数据库：`scm_f1_local_dev`。
- 迁移测试数据库：`scm_f1_migration_test`。

已应用：

- `purchasing.0002_supplypurchaseorder_supplyproductionprogress_and_more`
- `purchasing.0003_supplypurchaseorder_creation_idempotency_key_and_more`
- `permissions.0016_seed_supply_chain_f1_permissions`

迁移演练：

```text
purchasing 0003
  → 回退到 purchasing 0001
  → 重新升级到 purchasing 0003
  → 全部成功
```

`seed_supply_chain_local` 连续运行两次：

- 第一次创建虚构租户、供应商、SKU、用户和采购单。
- 第二次复用同一批数据，没有重复记录。
- 示例用户密码不可用。

MySQL API 烟测：

```text
GET /api/internal/purchasing/supply-orders/
HTTP 200
count=1
database=scm_f1_local_dev
```

## 8. 验证结果

| 验证 | 结果 |
|---|---|
| Django system check | 通过，0 issues |
| Django migration drift | 通过，No changes detected |
| SC-F1 + 旧采购 + 小程序认证定向回归 | 26 passed |
| 后端完整回归 | 424 passed |
| 管理端 SC-F1 测试 | 4 passed |
| 管理端完整 Mock 回归 | 163 passed |
| Vue 生产构建 | 通过 |
| 小程序完整测试 | 25 passed |
| 小程序项目校验 | 通过，8 pages / 28 JavaScript files |
| MySQL 8 正向迁移 | 通过 |
| MySQL 8 回退/再升级 | 通过 |
| MySQL API 读取烟测 | HTTP 200 |
| `git diff --check` | 通过；仅有仓库既有 CRLF 提示 |

管理端第一次完整回归在当前本机 `VITE_USE_MOCK=false` 环境下出现一项既有 UI-P4 测试前提不匹配：用例要求 Mock 写入禁用结果，但实际调用了未认证 API。显式设置该用例要求的 `VITE_USE_MOCK=true` 后，完整 163 项全部通过；未修改无关 UI-P4 代码。

## 9. 本机运行

### Django/MySQL

确保本机 `.env` 指向本地 Docker MySQL，然后：

```powershell
cd backend
python manage.py migrate
python manage.py seed_supply_chain_local
python manage.py runserver
```

禁止把生产 Supabase、真实微信或真实用户凭据写入本机开发配置。

### Vue

```powershell
cd frontend
$env:VITE_USE_MOCK="true"
npm run dev
```

入口：

```text
/supply-chain/purchase-orders
```

### 原生小程序

小程序开发环境默认 `useMock=true`，入口位于首页“进入供应链采购协同”。

## 10. 工作树说明

进入本轮开发前，仓库已存在未提交的小程序认证、发布模块和文档改动。为保护用户在途工作：

- 没有 reset、stash、删除或覆盖这些改动。
- 已创建独立分支 `codex/scm-f1-local`。
- 本轮只按供应链范围修改/新增文件。
- 尚未暂存或提交任何文件。

代码审核时必须按 SC-F1 文件清单审阅，不能把当前工作树其他在途改动自动视为本轮供应链交付。

## 11. 下一审核建议

建议结论：`READY_FOR_LOCAL_CODE_REVIEW`

下一次审核重点：

1. 采购单头/明细模型及与旧模型的兼容性。
2. 创建和动作幂等。
3. 租户、DataScope、供应商及 Token Channel 隔离。
4. 供应商字段最小化。
5. MySQL 迁移与回退证据。
6. Vue/小程序本机交互。

本报告不构成测试环境、预览环境或生产环境发布授权。
