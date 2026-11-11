# 2026-10-31 前端白屏紧急修复

## 根因
此前前端入口热修复把HTML入口改为index-b33dd7df2f83.js，但Login、送样等组件仍引用index-BrPhyQb4.js。两份入口都执行Vue应用mount，导致重复挂载，浏览器报Cannot read properties of null (reading 'nextSibling')并白屏。

## 已部署
仅修改production-frontend-1静态入口，不改组件业务、账号、数据库、后端或视频任务，不重启服务。

- 原canonical入口index-BrPhyQb4.js保留唯一应用启动代码，并保留最新广告页面和能力矩阵路由引用。
- index-b33dd7df2f83.js改为重导出canonical入口，不再另建应用。
- index.html切换到新的bootstrap-single-entry入口，该入口仅重导出canonical模块。
- 变更前校验两份入口差异仅为AdvertisingOverview、IntegrationCapabilityMatrix资源名称；部署时CAS复核并备份。

服务器备份和哈希收据：/opt/saas-collab/production/hotfix-single-entry-20261031/。
部署脚本：docs/06_release/fix_frontend_single_entry_20261031.py。

## 验证
真实Edge无痕自动化访问生产送样路径，未登录时正常显示企业登录页，浏览器脚本错误为0；送样页面模块动态加载成功。未冒用用户会话，登录后具体送样数据仍由用户刷新确认。

最初networkidle等待超时，不作为成功依据；改为检查实际DOM、浏览器错误和组件加载结果通过。

## 版本同步注意
这是生产容器静态文件热修复，并非新镜像发布。重建前端镜像前应确保完整构建产物的入口与组件依赖一致。不要只换index入口文件名而保留引用旧应用入口的页面chunks，否则可能再次重复启动Vue应用。保留已部署广告页面与能力矩阵功能，不用旧完整前端覆盖。
