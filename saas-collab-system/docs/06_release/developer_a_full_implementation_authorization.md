# 开发A完整实施授权记录

日期：2026-08-08

开发A获准在本项目 Shopee/TikTok Shop 受控连接范围内修改前后端、迁移、权限、部署配置和本地 Credential Custody，并可在应用 VM 与 `saas_collab_pilot` 项目数据库范围内执行部署、验证和回滚。

授权不允许：

- 将 App Secret、access token、refresh token、Cookie、Session 或 authorization code 写入 Git、业务数据库、日志、文档或聊天。
- 关闭 SSH 严格主机校验。
- 访问其他项目、其他业务库或 MySQL 系统库。
- 在缺少固定 SHA、固定制品、备份或恢复路径时宣称上线成功。

来源实现提交：`56ae18ee9d0c9cc1f2bbfd20b078ce8e60c5bee8`。

来源分支后续文档修复 HEAD：`981b5c602e3afa27975642da3cfecbd8986f0707`。

本分支未直接合并该远程分支，因为其基线会删除当前 OAuth/真实平台实现；仅移植 custody、部署和主机校验范围。
