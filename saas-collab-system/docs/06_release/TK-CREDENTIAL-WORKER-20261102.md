# TK 商城自动续期 worker 修复交接

## 已部署与实测

2026-11-02 北京时间16:42回读：生产配置v38已审批生效，18家TK商城精确绑定。
旧 credentials worker 不识别 creator_query_bindings，运行配置回退，读到0条自动续期绑定；backend读取18条。
这不是审批失败，也不是用户需要重新授权。

本次只对齐 production-celery-credentials-1 的 /app/apps/integrations/production_settings.py。
源文件与已运行backend及PR源码逐字节一致。没有修改数据库审批、账号、广告、同步任务或启动额外轮换任务。
部署前 running AutomaticRefreshAttempt 为0；使用 docker stop --time -1 等待正常退出，再启动同一worker，未重启backend或视频进程。

部署后worker读取18条绑定；既有每分钟调度器自动执行。
9家到期店铺已经续期：TK6PH、TKKJ1PH、TKKJ1TH、TKKJ5PH、TK1PH、TK2PH、TK3PH、TK4PH、TK7PH。
回读上述授权的expires_at均已到2026-11-09，last_error_code为空；TK1PH到16:42:08，TK2PH到16:42:11（北京时间）。
其余9家未到15分钟提前续期窗口，不强制刷新。
这不表示视频/联盟历史补录已完成，也不表示广告令牌已续期。

## 文件与版本

- 备份和部署源：/opt/saas-collab/production/hotfix-credential-config-20261102/
- worker旧SHA256：a5aa374a138099ca757257ffbc04ad7531ea5996e58d5017b83b0c36344cbe50
- 新SHA256：adec2d0ba24198abde958bbad3c0e7a6736e57b0034e38343f06f87beb74e314
- CAS部署脚本：docs/06_release/deploy_credential_config_20261102.py；重复执行会拒绝。
- 新源已通过compile及worker实际加载；真实续期结果以上述数据库回读为依据，不以容器启动当成功。

## 管理员发布要求

热修在容器可写层，重建容器会丢失；必须将PR中的production_settings.py构建进正式镜像，并保证backend及credentials worker采用兼容版本。
不能仅回退worker解析代码而保留含creator_query_bindings的生效配置，否则可能再次回退为安全空配置。
不要从旧前端重新提交整份生产配置覆盖新字段。达人查询与自动续期清单保持独立。
同一商城凭据统一由SaaS续期，不要同时由dfcy轮换。
广告授权不能套用商城refresh接口；本次没有修改广告令牌生命周期。
