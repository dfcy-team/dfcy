# SaaS 协同系统 V2.44.34 发布登记

- 登记日期：2026-08-23
- 父版本 / 虚拟机基线：V2.44.33
- 发布状态：`deployed`
- 数据库迁移：需要（`influencers 0007` 至 `0011`）
- 目标：`192.168.174.131:8443`
- 回退版本：V2.44.33

## 授权范围

本版本仅在 V2.44.33 上增量发布开发B的达人管理功能：

1. 扩展达人档案、建联任务、送样履约和 TikTok 视频数据层。
2. 新增 BD 订单归因、汇率、绩效统计、导出和诊断能力。
3. 只在“达人管理”中新增一个“BD绩效”子节点；其他 15 个一级菜单及原有子节点不调整。
4. BD 绩效页面必须同时具备 `influencers.outreach.view` 和 `influencers.fulfillment.view`。
5. 修复 V2.44.33 源码快照中开发产品档案清空平台/站点时的 null 兼容，防止重新构建产生回归。

## 发布前门禁

- 虚拟机运行镜像确认为前后端 `V2.44.33`。
- 达人迁移基线确认仅到 `0006`。
- 后端全量测试：`496 passed`。
- 前端全量测试：`208 passed`。
- 达人前端定向测试：`15 passed`。
- `manage.py check` 通过，`makemigrations --check --dry-run` 无变更。
- 前端生产构建通过。
- 菜单为 16 个一级分组；仅增加 BD 绩效一个子节点。

## 镜像登记

- 后端：`saas-collab-backend:v2.44.34`，镜像 ID `sha256:e1813b5fad8b941c02cbf2a9e92f6cb06ed7612428e5e68eaa850ec4392a1162`。
- 前端：`saas-collab-frontend:v2.44.34`，镜像 ID `sha256:caa8e136ab8242c6850e53199dc7513470e454f2e982e3c7e8a727a2d9b15a10`。
- 镜像包 SHA256：`cd0e12fba9a378c573b834f37450d2c7e3fc1146145054f82b91f45f90c49647`。

## 发布策略

1. 备份 V2.44.33 数据库并验证 gzip/SHA256。
2. 基于 V2.44.33 镜像只叠加达人模块、必要的兼容修正与新前端 dist。
3. 执行 `influencers 0007-0011` 迁移后只切换 backend/frontend。
4. 首次切换仅更新前后端；发布后复核发现开发 B 的订单归因会调用新增 Celery 任务，因此再将同一 V2.44.34 后端镜像增量应用到 Celery 和 Celery Beat，Redis 保持不动。
5. 发布后重新核对迁移、健康、菜单、权限、关键页面和日志。

## 部署结果

- 完成时间：2026-08-23 14:34:16 CST。
- 已切换 `saas-collab-backend:v2.44.34` 和 `saas-collab-frontend:v2.44.34`。
- 后端容器 ID：`6c194f23a0dd15259bc75a64aae2067920c21fefe58db625197c4175837bbabd`。
- 前端容器 ID：`37d9d00671b740e057a65f75e9185d17371bd05e2c776e9d6f5da87709834fdb`。
- 首次发布时 Celery、Celery Beat、Redis 容器未变化；二次复核确认开发 B 新增异步任务后，Celery 与 Celery Beat 已切换为 V2.44.34，Redis 容器仍保持原 ID。
- 异步进程补充切换完成时间：2026-08-23 14:47:34 CST；Celery 容器 ID `3eb0d81d5f1d2341a061e84e889edb2a3a80470d1241a9a67a12e9ce5baa0fe0`，Celery Beat 容器 ID `162342a0501ca06e4e4b389a5aa7d154d3a8401ab328664ba3835f7a150c2879`。
- Celery 已注册 `influencers.refresh_affiliate_order_attributions` 与 `influencers.mark_overdue_sample_fulfillments`；异步进程日志无 Traceback、CRITICAL 或未注册任务错误。
- 数据库备份：`pre-deploy-v2.44.34.sql.gz`，1,344,149 字节，SHA256 `0cc237e1241c217a897285aa8da8c59be7b1144a46f0c6d0da8f770d49e654b5`，gzip 完整性通过。
- 达人迁移 `0007-0011` 全部应用。发布演练中发现全局 `migrate` 同时应用了预存的 `purchasing.0005`；该表业务数据为 0，已安全撤回到 `purchasing.0004`，并将登记脚本改为只迁移 influencers。
- `/health/` 与 `/api/internal/health/` 返回 200；BD 绩效及导出接口未登录返回 401，路由存在且认证保护正常。
- 首页、商品主数据、商品明细、达人档案、建联任务、送样履约、BD 绩效共 7 个页面均返回 200。
- 菜单保持 16 个一级分组，编译产物同时包含“BD绩效”、“候选款登记”和“销售管理”，确认新节点存在且 V2.44.33 原菜单保留。
- 权限目录中两个依赖权限均存在；25 个启用角色中 6 个同时具备两项权限。
- Django/Nginx 检查通过，近 20 分钟后端无 Traceback/Internal Server Error/CRITICAL。
