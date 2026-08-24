# SaaS 协同系统 V2.44.39 发布登记

- 登记日期：2026-08-24
- 父版本：V2.44.38
- 当前虚拟机基线：V2.44.38
- 菜单基线：V2.44.33
- 权限界面基线：V2.44.29
- 发布状态：`deployed_server_verified`
- 目标：`192.168.174.131:8443`

## 本次增量

平台商品明细数据新增“按变体 ID 导入平台商品 ID”能力（接口：`/api/internal/listings/product-details/import-platform-product-ids/`）：

1. 使用当前租户的变体 ID定位记录；租户内同一变体 ID若同时存在于多个平台/店铺，则视为冲突并跳过。
2. 以 `tenant + platform_variant_id` 进行唯一匹配，重复导入更新原记录。
3. `platform_product_id` 允许重复；同一变体只能对应一条平台商品明细。
4. 导入结果返回新增、更新、无变化、跳过和错误明细，页面保留导入过程状态显示。
5. 本次部署脚本不执行真实业务导入；业务数据仍由用户在页面中按租户操作。

## 明确保持不变

- `frontend/src/router/menu.js`：相对 V2.44.38 零修改。
- `frontend/src/router/index.js`：相对 V2.44.38 零修改。
- `frontend/src/layouts/MainLayout.vue`：保留 V2.44.33 深色导航 CSS。
- 权限目录、权限 seed、角色授权和所有既有菜单节点：零修改。
- 平台商品 ID 不新增唯一约束，不执行数据库结构迁移。
- 应用代码仍使用通用 tenant 隔离；部署验收固定检查 `tenant_id=1`，不将租户 1 写死进业务代码。

## 发布产物

- 后端镜像：`saas-collab-backend:v2.44.39`，构建基线 `saas-collab-backend:v2.44.38`。
- 前端镜像：`saas-collab-frontend:v2.44.39`，构建基线 `saas-collab-frontend:v2.44.38`。
- 后端 Dockerfile 只覆盖本次 listings 代码和专项测试；前端 Dockerfile 只覆盖构建后的 `dist`。
- 发布目录：`/home/dfcy01/releases/system-v2.44.39-build-20260824`。
- 部署脚本：`deploy/pilot/releases/system-v2.44.39/deploy-v24439.sh`。

## 数据库与导入边界

- 本次无数据库结构迁移；部署前后执行 `manage.py check`、`makemigrations --check --dry-run` 和 listings 迁移状态检查。
- 发布前备份数据库，部署切换前后核对租户 1 平台商品明细总数、空平台商品 ID 数量和变体重复组数量均保持不变（基线预期分别为 36000、36000、0）。
- 部署脚本禁止调用平台商品明细真实导入接口，避免发布动作改变业务数据。

已对虚拟机 V2.44.38 做只读基线核对：`listings 0003_platformproductdetail` 已应用，目标表存在；租户 1 当前为 36000 条、空平台商品 ID 36000 条、变体重复组 0，四个应用容器均为 V2.44.38。

## 发布前/后复核门禁

- 四个应用容器必须从 V2.44.38 切换，目标镜像必须为 V2.44.39；Redis 容器 ID 保持不变。
- 专项后端测试覆盖变体 ID 幂等更新、平台商品 ID 重复、租户隔离和导入错误反馈。
- `/products/platform-details` 返回 200；未登录访问列表 API 和导入 API 均返回 401。
- 前端资源必须包含平台商品明细导入接口和“变体 ID”字段文案。
- 菜单标签、深色导航 CSS、角色权限资产继续存在；发布后检查后端/前端日志无严重错误。

## 部署与复核结果

- 部署完成时间：`2026-08-24T15:57:22+08:00`。
- 后端镜像 ID：`sha256:530316ab224e7006ceefe4581d4a47b4b79d2646192c165f5e8a0d2ddbbce7d4`。
- 前端镜像 ID：`sha256:0f80c1c4cee068cd042a8f55e86587ddc2aeecd66c7fa239a8b7609c0b0fa5e1`。
- 数据库备份：`pre-deploy-v2.44.39.sql.gz`，SHA-256 `a37c99df9ef6df1a38ecb25d56ff73e66c7339f3fa86788994428f83028d299b`，1,352,103 bytes。
- 后端专项测试 4/4 通过；前端专项与回归测试 17/17 通过；前端生产构建通过。
- Django 检查、迁移差异检查、Nginx 配置检查均通过，未产生新迁移。
- 租户 1 发布前后均为：36,000 条平台明细、36,000 条空平台商品 ID、0 个重复变体组；部署未修改业务数据。
- 已登录界面复核：新导入按钮和 36,000 条数据正常；权限目录仍为 189 项；导航栏实际背景色为 `rgb(23, 53, 80)`。
- `/`、`/products/platform-details`、`/system/roles` 均返回 200；未登录访问列表与导入 API 均返回 401。
