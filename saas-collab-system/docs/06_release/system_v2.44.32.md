# SaaS 协同系统 V2.44.32 发布登记

- 登记日期：2026-08-17
- 父版本 / 当前虚拟机基线：V2.44.31
- 发布状态：`deployed`
- 数据库迁移：需要（仅 `permissions.0030_seed_sales_management_permissions`）
- 目标：`192.168.174.131:8443`
- 回退版本：V2.44.31

## 授权范围

本版本只在 V2.44.31 菜单基础上新增开发 A 的“销售管理”前端模块壳：

1. 在“经营决策”与“达人管理”之间新增一级菜单“销售管理”。
2. 新增销售总览、销售订单、退款退货、门店销售、SKU 销售、销售明细导出、数据同步与质量 7 个页面节点。
3. 新增 8 个 `sales_management.*` 权限码，并只自动授予现有启用的 administrator 角色；其他角色不自动扩权。
4. 页面当前为待接入的前端占位功能壳，不包含销售业务后端模型、接口或真实销售数据。

除 `frontend/src/router/menu.js`、`frontend/src/router/index.js`、7 个销售页面、权限目录和 0030 迁移外，不允许其他业务源码进入本版本增量。

## 菜单节点门禁

| 项目 | V2.44.31 | V2.44.32 | 差异 |
| --- | ---: | ---: | ---: |
| 一级菜单 | 15 | 16 | +1 |
| 总菜单节点 | 105 | 113 | +8 |
| 路由权限声明 | 103 | 110 | +7 |

一级菜单顺序固定为：工作台、产品开发、全球刊登、经营分析、经营决策、**销售管理**、达人管理、流程协同、业务协同、RPA 协同、API 数据接入、财务中心、报表中心、基础档案、系统治理、治理与试点。

| 保护文件 | V2.44.31 SHA256 | V2.44.32 SHA256 | 结论 |
| --- | --- | --- | --- |
| `frontend/src/router/menu.js` | `0dd6ecd67bd874bc97322f5e7d3d4cdbbbb3f71e4897724d69ad07d09f0b611a` | `a627102d58d29eb5db7cea5d92d82000137193efb25ba5396ad470769a872071` | 仅销售节点增量 |
| `frontend/src/router/index.js` | `96edff0b40945180d2e4f3fda19ca47a7aa12de61512c497fb45ea24cbf9a98d` | `a4fd1fd8ac188be19479d702b7673a7a8968881a00b2f227f606f605ca1d6aee` | 仅 7 条销售路由增量 |
| `frontend/src/layouts/MainLayout.vue` | `63c2092d2fa1265608cc29ba4ae0fa28245bedc822c081bcc982cad56b135619` | `63c2092d2fa1265608cc29ba4ae0fa28245bedc822c081bcc982cad56b135619` | 未变更 |

## 权限与迁移

- `sales_management.view`
- `sales_management.orders.view`
- `sales_management.returns.view`
- `sales_management.stores.view`
- `sales_management.skus.view`
- `sales_management.export`
- `sales_management.data_quality.view`
- `sales_management.sync.view`

迁移 `permissions.0030_seed_sales_management_permissions` SHA256：`e32c5f3b73d8c1504f5b32598895c222f32337560eae9198c55423c80ace14c7`，依赖 `permissions.0029_sync_development_product_archive_permission_metadata`。

角色权限页继续按完整权限分页、菜单节点与路由能力生成权限树；上线后必须核验销售管理 7 个节点及 8 个权限码可选。

## 构建与发布前验证

- 显式生产构建：`VITE_USE_MOCK=false`、`VITE_API_BASE_URL=''`。
- 前端销售路由/菜单测试：3 项通过。
- 后端权限目录及销售权限测试：5 项通过。
- `manage.py check`：通过。
- `makemigrations --check --dry-run`：`No changes detected`。
- Vite production build：通过。
- 构建 `index.html` SHA256：`2d1ada97e2a921e6f5a565957cf3ffeea748c7c800f8fd1a0328c359bf0f1575`。
- 入口 `index-C_Tr7WJt.js` SHA256：`09f9c8e536c117c27ec857625f08eb121c7aef3dea9332b1ad278d0da237f283`。

## 发布门禁

1. 发布前确认虚拟机仍运行 V2.44.31，并备份数据库。
2. 后端镜像只允许基于 V2.44.31 覆盖权限目录和 0030 迁移。
3. 先执行并核验 0030，再只切换 backend/frontend；Celery、Beat、Redis 不得重启。
4. 发布后检查 16/113/110 节点计数、一级顺序、7 个销售路径、8 个权限记录、administrator 授权和角色权限页面。
5. 任一菜单非授权变化、哈希不符或服务异常时回退到 V2.44.31。

## 部署与上线后审查结果

- 部署完成时间：2026-08-17 15:11（Asia/Shanghai）。
- 数据库备份：`pre-migration-v2.44.32.sql.gz`，SHA256 `c130c93ced1aaa6d441ec9e35ce4e7f8183f3a714a9585cd8a5ea3221c858f98`；gzip 完整性通过。
- 已应用 `permissions.0030_seed_sales_management_permissions`。
- 后端镜像：`saas-collab-backend:v2.44.32`，ID `sha256:b0d1063da500aa90b23ef8305587beb1ac007b155d1b4b5e9d936c4e0626f952`。
- 前端镜像：`saas-collab-frontend:v2.44.32`，ID `sha256:f4ca9d00f3668408547a3503fb2a9a51a02651e6c290d0507e0dd4f2303eb922`。
- 仅切换 backend/frontend；Celery、Beat、Redis 容器 ID 与 V2.44.31 完全一致。
- 运行时 `manage.py check`、`nginx -t`、健康接口均通过。
- 7 个销售管理路径、根页面和角色权限页面均返回 200。
- 运行时 `index.html` 与入口 JS 哈希和登记完全一致。
- 8 条销售权限均存在，两条启用 administrator 角色均获得全部 8 条权限；普通角色未自动扩权。
- 菜单审查仍为 16 个一级分组、113 个总节点、110 条路由能力；除在“经营决策”与“达人管理”之间新增“销售管理”及其 7 个子节点外，原节点顺序未变。
- 角色权限树继续从完整权限分页、菜单节点与路由能力动态生成；销售管理节点的精确权限过滤与其他操作权限归组测试通过。
- 回退资产继续保留 V2.44.31 前后端镜像和 `/home/dfcy01/releases/system-v2.44.31-build-20260815`。
