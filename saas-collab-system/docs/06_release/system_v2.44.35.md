# SaaS 协同系统 V2.44.35 发布登记

- 登记日期：2026-08-23
- 父版本：V2.44.34
- 菜单基线：V2.44.33
- 发布状态：`deployed`
- 数据库迁移：不需要
- 目标：`192.168.174.131:8443`

## 修复范围

1. 恢复 V2.44.33 的完整菜单和路由结构。
2. 仅保留开发 B 增量“达人管理 → BD绩效”及 `/influencers/bd-performance` 路由。
3. BD 绩效仍要求同时具备 `influencers.outreach.view` 与 `influencers.fulfillment.view`。
4. 修正生产构建未设置 `VITE_USE_MOCK` 时错误进入 Mock 工作台的问题；生产默认使用真实 Pilot API。
5. 只替换前端容器，后端、Celery、Celery Beat、Redis 和数据库均不调整。

## 发布前门禁

- 一级菜单保持 16 个。
- 菜单叶节点为 99 个，即 V2.44.33 的 98 个加 BD绩效 1 个。
- 路由权限节点为 111 个，即 V2.44.33 的 110 个加 BD绩效 1 个。
- 相对 V2.44.33 的 `menu.js` 与 `router/index.js` 差异仅包含 BD绩效。
- 前端全量测试：`210 passed`。
- `VITE_USE_MOCK=false` 生产构建通过。
- 前端镜像：`saas-collab-frontend:v2.44.35`，镜像 ID `sha256:a95a3772f32f6dddd5c8e11bd240219b306b52a7ff5aaa6e9b74b14334676b54`。

## 部署结果

- 完成时间：2026-08-23 16:07:41 CST。
- 前端已切换为 `saas-collab-frontend:v2.44.35`，容器 ID `8d6168f814050700fa1a69ba834a0f82ca731d228bcc7defda5ba151ea4bdf23`。
- 后端、Celery、Celery Beat、Redis 的镜像和容器 ID 均与发布前一致；数据库未执行迁移。
- 首页、商品主数据、商品明细、达人档案、建联任务、送样履约、BD绩效、角色权限共 8 个页面均返回 HTTP 200。
- 内置浏览器已确认页面进入“Pilot API 环境 / 内部用户 JWT”登录，不再显示 Mock、stage0_internal_user 或 mock-tenant-001。
- 达人 BD 绩效及导出接口未登录返回 HTTP 401，路由存在并受认证保护。
- 运行产物核对为 16 个一级菜单、99 个菜单节点；相对 V2.44.33 只增加“BD绩效”。
- Nginx 检查通过，后端与前端近期日志无严重错误。
