# SaaS 协同系统 V2.44.16 商品明细数据页面发布登记

- 登记日期：2026-08-14
- 父版本：V2.44.15
- 发布状态：已登记并部署

本版本仅更新“基础档案 > 商品明细数据”对应页面及其必要的只读聚合接口，不调整菜单、路由位置或其他页面。

- 商品明细数据页面统一展示旧 SPU/SKU 与新 SPU/SKU 的对应关系。
- 新增租户和数据范围裁剪后的分页查询接口：`GET /api/internal/products/details/`。
- 保留既有商品导入、更新和编码生成操作。
- 菜单源码 SHA256 保持为 `c4919748b05f596ede323f0dfc86e7d58bcae40abb366b952ffb00889a4b3ab9`，与父版本一致。
- 前端入口：`index-BGEaSsQ3.js`，SHA256 `e19e1c83f151cb4cb607e2771b4237827b6c04dce9d191643c5b030cc5950dbc`。
- 商品明细页面包：`ProductDetailData-_IH1ASm5.js`，SHA256 `0b4bae93bb95ae23e65aa59549352fa92b77c660a54fb6dcac06c4f6c89ab249`。
- 前端镜像：`saas-collab-frontend:v2.44.16@sha256:ad0221f7e96ad5c7e667f0be95a78c1a0f91e48e87eb72091b54ed361f81de22`。
- 后端镜像：`saas-collab-backend:v2.44.16@sha256:aaed8026846cb63932de00f342f007c78d87c18e245fb0b25750b8cb9a9963fa`。

验证结果：前端生产构建通过；后端 `manage.py check` 通过；站点与 `/products/details` 返回 200；未登录访问新接口返回 401 而非 404，证明路由已上线并受认证保护。

