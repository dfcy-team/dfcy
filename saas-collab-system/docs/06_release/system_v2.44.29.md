# SaaS 协同系统 V2.44.29 发布登记

- 登记日期：2026-08-15
- 父版本：V2.44.28
- 部署前线上基线：V2.44.28
- 发布状态：已部署
- 部署时间：2026-08-15 14:59（Asia/Shanghai）
- 数据库迁移：无
- 菜单结构：与 V2.44.28 完全一致

## 本次授权范围

本版本仅包含以下两项修改：

1. 扩展“基础档案 > 商品明细数据”的单条编辑和按新旧 SPU 批量修改字段。
2. 更新“系统治理 > 角色与权限”的权限选择界面，使权限按最新菜单层级和顺序展示。

未修改 `menu.js`、路由、导航布局、菜单节点、商品模型或数据库迁移。

## 商品明细编辑扩展

单条编辑和批量修改新增以下字段：

- 重量（g）
- 体积（m³）
- 长、宽、高（cm）
- 原产国
- HS 编码

字段规则：

- 数值字段校验精度并禁止负数。
- 原产国最大 80 个字符。
- HS 编码为 2–20 位字母、数字及允许的点、横线和空格。
- 普通空值表示“不覆盖原值”。
- 只有勾选“清空”时才通过 `clear_fields` 明确删除已有值。
- 批量预览为纯读取，不会写入数据库。
- 仍保持租户、data scope 和 `products.master.manage` 权限边界。

## 角色权限菜单同步

- 权限目录按每页 100 条连续读取，避免原页面只显示前 100 项。
- 按当前 15 个一级菜单及其子菜单顺序显示权限。
- 同一路径的 `routeCapabilities` 权限与菜单节点合并并去重。
- 未映射到可见菜单的管理、审批、导入等动作权限保留在“其他操作权限”。
- 保存时只提交后端权限目录实际返回的权限码。
- 内置管理员角色仍由权限目录自动同步，不能手工修改。

## 菜单复核

- V2.44.29 菜单 SHA256：`c4919748b05f596ede323f0dfc86e7d58bcae40abb366b952ffb00889a4b3ab9`
- V2.44.28 登记菜单 SHA256：`c4919748b05f596ede323f0dfc86e7d58bcae40abb366b952ffb00889a4b3ab9`
- 两者完全一致。
- 一级菜单数量：15。
- 菜单节点数量：104；路由权限声明数量：102；当前权限目录定义数量：123。
- 一级菜单顺序：工作台、产品开发、全球刊登、经营分析、经营决策、达人管理、流程协同、业务协同、RPA协同、API数据接入、财务中心、报表中心、基础档案、系统治理、治理与试点。
- 本次未修改 `frontend/src/router/menu.js`、`frontend/src/router/index.js` 或 `frontend/src/layouts/MainLayout.vue`。

## 验证结果

- 商品明细后端测试：8 项通过。
- Django `manage.py check`：通过。
- 商品明细前端测试：6 项通过。
- 角色权限定向测试：3 项通过。
- Vite 非 Mock 生产构建：通过；构建参数为 `VITE_USE_MOCK=false`、`VITE_API_BASE_URL=''`。
- `git diff --check`：通过，仅保留工作区既有换行符提示。
- 全量 UI-P2 仍有 1 个既有 `StoreMasterList` 平台名称契约断言失败，与本版本修改无关。

## 部署产物

- 前端入口：`index-Do5aK0Dt.js`
- 商品明细资源：`ProductDetailData-KvuZxKPz.js`
- 商品明细样式：`ProductDetailData-cP3s0Hi3.css`
- 角色权限资源：`RolePermissionMatrix-CvrYWEbN.js`
- 角色权限样式：`RolePermissionMatrix-B3260y1r.css`
- 目标前端镜像：`saas-collab-frontend:v2.44.29`
- 目标后端镜像：`saas-collab-backend:v2.44.29`

## 部署结果

- 目标：`https://192.168.174.131:8443`
- 审计目录：`/home/dfcy01/releases/system-v2.44.29-build-20260815`
- 后端镜像 ID：`sha256:2803d532de10a08a76e9ddfff10ed4d305fe35497ad7df1d3a88ee0dfb8436d0`
- 前端镜像 ID：`sha256:681766e8b9af9bcca0132d3a3948dcfa2cf444b686cba17d2ca4553c07cba8fe`
- 仅执行 `docker compose up -d --no-deps backend frontend`；Celery、Beat、Redis 容器 ID 保持不变。
- 未执行数据库迁移。
- Django 运行态检查和 Nginx 配置检查均通过。
- `/`、`/products/master`、`/products/details`、`/products/platform-details`、`/system/roles` 均返回 200。
- `/api/internal/health/` 返回 200；未认证商品明细和权限目录 API 返回 401，路由存在且非 404。
- 线上入口、商品明细和角色权限资源 SHA256 均与登记一致。
- 线上 15 个一级菜单逐项复核通过，菜单结构未发生变化。
- 回退仍使用 V2.44.28 的前后端镜像及 `/home/dfcy01/releases/system-v2.44.28-build-20260815`。
