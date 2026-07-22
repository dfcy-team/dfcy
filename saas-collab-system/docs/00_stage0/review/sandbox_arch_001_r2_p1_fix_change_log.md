# SANDBOX-ARCH-001-R2 P1 整改变更日志

## 1. 整改对象

本次定向处理 `sandbox_arch_001_r2_review.md` 中的三项 P1：Pilot 同摘要晋级、最小权限 JWT/API E2E，以及独立 Sandbox 主机网络隔离实测证据。

## 2. Pilot 同摘要晋级

- Pilot Compose 已删除后端、前端目标主机构建和可变 `:pilot` 标签，统一消费 `PILOT_BACKEND_IMAGE`、`PILOT_FRONTEND_IMAGE` 与 `PILOT_REDIS_IMAGE` 的固定摘要。
- Pilot 安装器强制读取受控 Sandbox 制品清单与 PASS evidence，校验文件权限、Git SHA、清单 SHA256、前后端摘要、OCI revision 和迁移摘要。
- Sandbox E2E 通过且五份网络实测证据均有效后，才原子写入 mode `0400` 的 PASS evidence；运行设置检查仅生成 `runtime-verified`，不能用于晋级。
- CI 新增 Pilot 可变标签和目标主机构建负向门禁。

## 3. JWT/API 最小权限 E2E

- E2E 明确拒绝超级用户，要求 internal、有效 tenant、权限集合精确为 `pilot.readiness.view`。
- E2E 要求仅有一个 custom data_scope，且 `environment_ids` 精确为 `sandbox`。
- 脚本临时登记第二个受控环境作为越 scope 样本，并要求 readiness 严格返回 403；首次创建的样本在退出时清理。
- JWT、密码和认证头只存在于 mode `0400`/`0600` 临时文件，不进入命令行参数或证据 JSON。

## 4. 网络隔离证据

- 应用与数据库策略应用脚本记录策略哈希、链哈希、应用时间和 boot ID。
- `collect-network-evidence.sh` 支持 current/post-reboot 验证；post-reboot 必须证明 boot ID 已变化且策略与链未漂移。
- `probe-runtime-network.sh` 生成数据库正向连通和公共出站拒绝证据。
- `probe-db-source-denied.sh` 只能在显式批准的第三台未授权来源主机运行，并拒绝使用批准应用主机作为负向样本。
- PASS evidence 固化应用运行、应用重启、数据库重启、第三台来源拒绝和数据库 REJECT 计数器五份证据的 SHA256；Pilot 缺少任一哈希即拒绝安装。

## 5. 测试与状态

2026-07-22 在架构工作区实际执行：

| 检查 | 结果 | 证据摘要 |
|---|---|---|
| Shell 语法 | PASS | 17 个 Sandbox/Pilot Shell 脚本通过 `sh -n` |
| Sandbox 安装负向门禁 | PASS | `SANDBOX_INSTALL_GUARDS=PASS` |
| Pilot 晋级负向门禁 | PASS | `PILOT_PROMOTION_GUARDS=PASS` |
| JWT/网络合同静态门禁 | PASS | `SANDBOX_CONTRACT_GUARDS=PASS` |
| Sandbox 应用 Compose | PASS | 示例配置展开成功且无 `build` |
| Sandbox 数据库 Compose | PASS | 示例配置展开成功且无 `build` |
| Pilot 应用 Compose | PASS | 示例配置展开成功且无 `build` |
| workflow YAML | PASS | Python/PyYAML 解析成功 |
| 仓库安全门禁 | PASS | 无禁止文件或高置信凭据模式 |
| Django check | PASS | 0 issues |
| migration 一致性 | PASS | `No changes detected` |
| 后端全量 pytest | PASS | `399 passed` |
| 前端测试 | PASS | 11 files，`153 passed` |
| 前端生产构建 | PASS | Vite 构建成功；仅第三方 PURE 注释警告 |
| 独立 Linux Sandbox 网络实测 | 未执行 | 需要应用主机、数据库主机、第三台未授权探针主机及一次受控重启 |
| 最小权限 JWT/API E2E | 未执行 | 需要独立 Sandbox TLS、数据库和短期最小权限账号 |

P1-001 与 P1-002 的实现缺口已定向修正，仍需以固定提交在独立 Sandbox 主机执行验证。P1-003 的策略、计数器和证据链已实现，但运行证据尚未产生；在五份网络证据与 Sandbox PASS evidence 归档前，不声明该 P1 已关闭，也不允许晋级 Pilot。

## 6. 安全确认

- 未提交真实 `.env`、密码、Token、Cookie、Session、API Key、API Secret 或私钥。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未启用真实 RPA、高风险自动化、自动采购、清仓、改价或资金操作。
- 未修改后端、前端或 RPA 业务代码。
