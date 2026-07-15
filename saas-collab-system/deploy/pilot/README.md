# 阶段3生产试点安装包

本目录是阶段3生产试点的安装模板，不是正式生产发布包。当前推荐拓扑是两台 Ubuntu Server 虚拟机：数据库主机运行原生 MySQL 8.4，应用主机运行 Docker 化的 Redis、Django、Celery 与前端 Nginx。

- `database/`：保留的单机 Docker MySQL 模板；两机部署不使用该目录启动数据库。
- `application/`：应用主机上的 Redis、Django、Celery worker/beat 与前端 Nginx 模板。

先在数据库主机完成原生 MySQL 安装、业务库和最小权限账户配置，再在应用主机配置 `.env.pilot` 并启动应用栈。真实 `.env.pilot` 文件只能由密钥托管系统或受控运维主机生成，绝不能提交到 Git。

本安装包不启用真实平台接入、真实 RPA、自动采购、自动改价、自动清仓、自动资金操作。
