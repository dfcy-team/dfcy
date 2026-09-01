# V2.44.50 独立凭据托管 sidecar 发布说明

## 发布边界

V2.44.50 是从正式运行的 `v2.44.49`（Git commit
`61c68a59323e70dab226b5c6f441bf1bb14a00b3`）开始的增量修复，范围仅为
`integrations.credential_custody`。它修复正式外部地址下“Approved credential
custody is not configured”的维护凭据链路：业务 backend/celery 通过内网
HTTPS 调用独立 sidecar，sidecar 使用 Fernet 加密落盘。

本版本无 Django 数据库迁移、无生产 DDL、无平台 live 网络放行。`migrate`
服务通过 Compose profile 排除，Shopee/TikTok 等外部平台仍保持关闭。

## Compose 组成

运行配置必须按当前 V2.44.49 的完整 Compose 链加载，再追加本目录的
`docker-compose.yml`：

1. application 基础 compose；
2. `system-v2.44.24-build-20260814`、`system-v2.44.26-build-20260815`、
   `system-v2.44.28-build-20260815`、`system-v2.44.29-build-20260815`、
   `system-v2.44.30-build-20260815`、`system-v2.44.31-build-20260815`、
   `system-v2.44.32-build-20260817`、`system-v2.44.33-build-20260821`、
   `system-v2.44.34-build-20260823`、`system-v2.44.35-build-20260823`、
   `system-v2.44.37-build-20260823`、`system-v2.44.38-build-20260824`；
3. `architect-developer-a-v2.44.47-r2-20260828`、
   `system-v2.44.48-build-20260828`、
   `system-v2.44.49-reviewed-pr59-20260831`；
4. `system-v2.44.50/docker-compose.yml`。

发布脚本会验证这些路径存在，不能只使用基础 compose，否则会丢失既有
`product-media` 和其他累计运行挂载。

sidecar 仅加入 `saas-pilot-network`，不发布宿主机端口，运行身份默认为
非 root `1000:1000`，rootfs 只读、`no-new-privileges`、丢弃全部 Linux
capabilities。sidecar 独占：

- `custody-master.key`（Fernet key，0400）；
- `custody-tls.key`（TLS 私钥，0400）；
- `custody-data`（目录 0700，记录 0600）；
- TLS 证书和 service token 只读挂载。

backend/celery/celery-beat 只能看到只读的 service token 与 CA，不能挂载
master key、TLS 私钥或 custody 数据目录。`bootstrap-custody-v24450.sh`
必须由架构员在应用层虚拟机以 root 执行，负责为非 root UID/GID 修正专属
路径权限；它不会生成、打印或上传任何秘密。

## 执行顺序

在发布包所在目录放入由架构员确认的完整候选 SHA：

```bash
printf '%s\n' '<40位候选commit SHA>' > candidate-commit.txt
chmod 0640 candidate-commit.txt
```

使用 `env.v24450.example` 作为无秘密模板填写受保护的 `.env.pilot`。所有
密钥路径必须是应用层虚拟机上的绝对普通文件，不能为符号链接；master key、
TLS 私钥、token、CA、证书分别由受控账号保存，不能进入 Git、镜像层、日志
或数据库。

依次运行：

```bash
./bootstrap-custody-v24450.sh
PRECHECK_ONLY=1 ./deploy-v24450.sh
./deploy-v24450.sh
./register-v24450.sh
./post-verify-v24450.sh
```

`deploy-v24450.sh` 会先确认 v2.44.49 四个运行容器、候选 descendant、完整
Compose 链和密钥权限，再使用三条 `docker build --pull=false` 构建 backend、
custody、frontend 镜像。镜像内测试在任何运行容器切换前执行：

- backend：`test_custody_security_gate.py`、
  `test_integration_credential_maintenance.py`、`test_database_settings.py`；
- custody：`test_custody_service.py`。该门禁保持 sidecar 的非 root UID/GID，
  从 `/tmp` 执行并显式使用 `pytest -c /dev/null /app/tests/test_custody_service.py`；
  镜像仅以 `0444` 复制 sidecar 所需的 `apps` 包文件，避免读取继承镜像中
  root-only 的 `/app/pytest.ini`，不放宽宿主或运行时权限。

随后先启动并等待 sidecar health，再切换 backend/celery/celery-beat/frontend。
脚本不调用 `migrate`、`makemigrations`、`docker compose down` 或生产 DDL。

## 登记与验收状态

仅架构员运行 `register-v24450.sh`。它要求：实际容器和镜像 revision 等于
候选 SHA、canonical ref 与 `v2.44.50-deployed` 已在受控 Git mirror 指向
候选、双账本当前版本仍为 v2.44.49。通过后先备份，再原子写入：

- unified：`/opt/saas-collab/release-control/unified/ledger/current-version.json`、
  `ledger/release-history.jsonl`、`releases/2.44.50/release-record.json`；
- legacy：`/opt/saas-collab/release-control/shared-version-ledger/current-version.json`、
  `release-ledger.jsonl`；
- 两边的 `LATEST.sha256`、`OWNER_VERIFICATION_REQUIRED.json`。

登记字段固定为 parent `2.44.49`、status
`deployed_pending_owner_verification`、`release_actor=architect`、
`source_actor=architect`、scope `integrations.credential_custody`、
`database_migrations=NONE`。`post-verify-v24450.sh` 只做只读核对双账本、
canonical ref、tag、容器镜像 digest、sidecar health、`product-media` 两处
挂载和 owner marker；不会替用户接受验收。

如 sidecar 或业务入口核验失败，执行 `rollback-v24450.sh`。该脚本使用同一
历史 Compose 链直到 v2.44.49，只切换应用镜像，保持平台 live 关闭，保留
专属 custody 数据供事件审查，不删除数据、不恢复数据库、不执行迁移。

## 证据与回滚说明

部署证据目录应至少包含：候选 SHA、构建 stdout/stderr、镜像 ID、切换前后
运行容器、测试结果、迁移前后 `showmigrations integrations`、deployment
status、post-verify status。任何失败都必须保留错误状态并停止后续动作；不得
把 token、Fernet key、TLS 私钥或响应中的秘密写进这些证据。
