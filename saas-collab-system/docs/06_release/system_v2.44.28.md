# SaaS 协同系统 V2.44.28 发布登记

- 登记日期：2026-08-15
- 部署日期：2026-08-15
- 父版本：V2.44.27
- 部署前线上基线：V2.44.26
- 发布状态：已部署
- 部署地址：`192.168.174.131:8443`
- 数据库迁移：无
- 菜单结构：保持 V2.44.26/V2.44.27 不变

## 本次授权范围

V2.44.28 累计发布以下两项已登记修改：

1. V2.44.27 的“平台商品明细数据”分页优化，包括每页条数、页码跳转、总数显示、越界页校正和响应式分页布局。
2. “商品明细数据”新增 SKU 级物理与海关字段展示：重量、体积、长、宽、高、原产国和 HS 编码。

未修改菜单、路由、导航布局、商品模型或数据库迁移，也未调整其他业务页面。

## 字段与数据来源

| 页面字段 | API/模型字段 | 单位或格式 |
| --- | --- | --- |
| 重量 | `package_weight` | g，最多 3 位小数 |
| 体积 | `package_volume` | m³，最多 6 位小数 |
| 长 | `package_length_cm` | cm，最多 3 位小数 |
| 宽 | `package_width_cm` | cm，最多 3 位小数 |
| 高 | `package_height_cm` | cm，最多 3 位小数 |
| 原产国 | `origin_country` | 文本 |
| HS 编码 | `hs_code` | 既有校验格式 |

- 旧商品映射行读取 `ProductLegacyItem` 的原始导入值。
- 独立 SKU 行读取 `ProductSKU` 的 SKU 级字段。
- 不从 SPU 推导这些字段，空值统一显示为 `-`。

## 范围锁定

- 菜单源码 SHA256：`c4919748b05f596ede323f0dfc86e7d58bcae40abb366b952ffb00889a4b3ab9`
- `menu.js`、路由和 `MainLayout` 未修改。
- 构建参数：`VITE_USE_MOCK=false`、`VITE_API_BASE_URL=''`。
- 未执行数据库迁移。

## 部署产物

- 前端镜像：`saas-collab-frontend:v2.44.28`
- 前端镜像 ID：`sha256:1c0e26ea944e353ec93846d8421efd6eb1cae0eb2175dfdf8d948b966ca6a6c4`
- 后端镜像：`saas-collab-backend:v2.44.28`
- 后端镜像 ID：`sha256:17497a6489e20939f7ed605e2d9ee670787b3b0c4cdb981471e42f4408a2ac5c`
- 前端入口：`index-DzQOLpxa.js`
- 商品明细资源：`ProductDetailData-BjeeOjhf.js`
- 商品明细样式：`ProductDetailData-Dh6S0kI1.css`
- 远端审计目录：`/home/dfcy01/releases/system-v2.44.28-build-20260815`

## 部署验证

- 后端 `manage.py check`：通过。
- HTTPS `/`、`/products/master`、`/products/details`、`/products/platform-details`：均返回 200。
- `/api/internal/health/`：返回 200。
- 未认证商品明细 API 与平台商品明细 API：返回 401，确认路由存在且认证边界有效。
- 线上入口、商品明细和平台商品明细资源 SHA256：与登记值一致。
- 15 个一级菜单标签全部存在，菜单源码哈希保持不变。
- 仅重建 backend/frontend；Celery、Beat、Redis 容器未重启。
- 未执行数据库迁移。

## 回退

如需回退，使用保留的 V2.44.26 镜像与发布目录：

- `saas-collab-frontend:v2.44.26`
- `saas-collab-backend:v2.44.26`
- `/home/dfcy01/releases/system-v2.44.26-build-20260815`
