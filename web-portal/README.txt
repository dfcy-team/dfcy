TikTok Shop Web Portal
======================

位置（与 API 项目同级）:
  <项目根>/web-portal/
  <项目根>/正式环境/店铺配置/

自动识别项目根:
  - 本机开发: Desktop\TikTok_API\  （web-portal 与 正式环境 同级）
  - 部署包:   xxx\TikTok_API\web-portal + xxx\TikTok_API\TikTok_API\正式环境

页面
----
  首页:      /
  控制台:    /dashboard
  授权说明:  /authorize  （与线上一致：环境地址、3步流程、粘贴回调、复制链接）
  正式授权:  http://dingfengchuangyu.top/authorize
  OAuth回调: /callback
  部署信息:  /ruike
  隐私政策:  /privacy

本机启动
--------
  1. copy local.env.example -> local.env（默认 8080 端口）
  2. 双击 start.bat
  3. 浏览器: http://127.0.0.1:8080/dashboard

服务器（dingfengchuangyu.top）
------------------------------
  1. local.env 里 LISTEN_PORT=80，SITE_DOMAIN=dingfengchuangyu.top
  2. 管理员运行 start.bat
  3. 域名解析到本机 80 端口

功能
----
  - OAuth 回调 + 写入 config_<店>.env
  - Web 触发：店铺罗盘 / 订单 / 流水 Excel 导出
  - 下载 logs 与 店铺分析API接口 下的 xlsx

Partner redirect_url:
  http://dingfengchuangyu.top/callback
