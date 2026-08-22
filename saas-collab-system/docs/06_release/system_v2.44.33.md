# SaaS 协同系统 V2.44.33 发布登记

- 登记日期：2026-08-21
- 父版本 / 当前虚拟机基线：V2.44.32
- 发布状态：`deployed`
- 数据库迁移：不需要
- 目标：`192.168.174.131:8443`
- 回退版本：V2.44.32

## 授权范围

本版本只增量更新基础档案中的商品主数据、商品明细数据和平台商品明细数据：

1. 分类树显示编号，商品主数据和商品明细按二级分类显示稳定背景色。
2. 三张商品表增加从 1 开始的跨页序号。
3. 商品主数据增加勾选、批量修改和移动目录。
4. 商品明细增加图片字段和按旧/新 SKU 批量缓存图片链接，逐行返回处理状态。
5. 图片缓存使用独立持久卷，后端写入、前端只读展示。

不得修改或回退 V2.44.32 的菜单、路由、主布局、销售管理、产品开发或权限目录。

## 导航保护门禁

| 保护文件 | V2.44.32 | V2.44.33 | 结论 |
| --- | --- | --- | --- |
| `frontend/src/router/menu.js` | `a627102d58d29eb5db7cea5d92d82000137193efb25ba5396ad470769a872071` | `a627102d58d29eb5db7cea5d92d82000137193efb25ba5396ad470769a872071` | 未变更 |
| `frontend/src/router/index.js` | `a4fd1fd8ac188be19479d702b7673a7a8968881a00b2f227f606f605ca1d6aee` | `a4fd1fd8ac188be19479d702b7673a7a8968881a00b2f227f606f605ca1d6aee` | 未变更 |
| `frontend/src/layouts/MainLayout.vue` | `63c2092d2fa1265608cc29ba4ae0fa28245bedc822c081bcc982cad56b135619` | `63c2092d2fa1265608cc29ba4ae0fa28245bedc822c081bcc982cad56b135619` | 未变更 |

菜单门禁保持 16 个一级分组、113 个总节点、110 条路由能力声明。

## 更新前检查

- 虚拟机前后端均运行 `V2.44.32`，容器连续运行正常。
- V2.44.32 `index.html` 哈希和入口 `index-C_Tr7WJt.js` 与登记一致。
- 虚拟机 `manage.py check` 通过，`/health/` 与 `/api/internal/health/` 返回 200。
- 本地前端定向测试 24 项、后端定向测试 20 项通过。
- `manage.py check`、`makemigrations --check --dry-run`、生产构建通过。
- 菜单、路由和主布局哈希与 V2.44.32 完全一致。

## 发布策略

1. 后端镜像以 `saas-collab-backend:v2.44.32` 为基础，只覆盖 `apps/products` 的四个白名单文件。
2. 前端只使用显式生产构建产物；不从旧版本复制菜单源码。
3. 发布前保存数据库备份和原容器 `/app/media`，创建持久化商品图片卷。
4. 只切换 backend/frontend；celery、celery-beat、redis 容器不得重启。
5. 发布后复核服务、接口、静态资源哈希、商品图片读写、页面路径和导航保护门禁。

## 构建登记

- 前端 `index.html`：`57529edc8aa7bb259ce3003240cc7ff6a3c9b02115dd86397e7b7e004628701b`
- 前端入口：`index-XzChYA1L.js`
- 入口 SHA256：`942123ff99babb360f4784eb6f6a5eab998289d0f5a9651d2a240d4ff520ce59`
- 远端审计目录：`/home/dfcy01/releases/system-v2.44.33-build-20260821`

## 部署结果

- 完成时间：2026-08-21 10:41:44 CST。
- 已增量构建并切换 `saas-collab-backend:v2.44.33` 与 `saas-collab-frontend:v2.44.33`。
- 仅 backend/frontend 容器发生切换；celery、celery-beat、redis 容器标识保持不变。
- 数据库备份：`/home/dfcy01/releases/system-v2.44.33-build-20260821/pre-deploy-v2.44.33.sql.gz`，SHA256 `e9514b9790b4bb88148736f7748bbf66e866856e2f3d5b1e029abc515ea82eb2`，压缩包完整性通过。
- 商品图片持久卷 `application_product-media` 已挂载：后端 `/app/media` 可写，前端 `/usr/share/nginx/html/media` 只读。
- Django `check`、Nginx `-t` 通过；6 个页面/健康路径均返回 200。
- 3 个新增写接口均返回 401（认证保护正常）且均非 404。
- 16 个一级菜单标签、7 条销售管理页面路径全部存在；菜单、路由、主布局哈希与 V2.44.32 一致。
- 销售管理权限 8 项齐全，2 个启用中的管理员角色均拥有全部权限。
- 发布后数据复核：SPU 396、SKU 6604、旧商品 6602。
- 最近 15 分钟日志未发现后端 Traceback/Internal Server Error/CRITICAL，前端未发现 emerg/alert/crit。
- 审计归档：`/home/dfcy01/releases/system-v2.44.33-build-20260821.tar.gz`，SHA256 `cd54f461d82bb461835f5b478be559897d40a147ddef3b88402b008d3aa0af1b`。

## 回退说明

如需回退，仅需恢复 V2.44.32 前后端镜像；数据库未执行迁移。商品图片持久卷独立保留，不随容器回退丢失。
