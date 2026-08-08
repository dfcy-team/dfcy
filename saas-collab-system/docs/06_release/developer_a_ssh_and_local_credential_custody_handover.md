# 开发A SSH 与本地 Credential Custody 交接

日期：2026-08-08

## SSH 主机校验

项目文件：`deploy/pilot/ssh/developer_a_known_hosts`

- 应用 VM：`192.168.2.10:22131`，ED25519 指纹 `SHA256:MF0bgnmOWAp2SOwfhURMHVP8sdjwdjMLiPEjIEoRp3U`。
- 数据库 VM：`192.168.2.10:22132`，ED25519 指纹 `SHA256:CzsuNFl20wkL1f42xrZETF7PkvzAqrlGpYieAIM1Y98`。
- 两端口已使用 `StrictHostKeyChecking=yes` 和项目 known_hosts 通过主机身份阶段。
- 密码只允许在 SSH 交互提示中输入，不得进入命令、文件或日志。

## 本地 custody 边界

`FileCredentialStore` 将真实凭据保存在业务数据库之外的专用目录：

```text
/var/lib/saas-collab/credential-custody
```

实现保证：

- 目录目标权限 `0700`，记录目标权限 `0600`。
- 临时文件、`fsync`、原子 `os.replace`。
- 进程内锁和 POSIX/Windows 跨进程文件锁。
- store/rotate 幂等冲突和版本冲突。
- revoke 清空记录中的原始值，重复 revoke 幂等。
- 外部 API 只返回固定掩码、引用、版本、状态、时间和 operation hash。
- 默认 `LIVE_CUSTODY_BACKEND=refuse`；只有显式设置 `file` 与批准路径后启用。

业务数据库新增或复用的字段仅为：

```text
credential_id
token_id
credential_mask
credential_reference_version
credential_status
credential_expires_at
credential_revoked_at
credential_operation_id_hash
```

## 应用 VM 配置

```bash
sudo install -d -m 0700 -o dev-a -g dev-a /var/lib/saas-collab/credential-custody
```

受控环境文件只填写路径和模式，不填写真实凭据：

```text
LIVE_CUSTODY_BACKEND=file
CREDENTIAL_CUSTODY_PATH=/var/lib/saas-collab/credential-custody
INTEGRATION_ENCRYPTION_PROVIDER=unconfigured-production
```

backend 与实际执行平台调用的 Celery worker 挂载该目录；数据库、Nginx 和前端不得挂载。

## 当前验证

- 文件 custody、配置安全和真实平台定向测试：`42 passed`。
- 后端全量测试：`536 passed / 3 skipped`。
- Django check：PASS。
- migration drift：PASS。
- 全新 migration：PASS。
- 从 integrations `0014` 升级 `0015`：PASS。

VM 目录创建、MySQL 8.4、固定镜像部署和真实平台 OAuth 仍必须基于后续固定 Review SHA 记录，不能使用本地未提交代码作为证据。
