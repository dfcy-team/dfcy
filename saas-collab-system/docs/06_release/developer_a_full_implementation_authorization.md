# 开发A完整实施上线授权与执行交接

## 1. 授权结论

项目负责人授权开发A在 Shopee/TikTok Shop API 接入、平台配置界面、Credential Custody、销售库存同步及双虚拟机部署范围内承担开发负责人、模块架构负责人、数据库变更负责人和上线负责人角色。

开发A不需要等待其他角色批准即可执行：

- 修改前后端代码、API 合同、权限、数据模型、迁移、Celery、Nginx、Docker Compose 和部署脚本。
- 创建、切换、提交、推送和合并开发A功能分支。
- 在应用 VM 构建或拉取镜像、部署、重启、查看日志、修改项目服务配置和执行回滚。
- 在数据库 VM 对 `saas_collab_pilot` 执行备份、迁移、DDL、DML、索引检查和恢复验证。
- 配置本地 Credential Custody 持久卷、ACL、备份、轮换和撤销。
- 配置 Shopee/TikTok Shop callback、平台合同、密钥引用、同步任务和真实测试门店。
- 自主决定 mock、sandbox、pilot、connected、放量、降级、暂停和回滚状态。

完整权限仅限本项目及 `saas_collab_pilot` 业务库，不包括读取其他项目、MySQL 系统库、其他租户原始凭据或绕过操作系统审计。

## 2. 可拉取分支

- 分支：`codex/developer-a-full-implementation`
- 工作树：`.worktrees/developer-a-full-implementation`
- 内容：本地 Credential Custody、引用式数据库字段、配置 API 接入、迁移、测试、受信任 SSH host key 和开发A交接资料。

开发A使用：

```powershell
git fetch origin --prune
git switch codex/developer-a-full-implementation
```

若远端尚未推送，可直接使用共享工作树：

```powershell
cd "D:\Users\Administrator\Documents\saas协同系统\.worktrees\developer-a-full-implementation"
```

## 3. 只读执行环境的解决方式

开发A不再依赖写入个人 `%USERPROFILE%\.ssh\known_hosts`。项目提供已核对的只读主机密钥文件：

```text
deploy/pilot/ssh/developer_a_known_hosts
```

严格登录命令：

```powershell
ssh -p 22131 `
  -o StrictHostKeyChecking=yes `
  -o UserKnownHostsFile="saas-collab-system/deploy/pilot/ssh/developer_a_known_hosts" `
  dev-a@192.168.2.10

ssh -p 22132 `
  -o StrictHostKeyChecking=yes `
  -o UserKnownHostsFile="saas-collab-system/deploy/pilot/ssh/developer_a_known_hosts" `
  dev-a@192.168.2.10
```

不得使用 `StrictHostKeyChecking=no`。项目文件内的两条 ED25519 key 已分别与直连应用 VM `192.168.174.131`、数据库 VM `192.168.174.132` 的既有受信任记录匹配。

## 4. 虚拟机与数据库权限

| 目标 | 入口 | 账户 | 项目权限 |
|---|---|---|---|
| 应用 VM | `192.168.2.10:22131` | `dev-a` | sudo、Docker、项目目录、服务配置、日志、部署、重启、回滚 |
| 数据库 VM | `192.168.2.10:22132` | `dev-a` | 项目数据库运维、备份恢复目录、MySQL 客户端和迁移验证 |
| MySQL | `192.168.2.10:23306` | `dev_a` | `saas_collab_pilot.*` 的项目 DDL/DML/索引/迁移权限 |

如果数据库 VM 的 `dev-a` 仍没有项目运维权限，管理员在数据库 VM 控制台执行一次：

```bash
sudo usermod -aG sudo dev-a
sudo install -d -m 0750 -o dev-a -g dev-a /srv/saas-collab/backup
```

MySQL 管理员按现有密码库中的 `dev_a` 身份授予项目库权限；不要在命令历史或本文写密码：

```sql
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP,
      CREATE TEMPORARY TABLES, LOCK TABLES, EXECUTE
ON saas_collab_pilot.* TO 'dev_a'@'<approved-source>';
```

`DROP` 只用于获批迁移或回滚，不授权访问 `mysql.*`、其他业务库或创建全局用户。

## 5. Credential Custody 上线权限

开发A可在应用 VM 创建并管理：

```bash
sudo install -d -m 0700 -o dev-a -g dev-a /var/lib/saas-collab/credential-custody
```

部署配置：

```text
CREDENTIAL_CUSTODY_PATH=/var/lib/saas-collab/credential-custody
INTEGRATION_ENCRYPTION_PROVIDER=unconfigured-production
```

开发A可以写入、轮换、撤销和备份 custody 记录，但不得把 App Secret、access token、refresh token、Cookie 或授权 code 写入 Git、SaaS 数据库、日志、聊天或交接文件。

## 6. 上线执行顺序

1. 拉取或进入交接分支，记录 HEAD。
2. 运行 custody 与 integrations 定向测试。
3. 数据库 VM 备份 `saas_collab_pilot`。
4. 应用 VM 创建 custody 专用目录并配置 ACL。
5. 执行 integrations migration `0014_credential_custody`。
6. 构建并部署 backend/Celery/frontend。
7. 验证健康接口、权限、配置新建、密钥轮换和撤销。
8. 检查业务数据库仅有引用、星号、版本和状态。
9. 检查 Django、Celery、Nginx、审计和 APM 无秘密。
10. 使用 Shopee/TikTok Shop 测试门店执行授权和只读同步。
11. 由开发A决定继续放量、修复、降级或回滚。

## 7. 停止条件

完整实施权限不允许忽略以下事实性故障：

- 凭据进入 Git、业务数据库、日志或前端响应。
- tenant/store 数据串租户。
- 数据库迁移不可恢复且无有效备份。
- SSH 主机密钥与本交接文件不一致。

发生上述问题时，开发A有权且应立即停止相关能力、自行修复或回滚，不需要等待其他角色批准。

## 8. 当前验证证据

- SSH `22131/22132` 主机密钥已匹配直连 VM 受信任记录。
- Custody 与 integrations 定向测试：`21 passed`。
- integrations 迁移检查：无漂移。
- CI 凭据扫描：通过。
- `git diff --check`：通过。

本授权文件是开发A执行项目级部署、数据库迁移和平台接入的正式交接依据。操作系统账户或 MySQL 权限若仍未实际生效，由虚拟机/数据库管理员按第 4 节一次性落地；不得把“文档授权”等同于已经改变系统 ACL。
