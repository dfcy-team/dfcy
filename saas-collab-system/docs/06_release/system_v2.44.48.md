# 系统版本 V2.44.48（已部署）

登记日期：2026-08-28

基线版本：V2.44.47

发布状态：已部署并完成服务器复核

## 更新内容

- 完整保留 V2.44.47 已发布的开发A API数据接入功能。
- 在“基础档案”子菜单末尾新增“基础档案设置”。
- 在设置页新增“商品分类背景颜色”，可按当前租户维护二级类目的商品列表背景色。
- 商品主数据和商品明细数据共用该配置；未设置自定义颜色时继续使用原有默认背景色规则。
- 支持颜色预览、输入、颜色选择器、恢复默认及批量保存。

## 权限与数据边界

- 新增 `masterdata.settings.view`：查看基础档案设置。
- 新增 `masterdata.settings.manage`：维护基础档案设置。
- 迁移仅给内置启用的 `administrator` 角色补充新权限，其他角色由权限配置页面按需授权。
- 背景颜色按租户和二级类目存储；接口拒绝跨租户和非二级类目更新。
- 普通商品分类编辑接口只读返回颜色字段，不能绕过专用设置权限修改。

## 菜单保护

- 顶级菜单仍为16个，名称和顺序保持V2.44.47基线。
- 原“基础档案”13个子节点名称和顺序不变，仅在末尾增加第14个节点。
- 路由仅新增 `/master-data/settings`。
- `MainLayout.vue` 未修改，深色桌面与移动端导航样式保持不变。

## 数据库变更

- `products.0014_productcategory_row_background_color`：为商品分类增加背景颜色字段。
- `permissions.0033_seed_masterdata_settings_permissions`：登记查看、维护权限并同步内置管理员角色。

## 验证结果

- 前端完整测试：253项通过。
- 前端生产构建：通过。
- 后端基础档案设置、商品API与分类元数据定向测试：13项通过。
- Django `check`：通过。
- Django `makemigrations --check --dry-run`：通过，无遗漏模型变更。
- 后端 `compileall`：通过。
- 菜单契约测试锁定顶级结构、基础档案原节点顺序和深色导航样式。

## 发布结果

- 应用虚拟机：`192.168.174.131`。
- 后端、Celery、Celery Beat：`saas-collab-backend:v2.44.48`。
- 前端：`saas-collab-frontend:v2.44.48`。
- 镜像源码修订：`78ac6ce1d64f1715663b754a4c4d049e2fc1f9a9`。
- 已执行并复核迁移：`products.0014`、`permissions.0033`。
- 租户1发布前后数量一致：分类68、SPU 396、SKU 6604。
- `/`、`/products/master`、`/products/details`、`/master-data/settings`、`/system/roles`、`/integrations/configs` 均返回 HTTP 200。
- 未登录访问设置接口返回 HTTP 401，专用权限边界生效。
- 服务器静态资源中已确认原16个顶级菜单标签、新增设置节点及深色导航 CSS 均存在。
- 后端、前端、Celery、Celery Beat 最近日志未发现关键错误。

## 备份与证据

- 发布证据目录：`/home/dfcy01/releases/system-v2.44.48-build-20260828`。
- 发布前数据库备份：`pre-deploy-v2.44.48.sql.gz`，大小5,529,602字节。
- 备份 SHA-256：`163be18b5e1066d7e81072832ce1071101905021fbd638102e6b22879be838e8`。

发布脚本首次执行通用 `migrate` 时带入基线中既有但未执行的 `purchasing.0005`。该采购表当前为0行，已在最终复核前安全回退至 `purchasing.0004`；脚本随后改为只执行本版本的两项目标迁移，并增加后端 API 就绪等待。最终迁移状态与 V2.44.47 基线相比仅新增 `products.0014` 和 `permissions.0033`。
