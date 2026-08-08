# 开发A交接文件：虚拟机 SSH 主机校验与本地 Credential Custody

## 1. 交接结论

方框内两项已处理：

1. 应用层 VM `192.168.2.10:22131` 与数据库 VM `192.168.2.10:22132` 的 SSH ED25519 主机密钥已经与原受信任直连 VM 记录比对；端口级记录均已登记到当前 Windows 管理机的 `known_hosts`。
2. 已增加本地独立 Credential Custody 存储边界，并将平台连接配置的新建/轮换写路径切换为引用式保存。SaaS 业务数据库的新写路径只保存 `credential_id/token_id/mask/version/status/expiry/operation hash`，不保存 App Secret、access token 或 refresh token 原值。

交接对象：开发A。

处理日期：2026-08-08。

## 2. SSH 主机密钥核验结果

### 2.1 应用层 VM

- SSH 入口：`192.168.2.10:22131`
- 账户：`dev-a`
- 映射目标：应用 VM `192.168.174.131`
- 算法：ED25519
- 端口入口主机密钥与既有直连应用 VM 记录一致。
- `known_hosts` 已存在 `[192.168.2.10]:22131` 记录。

### 2.2 数据库 VM

- SSH 入口：`192.168.2.10:22132`
- 账户：`dev-a`
- 映射目标：数据库 VM `192.168.174.132`
- 算法：ED25519
- 指纹：`SHA256:CzsuNFl20wkL1f42xrZETF7PkvzAqrlGpYieAIM1Y98`
- 扫描所得密钥与 `known_hosts` 中既有直连数据库 VM 记录完全一致。
- 已新增 `[192.168.2.10]:22132` 端口级记录。

### 2.3 严格校验结果

以下严格主机校验已经通过主机身份阶段：

```powershell
ssh -o BatchMode=yes -o PreferredAuthentications=none `
    -o StrictHostKeyChecking=yes -p 22131 dev-a@192.168.2.10 true

ssh -o BatchMode=yes -o PreferredAuthentications=none `
    -o StrictHostKeyChecking=yes -p 22132 dev-a@192.168.2.10 true
```

探测最终返回 `Permission denied` 是预期结果，因为特意禁止交互式输入密码；日志中没有出现 `Host key verification failed`，证明端口级主机身份校验成功。

开发A正式登录：

```powershell
ssh -p 22131 -o StrictHostKeyChecking=yes dev-a@192.168.2.10
ssh -p 22132 -o StrictHostKeyChecking=yes dev-a@192.168.2.10
```

密码只在 SSH 交互提示中输入，不得写入命令、脚本、Git、聊天或日志。

## 3. Credential Custody 实现

### 3.1 实现文件

```text
backend/apps/integrations/custody.py
backend/apps/integrations/credential_service.py
backend/apps/integrations/models.py
backend/apps/integrations/serializers.py
backend/apps/integrations/views.py
backend/apps/integrations/admin.py
backend/apps/integrations/migrations/0014_credential_custody.py
backend/config/settings/base.py
backend/tests/test_credential_custody.py
```

### 3.2 存储边界

`FileCredentialStore/CredentialCustody` 将凭据保存在 SaaS 业务数据库之外的独立本地目录中：

- 目录权限目标：`0700`。
- 文件权限目标：`0600`。
- 每个 credential 使用独立 JSON 记录。
- 使用临时文件、`fsync` 和原子 `os.replace` 写入。
- 使用进程内锁和跨进程文件锁避免并发覆盖。
- 支持幂等键、版本冲突、过期和撤销。
- 撤销时清空 custody 文件中的凭据值。
- 对外仅返回 `CredentialReference`，没有读取原值的公共 API。

本地 custody 文件中包含平台调用所需的真实凭据，因此该目录本身属于高敏资产。它不属于 SaaS 业务数据库，但必须依赖专用卷、操作系统 ACL、加密备份和最小进程权限保护。

### 3.3 业务数据库字段

新增的业务数据库元数据字段包括：

```text
credential_id
token_id
credential_mask
credential_version
credential_expires_at
credential_status
credential_revoked_at
credential_operation_id_hash
```

旧 `credential_ciphertext`、`api_key_encrypted`、`api_secret_encrypted` 字段暂时保留用于迁移兼容，但新建/轮换接口不再写入。管理后台已隐藏 legacy encrypted 字段，避免通过 Admin 绕过 custody。

后续完成历史数据迁移并确认无旧调用方后，开发A可以另建迁移删除这些 legacy 字段。

## 4. API 接入变化

### 4.1 新建配置

`PlatformIntegrationConfigSerializer` 的 `credentials` 和 `expires_at` 为 write-only。新建配置时：

```text
页面提交凭据
 → serializer 调用 store_credentials
 → custody 在独立目录保存凭据
 → 返回 CredentialReference
 → 业务数据库只保存引用元数据
 → API 只返回星号、引用、版本、状态和过期时间
```

### 4.2 轮换配置

轮换接口调用 `rotate_stored_credentials`，透传：

- `Idempotency-Key`
- `X-Request-ID`
- 当前 credential version
- 可选 `expires_at`

已撤销凭据不能轮换；并发旧版本返回版本冲突；审计只记录固定掩码和引用元数据。

### 4.3 兼容层

旧 base64 `TestOnlyEncryptionProvider` 仅保留为显式本地/测试兼容层。Sandbox、Pilot、Production 的新写路径必须使用 custody，不能回退到 base64 或业务数据库密文字段。

## 5. 应用层 VM 部署要求

建议在应用层 VM 创建专用 custody 目录：

```bash
sudo install -d -m 0700 -o <backend-service-user> -g <backend-service-group> \
  /var/lib/saas-collab/credential-custody
```

在应用部署的受控环境文件中设置：

```text
CREDENTIAL_CUSTODY_PATH=/var/lib/saas-collab/credential-custody
INTEGRATION_ENCRYPTION_PROVIDER=unconfigured-production
```

注意：

- 不得把 `CREDENTIAL_CUSTODY_PATH` 指向 Git 工作区、Web 静态目录、共享临时目录或数据库 VM。
- custody 目录只允许后端服务账户访问，Nginx、前端、普通 SSH 用户和数据库账户不得读取。
- Docker 部署时使用独立持久卷，只挂载给 backend/Celery 中实际需要平台调用的服务。
- 备份必须加密；恢复测试不能把原值输出到日志。
- 应用日志、Celery payload、Nginx access log、APM 和错误上报不得包含请求 credentials。
- 当前实现是独立文件存储边界，并非独立网络守护进程；如果后续要求更强的进程隔离，可在保持 `CredentialReference` 合同不变的情况下封装为 Unix socket/本机服务。

## 6. 数据库 VM 要求

数据库 VM 不部署 custody，也不保存 App Secret/Token 原值。

开发A执行迁移：

```bash
python manage.py migrate integrations
python manage.py makemigrations integrations --check --dry-run
```

迁移后检查业务表只有引用元数据新字段。不得手工将 custody 文件内容、App Secret、access token 或 refresh token 写入 MySQL。

## 7. 验证结果

主代理复核运行：

```text
tests/test_credential_custody.py
tests/test_phase2_integrations_secure_config.py
tests/test_integrations_models_celery.py
```

结果：`21 passed`。

其他检查：

- `python manage.py makemigrations integrations --check --dry-run`：无迁移漂移。
- `python scripts/ci_guard.py`：通过，未发现禁止文件或高置信凭据模式。
- `git diff --check`：通过。
- Python 编译检查：通过。

## 8. 开发A上线检查

- [ ] 通过严格主机校验登录两台 VM。
- [ ] 应用层 VM 创建专用 custody 持久卷/目录并设置最小 ACL。
- [ ] 受控配置中设置 `CREDENTIAL_CUSTODY_PATH`。
- [ ] 数据库备份后执行 integrations migration 0014。
- [ ] 新建一条测试平台配置，确认 API 只返回 `***`/引用元数据。
- [ ] 检查 MySQL legacy 字段没有新增 ciphertext 或 secret。
- [ ] 轮换测试凭据，确认 version 递增且旧值被替换。
- [ ] 撤销测试凭据，确认 custody 记录内容被清空且状态为 revoked。
- [ ] 检查 Django、Celery、Nginx 和审计日志无凭据原值。
- [ ] 备份并恢复 custody 专用卷，过程不输出秘密。
- [ ] 记录部署 SHA、本地变更摘要、迁移号、目录 ACL 和验证时间。

## 9. 交接边界

本次已关闭截图中“缺少可信 known_hosts”和“业务数据库不能保存明文 App Secret/Token”的本地技术缺口。

开发A仍需在目标应用 VM 上创建专用 custody 持久卷、配置 ACL、执行迁移并完成一次真实部署验证。平台真实 App Secret/Token 只允许通过受控页面或服务端写入 custody；不得写入本交接文件或通过聊天传递。
