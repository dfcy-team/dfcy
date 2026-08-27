# 开发 A 受控自助发布（架构员启用文件）

本目录实现“开发 A 可以自助发布，但不能直接操作虚拟机”的生产发布控制面：GitHub Actions 在 CI 中构建并推送后端、前端镜像，目标 VM 只拉取带 `sha256` 摘要的镜像；发布通过受限 SSH 强制命令进入，服务器脚本再用仅限指定命令的 `sudo` 规则执行部署。

这不是生产凭据或现成上线授权。当前仓库的 `AGENTS.md` 要求生产发布由架构员审查和启用；本文件提供的自助发布仅在系统负责人明确批准、完成下列安装和验收后启用。

## 控制边界

- GitHub workflow：`.github/workflows/developer-a-production-release.yml`。
- VM 固定入口：`/opt/saas-collab/release-control/unified/bin/developer-a-ci-dispatch`。
- 允许的远程操作只有 `deploy`、`rollback` 和 `check`，入口拒绝 shell 元字符、路径跳转和任意命令。
- `dfcy01` 不加入 Docker 用户组，不授予通用 root shell；sudo 只允许调用 root-owned 的部署、回滚和运行时基线检查脚本。
- 生产环境不配置 Required reviewers。取消人工审批不等于取消自动门禁；环境仍需保留 `production` 变量/密钥和审计记录。
- 目标 VM 位于内网时，GitHub-hosted runner 不能直连它。发布 job 必须使用能够访问该内网的 self-hosted runner，并在 Production 环境设置 `PRODUCTION_RUNNER_LABEL`；也可以先使用 `dry_run` 或 `check` 做本地门禁。

## 构件和门禁

每次普通发布都必须同时满足：

1. 请求的完整 Git SHA 属于受保护 `main` 的历史。
2. 后端测试、迁移检查、前端锁定依赖构建和生产控制树基线检查全部通过。
3. CI 用 `github.token` 登录 GHCR，构建带 OCI revision 的后端/前端镜像，并记录两个镜像的不可变 digest。
4. 运行时只允许 `ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:...`、`ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:...` 和 owner 批准的官方 Redis digest。
5. VM 的 root-owned 基线账本、Compose 文件链和生产环境文件完整；普通发布之间至少间隔 600 秒。
6. 预迁移备份 hook 成功，专用 `migrate` service 成功，容器健康检查和 Django `check --deploy` 成功。
7. 发布人、SHA、镜像摘要、迁移摘要、结果和时间写入 JSON Lines 审计账本；不会写入 SSH 私钥、GHCR token、数据库密码或 `.env` 内容。

紧急回滚通过单独的 `rollback --emergency` 路径执行，不受 10 分钟普通发布限频限制，但仍需要强制命令、环境锁、镜像摘要校验、健康检查和审计。回滚只切换已登记的应用镜像，不自动逆向数据库迁移；不可逆迁移必须按备份恢复/向前修复方案由架构员处理。

## 架构员首次安装（VM 上执行）

以下命令需要 root，并且应从已审查的仓库 checkout 执行。`--force` 只在已审核固定控制文件差异后使用；它不会覆盖 live dotenv 或 SSH key。

```sh
sudo bash saas-collab-system/deploy/production-control/bin/install-control.sh \
  --control-root=/opt/saas-collab/release-control/unified \
  --deploy-user=dfcy01 \
  --env-file=/etc/saas-collab/production/.env.production \
  --initialize-baseline \
  --write-sudoers
```

如果控制文件已安装，先复核差异，再显式增加 `--force`。安装脚本只安装固定入口、脚本、公共 Compose 和 root-owned 基线账本；它不会生成生产密钥，也不会改写授权 key。建议使用单独生成的 CI key，并在 `~dfcy01/.ssh/authorized_keys` 加入类似以下的一行（路径、指纹和 key 内容由 owner 实际生成）：

```text
restrict,command="/opt/saas-collab/release-control/unified/bin/developer-a-ci-dispatch" ssh-ed25519 AAAA... production-ci
```

如果 OpenSSH 版本不接受 `restrict`，使用等价的 `no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty` 选项，并保留 `command=`。不要复用开发 A 的个人 key，也不要在 authorized_keys 中允许普通 shell。

### 生产环境文件

将 `env.production.example` 复制到 owner 管理的 live 路径，填写实际值后设置 `root:root`、`0400` 或 `0600`。不得提交 Git。默认控制树通过 `config/env.path` 指向该文件；实际生产可在 `PRODUCTION_COMPOSE_FILES` 中使用冒号分隔的已审核 Compose 文件链，例如现有 Pilot overlay。每一个 Compose 文件及其项目目录必须是绝对路径，且在基线初始化时被记录哈希。

至少需要调整：

- `PRODUCTION_COMPOSE_PROJECT_DIR`、`PRODUCTION_COMPOSE_FILES`、TLS 路径和真实数据库地址；
- `PRODUCTION_RUNTIME_ENV_FILE` 对应的 live env 路径（脚本会以 `config/env.path` 的路径为准）；
- `PRODUCTION_REQUIRE_BACKUP=true` 和 root-owned、不可符号链接的 `PRODUCTION_BACKUP_COMMAND`；
- `PRODUCTION_REQUIRED_SERVICES`、`PRODUCTION_MIGRATION_SERVICE` 与既有 Compose service 名称。

若目标 VM 当前运行的是 Pilot/自定义 overlay，不要把它替换成 canonical Compose。先把已审查的现有 Compose 文件按顺序写入 `PRODUCTION_COMPOSE_FILES`，设置正确 `PRODUCTION_COMPOSE_PROJECT_DIR`，再初始化基线；控制脚本会对整条文件链做 digest 校验。

### 接管当前版本

第一次 CI 发布前，owner 必须从运行中的 VM 和已审查的镜像 registry 取得当前 backend/frontend/Redis 的真实 `@sha256` 引用，并计算当前镜像内 migration tree 的 SHA-256。确认当前容器确实使用这些摘要后执行：

```sh
sudo /opt/saas-collab/release-control/unified/bin/adopt-current.sh \
  --release-sha=<40-char-main-sha> \
  --backend-image=ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:<64-hex> \
  --frontend-image=ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:<64-hex> \
  --redis-image=redis@sha256:<64-hex> \
  --migration-sha256=<64-hex> \
  --actor=owner \
  --confirm-current
```

不能用 `:latest`、`:v2.44.44` 等可变标签接管。若当前 VM 只有标签而没有可确认的 registry digest，应先由 owner 做一次同版本摘要化迁移和验收，不能让 CI 直接猜测回滚点。

## GitHub Production 环境

在仓库 `Settings → Environments → production` 配置以下 Variables：

| 类型 | 名称 | 示例/说明 |
| --- | --- | --- |
| Variable | `VM_HOST` | `192.168.2.10`（内网地址） |
| Variable | `VM_PORT` | `22131` |
| Variable | `VM_DEPLOY_USER` | `dfcy01` |
| Variable | `PRODUCTION_RUNNER_LABEL` | 能访问 VM 的 self-hosted runner label |

配置以下 Secrets：

| 名称 | 内容 |
| --- | --- |
| `VM_SSH_PRIVATE_KEY` | 仅用于该 forced-command CI key 的私钥 |
| `VM_KNOWN_HOSTS` | owner 固定的 VM host key，禁止关闭 host key 校验 |

Production 环境不要添加 Required reviewers，否则会重新引入人工审批。保留分支/环境访问范围、Actions 权限和审计；`GITHUB_TOKEN` 由 workflow 的 `packages: write` 权限用于推送并在任务期间临时登录 GHCR，VM 不保存长期 GHCR PAT。

## 开发 A 的使用方式

开发 A 在 GitHub Actions 手动选择：

- `dry_run`：只执行 main SHA、测试、基线和本地镜像构建，不推送、不连接 VM；
- `check`：执行仓库基线检查；选择 `ssh` 时才会调用 VM 的 `check` 强制命令；
- `deploy`：必须选择 `ssh`，传入 owner 批准的 Redis digest，CI 推送后调用固定 `deploy`；
- `rollback`：必须选择 `ssh` 并填写单行原因，立即调用 emergency rollback，不受 10 分钟限频影响。

普通发布由 GitHub workflow concurrency 和 VM `flock` 双重互斥；VM 脚本还会拒绝 600 秒内的普通发布。部署失败且已有受管当前版本时，服务健康检查失败会自动恢复 `previous.json`；回滚失败会保留审计事件并明确要求 owner 介入。

开发 A 不应也不能：保存 VM 私钥、执行 `ssh` 普通 shell、加入 Docker 组、读取 live env、上传本地镜像、在 VM 构建源码、手工执行生产迁移或修改控制树基线。

## 本地静态验收

在仓库根目录执行：

```sh
bash saas-collab-system/deploy/production-control/tests/test-production-control.sh
bash saas-collab-system/deploy/production-control/bin/production-baseline-check \
  --ci --repo-root "$PWD"
```

测试不启动 Docker、不连接 VM、不读取生产凭据；它检查 workflow/脚本语法、强制命令拒绝规则、Compose 无 build/特权入口、摘要和频率门禁是否仍存在。
