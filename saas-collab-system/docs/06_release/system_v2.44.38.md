# SaaS 协同系统 V2.44.38 发布登记

- 登记日期：2026-08-24
- 父版本：V2.44.37
- 当前虚拟机基线：V2.44.37
- 菜单基线：V2.44.33
- 权限界面基线：V2.44.29
- 发布状态：`deployed_server_verified`
- 发布时间：2026-08-24 12:12:58 +08:00
- 数据库迁移：需要，发布前必须完成迁移计划和备份检查
- 目标：`192.168.174.131:8443`

## 增量范围

1. 在 V2.44.37 上增量接入 commerce 七类业务事实表和销售管理查询接口。
2. 保留现有七个销售管理菜单与路由，页面接入真实 API，并保留开发/测试 Mock 回退。
3. 增量接入平台配置、OAuth、凭据托管引用、店铺授权、店铺映射、商品映射和同步安全控制。
4. 增加销售明细导出和 commerce 数据回退。
5. 在原权限目录上新增 13 个 integrations 动作权限，不替换既有权限码或角色授权。
6. 真实平台网络访问保持默认关闭；未配置安全批准、允许主机和凭据托管时拒绝执行。

## 明确保持不变

- `frontend/src/router/menu.js`：保持 V2.44.37 内容和 SHA-256。
- `frontend/src/router/index.js`：保持 V2.44.37 内容和 SHA-256。
- `frontend/src/layouts/MainLayout.vue`：保持 V2.44.33 深色导航样式。
- 一级菜单 16 个、菜单节点 99 个、路由权限节点 111 个。
- V2.44.29 菜单式角色权限树、“其他操作权限”分组和管理员只读保护。
- 产品开发、达人管理、基础档案及其他既有模块不回退。

## 数据库迁移计划

- `commerce.0001_fact_tables_v1`
- `integrations.0007` 至 `integrations.0016`
- `permissions.0031_seed_integration_custody_permissions`
- `reports.0006_sales_details_export`

目标虚拟机当前已应用基线为 integrations `0006`、permissions `0030`、reports `0005`，且尚无 `commerce_` 表。实际数据库中三个旧凭据列已经全部不存在；新增迁移对此状态提供兼容分支。发布前仍需在数据库备份后执行 `showmigrations`、`migrate --plan` 和迁移后表结构复核。

## 发布前门禁

- 开发 A 交接包校验通过，但禁止直接使用其 V2.44.32 镜像或覆盖源码树。
- 菜单、路由、导航样式相对 `v2.44.37-deployed` 必须零差异。
- 前端全量测试、生产构建必须通过。
- 后端 `compileall`、`manage.py check`、迁移漂移检查和新增定向测试必须通过。
- 销售订单与退款退货使用各自权限；销售导出只要求 `sales_management.export`，不能隐式要求全局 `reports.export`。
- 发布前后均需核对 16 个一级菜单、99 个菜单节点、权限目录和虚拟机运行日志。

## 当前状态

- 源码增量合并、发布前门禁、虚拟机发布和服务器端独立复核已完成。
- V2.44.33 菜单基线、开发模块、角色权限和销售路由专项测试：`19/19` 通过。
- 前端全量测试：`23` 个测试文件、`216/216` 通过；生产构建通过。
- 后端 `compileall`、生产配置 `manage.py check`、`makemigrations --check` 通过；定向测试 `21/21` 通过。
- 仅执行 integrations `0016`、commerce `0001`、permissions `0031`、reports `0006`；未执行发现但不属于本次范围的 purchasing `0005`。
- 虚拟机运行镜像：前端 `saas-collab-frontend:v2.44.38`，后端/Celery `saas-collab-backend:v2.44.38`；Redis 容器未重建。
- 已验证七张 commerce 事实表、十三项 integrations 权限、销售管理 URL、未登录 `401` 契约、十一条页面路径、深色导航 CSS 和角色权限资产。
- 数据库备份：`/home/dfcy01/releases/system-v2.44.38-build-20260824/pre-deploy-v2.44.38.sql.gz`，SHA-256 `67627904daa67f808e0f31df95c9c57f112b80f0fa29442e9d9808a0326a5466`。
- 前端容器替换使原内置浏览器登录会话失效；服务器端复核完成，登录后的最终界面目视复核待用户重新登录。
- 已建立干净 Git 发布节点并登记标签 `v2.44.38-deployed`。
