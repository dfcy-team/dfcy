# 受控内网试点 P1 整改复验报告

## 1. 整改对象

- 整改日期：2026-07-21
- 仓库基线：`002ee03a4e448b6bda86727f043cf6799571dc08`
- 目标环境：Ubuntu 24.04 应用虚拟机、Ubuntu 24.04 数据库虚拟机、MySQL 8.4.10
- 整改范围：客户端证书信任、试点环境编码、主机补丁维护、虚拟机登录凭据

本次只处理受控内网试点准入的四项 P1。未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台；未启用真实 RPA、自动采购、自动改价、自动清仓、生命周期自动变更或资金操作。

## 2. 整改结论

**PASS**

四项 P1 的技术整改和命令行回归均已完成。客户端已安装受控根 CA，服务端证书已替换为包含试点 DNS 名称和应用主机 IP SAN 的 CA 签发证书；数据库环境编码已统一为 `controlled-pilot`；两台主机已完成批准更新、重启和服务回归；已披露的共享口令已分别轮换，SSH 已关闭密码登录并改为独立密钥认证。

当前运行中的浏览器自动化窗口无法可靠确认地址栏状态，安全控制主动终止了可视化操作。因此未伪造浏览器截图或菜单/退出流程结果；该证据缺口降为 P2，建议在浏览器重新启动后执行一次人工可视化确认。系统信任库、证书链和不跳过证书校验的 Windows HTTPS 请求已经通过。

## 3. 原 P1 关闭情况

| 原编号 | 原问题 | 是否关闭 | 实际证据 | 备注 |
|---|---|---|---|---|
| PILOT-CONTROLLED-P1-001 | 浏览器不信任当前自签名证书 | 是 | 创建受控根 CA；服务端证书 SAN 包含试点 DNS 与应用主机 IP；根 CA 已进入 Windows 当前用户与本机受信任根；OpenSSL 链验证通过；Windows `Invoke-WebRequest` 未使用跳过证书参数返回 200 | 当前已运行浏览器可能需要重启以刷新信任缓存；可视化 UI 流程列为 P2 复核项 |
| PILOT-CONTROLLED-P1-002 | 数据库环境编码 `pilot` 与合同 `controlled-pilot` 不一致 | 是 | 受控备份后通过 Django ORM 原位更新；数据库仅保留 `controlled-pilot`；真实 HTTPS/JWT 请求返回 `environment_id=controlled-pilot`；旧编码请求被 403 拒绝 | 未通过前端临时改写规避合同 |
| PILOT-CONTROLLED-P1-003 | 主机补丁维护未闭环 | 是 | 两台主机完成 `apt update`、批准更新、必要的完整升级、重启及回归；运行内核均为 `6.8.0-136-generic`；无重启要求；仅保留 Ubuntu phased rollout 的 `snapd` | Docker、MySQL、后端、前端、Celery、Celery Beat、Redis 均恢复正常 |
| PILOT-CONTROLLED-P1-004 | 已披露的虚拟机登录凭据未轮换 | 是 | 两台主机使用不同随机口令完成轮换；新口令只以 Windows DPAPI 密文保存在仓库外；独立 SSH 密钥登录与新口令 `sudo` 均通过；有效配置为 `PasswordAuthentication no`、`KbdInteractiveAuthentication no`、`PermitRootLogin no` | 旧口令无法再通过 SSH 使用；未在报告、Git 或日志中记录新口令 |

## 4. 证书与 HTTPS 复验

1. 根 CA 私钥采用 AES-256 加密，解密材料由 Windows DPAPI 保护并保存在仓库外。
2. 服务端证书有效期至 2027-07-21，包含 `serverAuth`、试点 DNS 名称及应用主机 IP SAN。
3. Nginx 使用的新私钥权限为仅 root 可读；旧证书和私钥已在目标主机受限目录中备份。
4. OpenSSL 使用受控根 CA 验证服务端证书返回 `OK`。
5. Windows 系统信任库能够建立完整证书链；`Invoke-WebRequest` 未配置证书跳过回调并返回 HTTP 200 和统一健康响应。
6. Windows Schannel 命令行工具对内部 CA 无在线吊销端点会报告吊销状态未知；本问题不影响已建立的受信任证书链，但后续应将 CRL/OCSP 方案纳入证书生命周期管理。

## 5. 环境编码与 HTTPS/JWT 回归

使用运行时随机生成的临时内部用户和短生命周期 JWT，通过目标 HTTPS 入口完成以下实测；未记录用户名、密码或 Token。

| 场景 | HTTP 状态 | 结果 |
|---|---:|---|
| 管理验证用户登录 | 200 | PASS |
| 精确 scope 用户登录 | 200 | PASS |
| 内部健康接口 | 200 | PASS |
| 匿名读取 `auth/me` | 401 | PASS |
| 登录后读取 `auth/me` | 200 | PASS |
| 读取 `controlled-pilot` 准入 | 200 | PASS |
| 返回环境编码 | `controlled-pilot` | PASS |
| 精确 `environment_ids` scope 读取准入 | 200 | PASS |
| 使用旧环境编码 `pilot` | 403 | PASS，已拒绝 |
| 读取 `controlled-pilot` 拓扑 | 200 | PASS |
| 读取 `controlled-pilot` 容量摘要 | 200 | PASS |

总体结果：`PILOT_CONTROLLED_E2E=PASS`。验证结束后活跃临时 E2E 用户为 0。

## 6. 主机补丁与服务回归

### 应用主机

- 已安装普通更新和安全内核，当前内核为 `6.8.0-136-generic`。
- `/run/reboot-required` 不存在。
- Docker 服务为 `active`。
- backend、frontend、celery、celery-beat、redis 均为运行状态，Redis 健康检查通过。
- 最近验证窗口未发现 backend、celery 或 celery-beat traceback。

### 数据库主机

- 已安装普通更新、安全内核和批准的固件更新，当前内核为 `6.8.0-136-generic`。
- `/run/reboot-required` 不存在。
- MySQL 为 `active`，应用在数据库主机重启后重新连接成功。

两台主机当前仅显示处于 Ubuntu phased rollout 的 `snapd` 更新，不属于立即可用的未安装安全修复；应由后续例行维护窗口继续跟踪。

## 7. 凭据轮换与 SSH 边界

- 为应用主机和数据库主机分别生成了不同的新口令。
- 新口令只保存在架构员电脑的受限、DPAPI 加密材料中，不进入 Git。
- 独立 Ed25519 运维密钥已在两台主机验证。
- 两台主机 `sshd -T` 均确认：公钥认证开启、密码认证关闭、键盘交互认证关闭、root 登录关闭。
- 使用仅密码认证的 SSH 探针均返回 `Permission denied (publickey)`。
- 两台主机的新口令 `sudo` 验证通过，保留 VMware 控制台应急运维能力。

## 8. 安全确认

- 未提交真实 `.env`、数据库密码、虚拟机密码、Token、Cookie、Session、API Key、API Secret、证书私钥或 SSH 私钥。
- 未把受控根 CA 私钥复制到应用主机或数据库主机。
- 未新增真实平台连接、真实业务数据或真实财务数据。
- 未执行自动采购、自动改价、自动清仓、自动生命周期变更、真实 RPA 或资金操作。
- 数据库变更前已生成受限权限的校验和备份；备份未进入 Git。

## 9. P0

无。

## 10. P1

无。

## 11. P2

1. 浏览器重新启动后，应人工确认页面无证书警告，并补录登录、角色菜单、401/403 和退出流程截图或测试记录。
2. 为内部 CA 规划 CRL 或 OCSP，消除 Schannel 对吊销状态未知的提示。
3. 将证书到期、Ubuntu phased updates、备份校验、环境编码和 SSH 有效配置纳入持续门禁。

## 12. 准入建议

1. 允许继续受控内网试点验证和低风险页面测试。
2. 四项原 P1 不再阻断受控内网试点。
3. 本结论不允许直接接入真实平台、银行或支付系统。
4. 本结论不允许启用真实 RPA、自动采购、自动改价、自动清仓、生命周期自动变更或资金操作。
5. 真实平台接入仍必须另行完成专项安全评审、凭据托管评审和生产试点评审。
