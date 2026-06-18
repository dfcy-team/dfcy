鼎峰 Web 平台 — 用户权限数据库说明
====================================

数据库名: dingfeng_portal
用途:     网站登录账号、角色、权限（后续接入登录页）

一、Navicat 连接
----------------
主机: 43.110.37.58
端口: 3360
用户: dingfeng
密码: DfMysql2026!
数据库: dingfeng_portal

二、表结构
----------
users             网站用户（用户名、密码哈希、邮箱）
roles             角色（admin / operator / viewer）
permissions       权限点（shop.view、content.upload 等）
user_roles        用户 ↔ 角色
role_permissions  角色 ↔ 权限
login_logs        登录日志（成功/失败、IP）

三、网站登录账号
----------------
admin / dfcyadmin        管理员（全部权限）
yanxinjie / yanxinjie001 运营（导出、授权、上传）

登录地址: https://dingfengchuangyu.com/login

四、预置角色与权限
------------------
admin     全部权限
operator  店铺授权、导出、内容上传
viewer    仅查看

权限代码:
  shop.view / shop.authorize / shop.export
  content.view / content.upload
  admin.users / admin.settings

五、重新初始化（服务器上执行）
------------------------------
cd C:\Users\Administrator\Desktop\TikTok_API\web-portal
python scripts\init_db.py

可选环境变量:
  PORTAL_ADMIN_USER=admin
  PORTAL_ADMIN_PASSWORD=你的密码

六、Flask 配置（local.env）
---------------------------
DB_HOST=127.0.0.1
DB_PORT=3360
DB_USER=dingfeng
DB_PASSWORD=DfMysql2026!
DB_NAME=dingfeng_portal

代码入口: services/db.py（后续登录模块调用）
