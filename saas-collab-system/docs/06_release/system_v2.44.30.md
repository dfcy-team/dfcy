# SaaS 协同系统 V2.44.30 发布登记

- 登记日期：2026-08-15
- 父版本：V2.44.29
- 发布状态：已部署
- 部署时间：2026-08-15 18:17（Asia/Shanghai）
- 数据库迁移：需要
- 回退版本：V2.44.29

## 本次授权范围

本版本只在现有“产品开发”模块新增“开发产品档案”功能：

1. 增加开发产品档案列表、创建、编辑、试销确认和转正式商品流程。
2. 增加产品档案类目归属、平台、站点、虚拟库存和流程事件记录。
3. 增加查看、维护、确认三个权限码，并兼容现有开发项目权限。
4. 在“产品开发”下新增唯一菜单入口“开发产品档案”。

不修改其他一级菜单、其他子菜单、主导航样式、商品明细、平台商品明细或角色权限页面。

## 菜单复核

- V2.44.29 菜单 SHA256：`c4919748b05f596ede323f0dfc86e7d58bcae40abb366b952ffb00889a4b3ab9`
- V2.44.30 菜单 SHA256：`0dd6ecd67bd874bc97322f5e7d3d4cdbbbb3f71e4897724d69ad07d09f0b611a`
- V2.44.29 路由 SHA256：`10d9e134611817f433e7553d86c802b6ed0473321f32ab911cc5ed536c0369f6`
- V2.44.30 路由 SHA256：`96edff0b40945180d2e4f3fda19ca47a7aa12de61512c497fb45ea24cbf9a98d`
- 一级菜单仍为 15 个，名称和顺序完全不变。
- 菜单节点由 104 增至 105；路由权限声明由 102 增至 103。
- 将本次新增的父权限、子菜单和路由权限三处内容从源码中移除后，菜单和路由哈希均精确还原为 V2.44.29。
- `MainLayout.vue` SHA256 仍为 `63c2092d2fa1265608cc29ba4ae0fa28245bedc822c081bcc982cad56b135619`。

## 数据库迁移

- `development.0002_product_sales_summary_view`（线上此前未登记执行；补充 `atomic = False` 以兼容 MySQL DDL）
- `development.0004_development_product_archives`
- `permissions.0028_seed_development_product_archive_permissions`

迁移为增量新增：先创建既有产品销售汇总视图，再给开发项目增加类目引用，新增开发产品档案及事件表，并登记三个权限码。发布前首次预演已拦截 0002 在 MySQL 原子迁移中的 DDL 限制；修正为非原子、幂等执行后才能继续。旧版应用可忽略新增视图、表、字段和权限，因此应用回退到 V2.44.29 时仍保持兼容。

## 发布前验证

- 开发产品档案后端专项测试：8 项通过。
- 开发产品档案前端专项测试：5 项通过。
- Django `manage.py check`：通过。
- `makemigrations --check --dry-run`：无遗漏迁移。
- Vite 非 Mock 生产构建：通过，参数为 `VITE_USE_MOCK=false`、`VITE_API_BASE_URL=''`。
- 前端入口：`index-B7iTp8hS.js`。
- 开发产品档案资源：`DevelopmentProductArchiveList-Cm1CqhOV.js`。

## 部署要求

1. 部署前核对线上仍为 V2.44.29，并保留 V2.44.29 镜像和 Compose 回退配置。
2. 先检查迁移计划，再执行两项增量迁移。
3. 仅更新 backend 和 frontend；不得重启 celery、beat、redis。
4. 部署后复核迁移状态、Django/Nginx、HTTPS 页面、受保护 API、运行资产哈希和全部 15 个一级菜单。

## 部署结果

- 目标：`https://192.168.174.131:8443`
- 审计目录：`/home/dfcy01/releases/system-v2.44.30-build-20260815`
- 部署前数据库备份：`pre-migration-v2.44.30.sql.gz`
- 备份 SHA256：`20f947aed20a7677154f34b86b72100f2a9c83dd4fd46ff5b92c1155d429e080`
- 后端镜像：`saas-collab-backend:v2.44.30`，ID `sha256:57a785208d1c108e0f974e67c65c3a7c57491bae1a33fa1f935afb92598dc000`
- 前端镜像：`saas-collab-frontend:v2.44.30`，ID `sha256:450f0340fe5577fe5f11f566d664a3dc57b414c926572b07d05637b8827c4f01`
- 只执行了 backend/frontend 切换；celery、beat、redis 容器 ID 均未变化。

迁移执行结果：

- `development.0002_product_sales_summary_view`：生产数据库账号没有 `CREATE VIEW` 权限，因此只做 fake 登记；该视图在 V2.44.29 原本也不存在，本次档案功能不依赖它。
- `development.0004_development_product_archives`：成功应用。
- `permissions.0028_seed_development_product_archive_permissions`：成功应用，运行态确认三个权限码均存在。
- 无关的 `purchasing.0005_shipping_route`：未执行。

发布后复核：

- Django `manage.py check` 与 Nginx `nginx -t` 均通过。
- `/`、`/development/projects/archives`、`/products/master`、`/products/details`、`/products/platform-details`、`/system/roles` 均返回 200。
- `/api/internal/health/` 返回 200；未认证档案 API 返回 403，确认路由存在且不是 404。
- 线上入口、档案 JS/CSS 哈希均与登记完全一致。
- 15 个一级菜单全部存在，名称与顺序保持；仅新增“产品开发 → 开发产品档案”。
- V2.44.29 镜像、Compose 配置及数据库备份均保留，可执行应用回退。
