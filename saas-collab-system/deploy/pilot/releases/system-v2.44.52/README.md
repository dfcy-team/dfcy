# V2.44.52 受控生产增量发布包

本包对应已核定的合并提交 `e3dc85b948ffa7ddee9bf5ffc7e3ae16d95d4644`，父基线为
`v2.44.51` / `db8a4dabfaac40f0baef444ff0de26abe7d98091`。范围是 Shopee 正式 OAuth
就绪修复、平台档案仓储服务平台类型与仓库 API 接入绑定；不带入其他未发布开发节点。

## 现场路径与版本

现场 release directory 固定为：

`/home/dfcy01/releases/system-v2.44.52-e3dc85b-20260901`

架构员需把 Git bundle/clone 放在 `reviewed-source/`，仓库根目录为
`reviewed-source/`，应用目录为 `reviewed-source/saas-collab-system`。默认源目录已经写入
`lib-v24452.sh` 和 `env.v24452.example`，Docker build context 只使用该应用目录。

当前运行基线是混合版本：backend/Celery/Celery Beat `V2.44.50`、前端 `V2.44.51`、
credential custody `V2.44.50 (healthy)`。目标是 backend/Celery/Celery Beat 和前端统一
为 `V2.44.52`；custody 不重建，继续使用 `saas-collab-custody:v2.44.50`。

## 数据库安全边界

唯一数据库动作是 `masterdata.0009_warehouse_service_platform`。脚本按顺序读取
应用层受保护的 `.env.pilot`，使用其中现有的 `saas_collab_pilot_user` 连接
`saas_collab_pilot` 完成 `mysqldump`、`migrate --plan` 和精确迁移。迁移前必须产生
gzip 完整性和 SHA-256 证明；迁移计划必须只包含该一个 migration。

`INFLUENCERS_MIGRATOR` 在正式库只有 SELECT 权限，禁止替代应用账号、提权、改 grant，
也禁止使用 `.influencers-migration.cnf`。任何上述文件出现时脚本直接阻断。密码只从
VM 的 `.env.pilot` 在运行时读取，不进入 Git、镜像、参数记录或证据文件；发布包不含
任何真实密码、Token、证书或私钥。

## 构建、发布与复核顺序

1. 可在受保护 `.env.pilot` 中显式填写准确的当前 Compose 链
   `PILOT_RELEASE_COMPOSE_CHAIN`；若旧基线没有该项，脚本只读使用当前
   `application-frontend-1` 的 Compose 配置标签并逐项校验文件存在。
   同时确认 `PILOT_REPO_DIR` / `PILOT_SOURCE_DIR` 指向上面的 reviewed source。
2. 架构员执行 `./preflight-v24452.sh` 或 `./deploy-v24452.sh --precheck-only`。
   该阶段检查 Git ancestry、严格 changed-path allowlist、当前混合版本、custody
   health、凭据挂载隔离和 Compose 解析，不切换容器、不执行 DDL。
3. 架构员执行 `./deploy-v24452.sh`。它先构建并测试 backend/frontend，再由
   `migrate-v24452.sh` 备份、精确计划并执行唯一迁移，最后仅滚动更新四个应用容器。
4. 运行 `./verify-v24452.sh`，复核镜像/容器健康、custody 隔离、Django check、
   migration 状态、`myjf` 分类、仓库平台类型绑定和 HTTPS 根页。
5. 运行 `./register-v24452.sh` 前，主代理必须在最终运行复核通过后，在受控 Git mirror
   中完成 `v2.44.52-deployed` 和 canonical ref 指向候选提交。登记脚本只验证已有 tag
   和 ref，绝不创建 tag、合并、推送或修改 Git。
6. 运行 `./post-verify-v24452.sh` 完成统一/旧账本、digest、tag、migration 和
   `OWNER_VERIFICATION_REQUIRED` 复核；owner 验收仍由负责人完成。

## 回滚

`./rollback-v24452.sh` 仅恢复应用镜像：backend/Celery/Celery Beat 回到
`V2.44.50`，前端回到 `V2.44.51`，custody 保持 `V2.44.50`。它不执行
`docker compose down`、不删除 custody 数据、不 reverse migration、不恢复数据库，
并要求 `0009` 已应用后才允许切换。由于本迁移含 nullable `PROTECT` 外键和精确分类
修订，若必须恢复数据库，须由架构员先评估并使用迁移前备份制定恢复方案。

所有脚本的失败证据都应保留在现场 evidence directory；不得将生产备份或 `.env.pilot`
加入本目录 Git。发布包本身仅包含模板、脚本、镜像构建定义和非敏感版本元数据。
