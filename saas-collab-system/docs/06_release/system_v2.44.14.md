# SaaS 协同系统 V2.44.14 导入状态与超时修复登记

- 登记日期：2026-08-13
- 父版本：V2.44.13
- 发布状态：已登记并部署

仅修复平台商品明细导入：专用请求超时由全局 10 秒调整为 120 秒；导入弹窗显示文件选择、上传解析、完成/失败状态、文件名和实际耗时；导入期间禁止重复提交和关闭弹窗。未修改菜单、路由、后端导入规则或其他页面。

- 菜单 SHA-256（与 V2.44.13 一致）：`c4919748b05f596ede323f0dfc86e7d58bcae40abb366b952ffb00889a4b3ab9`
- Vite build：PASS（2022 modules transformed）
- bundle：`frontend/dist/assets/index-VVfflGnU.js`
- bundle SHA-256：`52a361723762485aad64b93c7dafa897aae5ef8638cfcc7e52932b83d830b938`
- 页面 chunk：`PlatformProductDetailList-BX4wcNCU.js`
- chunk SHA-256：`62ceffbaf6d515f3bb8cc3a3558c350ae59bdb1fdfad03be34e2208eb6254fa6`
- 前端镜像：`saas-collab-frontend:v2.44.14@sha256:6535091b67f907a7b29ee42fbd5fc8f37084b4c7dd9eaa00e49708dfd03bfea0`
- 虚拟机页面 HTTP 200，后端系统检查通过。

