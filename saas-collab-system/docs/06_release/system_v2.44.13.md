# SaaS 协同系统 V2.44.13 平台商品新 SKU 导入登记

- 登记日期：2026-08-13
- 父版本：V2.44.12
- 发布状态：已登记并部署

## 授权变更

仅修改“平台商品明细数据”的导入格式和解析：模板新增“新SKU编码”；旧 SKU 编码与新 SKU 编码至少填写一个；两者同时填写时优先按当前租户的新 SKU 编码精确关联。未修改菜单、路由、其他页面或数据库结构。

菜单 SHA-256 保持 V2.44.12 不变：`c4919748b05f596ede323f0dfc86e7d58bcae40abb366b952ffb00889a4b3ab9`。

## 构建证据

- Python 编译检查：PASS
- Vite production build：PASS（2018 modules transformed）
- bundle 入口：`frontend/dist/assets/index-CoowVWqQ.js`
- bundle 入口 SHA-256：`668fa25da01674707466b33c37a28e31ed1ad9c86ea99cea09b22542604b76c3`
- 平台商品明细 chunk：`PlatformProductDetailList-BuAv2rBL.js`
- chunk SHA-256：`6d57f8b404dcd40d3043a2d22f081b74e9e1e7926eb872fc5403aa38f1a1c81b`
- 前端镜像：`saas-collab-frontend:v2.44.13@sha256:3c93ffc2beb80b17d1f1151c189347c6927fc0ddc3663752c9390b8fc080951b`
- 后端镜像：`saas-collab-backend:v2.44.8@sha256:a6a41bfb585454b844376ba770ef4695c27ac7ec1d8dcfadcfeca729535fdb13`
- 虚拟机页面 HTTP 200，后端 `manage.py check` 通过。
