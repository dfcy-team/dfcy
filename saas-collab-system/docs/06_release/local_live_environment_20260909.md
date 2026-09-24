# 本地真实联调环境（2026-09-09）

状态：基础环境已启动；用户完成审批后，已只读确认 v5 生效、HTTP 加密托管可达、DEBUG=False。旧 Shopee 凭据尚未迁入新托管，不视为真实平台联调已通过。

## 入口和隔离

- 按用户“覆盖 3001”要求，前端沿用 http://127.0.0.1:3001，连接新后端 http://127.0.0.1:8002。
- 3002 已停止。原隔离后端 8001、原验收库和启动脚本保留供回退；未修改虚拟机或阿里云。
- 新库 `saas_collab_live_local_20260909` 由本地 `saas_collab_acceptance_20260909` 一致性快照恢复，使用专用数据库账号，未覆盖原库。
- Django 使用 `config.settings.local_live`，DEBUG=False，仅监听回环地址；未启动 Celery worker/beat，调度表为空。
- 本机浏览器到应用使用回环 HTTP；不是可暴露到局域网或公网的生产部署。平台与托管均使用验证证书的 HTTPS。

## 托管服务

- 独立进程：https://127.0.0.1:8444；复用现有 `custody_service.py`。
- Bearer 服务认证、Fernet 认证加密落盘；应用数据库仅保存引用。
- 运行文件目录：`C:/Users/Administrator/Desktop/开发/.codex-tmp/live-local-20260909`，已关闭继承并限制当前 Windows 用户访问。
- 证书有效期 90 天，专用于本地托管，不修改系统信任库；到期应更新证书，不能禁用验证。
- 应用只配置认证文件和 CA 文件路径，不显示 Token、加密密钥或 TLS 私钥。
- 没有迁移旧文件托管中的真实秘密；旧引用不能被当作新托管中的可用授权，需要后续确认迁移或重新填写。

## 受控出站

- `network-policy.json` 为进程级出站上限，目前仅包含现有配置能明确确认的 `partner.shopeemobile.com`、`auth.tiktok-shops.com`，平台端口限定 443。
- 允许本地 MySQL 127.0.0.1:3307、本地托管 127.0.0.1:8444；其他本地或局域网目的地拒绝。
- 已确认本机 Meta Tunnel 使用 Fake-IP；仅允许白名单域名 DNS 解析产生的对应 198.18.0.0/15 地址，不允许整个网段。平台客户端仍验证主机名、证书和应用白名单。
- TikTok 区域 API 域名和极风 API Base URL 在当前有效配置中缺失，不猜测、不开放通配符；确认后同时补应用白名单及进程网络策略并重启。
- 不自动执行授权、刷新平台 Token、同步、采购或刊登。

## 待登录后在本地页面提交的配置

原生效版本继承自快照，仍为 `custody.backend=file`，会覆盖环境变量；没有直接修改不可变的版本或伪造审批。

已在本地内置浏览器的用户会话中提交 v5（创建人 ID 40），后端只读核对为 `pending_approval`、`approved_by_id=null`，当前有效版本仍为 v4。新版本只更改托管后端、URL、Host、认证文件及 CA 文件路径，其他现有策略保留。页面禁止创建人审批自己的版本，未尝试绕过。

后续用户确认审批完成：只读复核有效版本为 v5、runtime_valid=true、custody.backend=http、custody_gate=true、live_mode_gate=true。应用经实际配置访问托管 `/healthz` 返回 200。配置 ID 5 的授权门禁列表为空，但真实解析其现有凭据引用返回 HTTP 400 / CUSTODY_OPERATION_FAILED；仅检查记录路径确认旧托管文件存在、新托管记录不存在，未读取旧密钥、未迁移文件或发起平台 API 调用。需要通过“维护凭据”重新安全保存 Partner Key，或另行执行经确认的迁移流程。

### 旧引用重新保存兼容修复

用户重新保存时报 `Credential custody rotation failed`。源码原因：托管查不到旧引用时返回通用 HTTP 400，经通用网络客户端转为 OAuthFlowError，而凭据替换服务仅捕获 CustodyError，导致在保存新值前退出。

本地修复将已认证的“查无引用”查询结果明确为 `{"found": false}`，适配器转换为专用 CustodyReferenceNotFound。只有这类明确缺失且本次有新密钥时，替换服务才创建新托管记录；认证失败、网络错误、损坏/不可读记录继续失败关闭，不自动新建引用。旧文件不会被读取、迁移或删除，业务授权不会因此标为连通。

隔离 SQLite/合成凭据回归最终 34 passed / 3 skipped（Windows 不适用 POSIX 权限项），119.08 秒。覆盖 HTTP 托管旧引用替换、加密落盘、认证失败/503/记录损坏不创建记录，以及已有凭据维护、TikTok 回调配置与仓库幂等。仅重启本地 8444 托管和 8002 后端；用户真实密钥没有重新提交，平台 API 未调用。

在 API 数据接入 → 生产环境配置 → 密钥托管服务填写：

| 字段 | 值 |
| --- | --- |
| 托管后端 | 独立 HTTPS 托管服务 |
| 服务 URL | https://127.0.0.1:8444 |
| 服务 Host | 127.0.0.1 |
| 认证文件路径 | C:/Users/Administrator/Desktop/开发/.codex-tmp/live-local-20260909/custody.token |
| CA 文件路径 | C:/Users/Administrator/Desktop/开发/.codex-tmp/live-local-20260909/custody-cert.pem |

保持生产刊登关闭。网络出站白名单与上述进程策略对齐；自动同步不因环境搭建而启用。提交后通过应用原有权限与版本审批流程生效。

## 验证证据

- `test_custody_service.py`、`test_custody_security_gate.py`：12 passed / 3 skipped（Windows 不适用的 POSIX 权限检查）。
- Django system check：0 issues；运行配置 DEBUG=False，新数据库名称正确，Celery 调度条目为 0。
- 3001 返回 HTTP 200，前端实际 API 地址为 8002；3002 无监听。
- 真实本地 TLS 托管自检：证书验证通过；未认证请求返回 401；合成凭据可保存/读取且文件不含其明文；撤销后不可读取。
- 出站负向检查：拒绝局域网 192.168.2.10:443、非授权公网 IP、非授权 Fake-IP、非允许端口。
- Shopee 443 TLS 握手通过；未请求业务 API，未使用真实平台凭据。
- 自检报告在运行目录 `selftest-report.json`；保留已撤销的合成测试记录，不混入业务授权。

## 启动和回退

脚本位于 `C:/Users/Administrator/Desktop/开发/.codex-tmp/`：

- `start-live-custody.py`：先启动本地 TLS 托管。
- `start-live-backend.py`：启动非 DEBUG 后端；访问日志不记录 OAuth 回调查询串。
- `start-live-frontend.ps1`：启动 3001，指向 8002。

回退时先核对 3001 监听进程确属新 Vite，再停止它并运行原 `start-acceptance-frontend.ps1`（指回 8001）。不能按端口盲杀进程，不能整库覆盖恢复。新旧运行密钥不同，切换后需重新登录。
