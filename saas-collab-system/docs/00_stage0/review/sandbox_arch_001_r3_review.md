# SANDBOX-ARCH-001-R3 固定提交部署现场复审报告

## 1. 复审对象

- 复审日期：2026-07-22
- 复审性质：固定提交部署与独立 Sandbox 现场复审
- 固定基线：`origin/main@2b85bb03b6046c2e58c1d0c5cb9bc70a8bb0c515`
- 整改提交：`446bf221106df334b7a8e91ca93a0be026895f28`
- 合并记录：PR #32，merge commit `2b85bb03b6046c2e58c1d0c5cb9bc70a8bb0c515`
- 复审依据：`sandbox_arch_001_r2_review.md`、`sandbox_arch_001_r2_p1_fix_change_log.md`、`deploy/sandbox/README.md`、`sandbox_acceptance_checklist.md`

本次复审仅认可实际命令输出和可追溯制品。未执行的现场项目不以静态检查或 Pilot 环境结果替代。

## 2. 复审结论

**CONDITIONAL_PASS**

未发现 P0。R2 的 Pilot 同摘要晋级实现和最小权限 JWT/API E2E 实现缺口已经关闭，固定提交已合并 `main`，不可变制品工作流成功并生成固定镜像摘要。

现场部署尚不能完成：当前 VMware 只运行受控 Pilot 应用主机 `192.168.174.131` 和数据库主机 `192.168.174.132`，没有经确认的独立 Sandbox 应用主机、独立 Sandbox 数据库主机及第三台未授权来源探针主机。另一个停机 Ubuntu 配置与现有应用主机具有相同 UUID/MAC，不能作为并行独立 Sandbox 主机。为避免污染 Pilot、伪造隔离或产生网络冲突，本次未在上述主机部署 Sandbox。

因此，独立主机部署、TLS、最小权限 JWT/API E2E、数据库非法来源拒绝、公共出站阻断和重启持久化证据均未执行，Sandbox 不能标记为 PASS，也不能晋级 controlled-pilot。

## 3. 固定提交与不可变制品

| 检查项 | 结果 | 证据 |
|---|---|---|
| 固定提交已进入 `origin/main` | PASS | `2b85bb03b6046c2e58c1d0c5cb9bc70a8bb0c515` |
| PR #32 | PASS | 已使用 merge commit 合并 |
| `Sandbox immutable artifacts` | PASS | GitHub Actions run `29887518480`，结论 `success` |
| workflow HEAD | PASS | `2b85bb03b6046c2e58c1d0c5cb9bc70a8bb0c515` |
| 制品清单环境 | PASS | `environment=sandbox` |
| 制品清单 SHA256 | PASS | `efd737c4b16382ab38a48c595e414f20832348caaaaf3a149c71bbaa22eb512b` |
| 后端镜像 | PASS | `ghcr.io/dfcy-team/dfcy/saas-collab-backend@sha256:d98bc8951b70b9bc1c2a292331db3dbf8080d0f8b204c9a28b2adfd675c46e8b` |
| 前端镜像 | PASS | `ghcr.io/dfcy-team/dfcy/saas-collab-frontend@sha256:29626027ecbf4b0ec69d117662314385e497e1ec17d92cbaf647d80c9f9e520b` |
| migration SHA256 | PASS | `09fa0faf8167b7d30aac088cd785b6327ab9a2f00dbb6c3f40a33635681251c9` |

## 4. R2 原 P1 关闭情况

| 原问题 | 是否关闭 | 证据 | 备注 |
|---|---|---|---|
| Pilot 本机构建及可变标签，未实现同摘要晋级 | 是，实现关闭 | Pilot Compose 不含 `build:`；安装器强制 Git SHA、清单哈希、镜像摘要、OCI revision、迁移摘要及 Sandbox PASS evidence | Pilot 实际晋级不属于本次 Sandbox 现场部署 |
| JWT E2E 未断言最小权限和 sandbox-only data_scope | 是，实现关闭 | 脚本拒绝超级用户，要求精确 `pilot.readiness.view`、单一 custom scope、`environment_ids=["sandbox"]`，越 scope 环境必须返回 403 | 运行证据仍需独立 Sandbox |
| 网络隔离缺少独立主机运行证据 | 否 | 策略、重启复验、公共出站探针、第三来源探针和数据库 REJECT 计数器已实现 | 当前缺少独立三主机现场，运行证据未产生 |

## 5. VMware 现场资源核验

| 项目 | 结果 | 说明 |
|---|---|---|
| VMware Workstation | 已运行 | 本机存在 2 个 `vmware-vmx` 进程 |
| 应用层虚拟机 | 已运行，非 Sandbox | `E:\应用层\应用层Ubuntu 64 位.vmx`，IP `192.168.174.131`，现有受控 Pilot 应用主机 |
| 数据库层虚拟机 | 已运行，非 Sandbox | `E:\数据库层\数据库Ubuntu 64 位.vmx`，IP `192.168.174.132`，现有受控 Pilot 数据库主机 |
| 额外 Ubuntu 配置 | 不可作为独立并行主机 | `E:\新建文件夹\Ubuntu 64 位.vmx` 与应用层 VM 使用相同 UUID `56 4d df c2 ...` 和 MAC `00:0c:29:c6:fe:9e` |
| 独立 Sandbox 应用主机 | 缺失 | 不得以 Pilot 主机替代 |
| 独立 Sandbox 数据库主机 | 缺失 | 不得与 Pilot 共用数据库、卷、账号或网络 |
| 第三台未授权来源探针 | 缺失 | 无法形成数据库来源拒绝和 REJECT 计数器闭环证据 |

## 6. 现场部署结果

| 检查项 | 结果 | 原因 |
|---|---|---|
| 固定摘要镜像部署 | 未执行 | 独立 Sandbox 应用/数据库主机未具备 |
| Sandbox MySQL 安装 | 未执行 | 独立数据库主机未具备 |
| Sandbox Redis、Django、Celery、前端安装 | 未执行 | 独立应用主机未具备 |
| TLS 与浏览器信任链 | 未执行 | 缺少 Sandbox 主机名、地址和受信任证书配置 |
| `verify-sandbox.sh` | 未执行 | Sandbox 服务未部署 |
| 最小权限 JWT/API E2E | 未执行 | Sandbox 服务和短期账号未创建 |
| 公共出站拒绝 | 未执行 | Sandbox 应用主机未具备 |
| 数据库批准来源连接 | 未执行 | Sandbox 应用/数据库主机未具备 |
| 第三来源数据库拒绝 | 未执行 | 第三台探针主机未具备 |
| 应用/数据库重启持久化 | 未执行 | 独立 Sandbox 主机未具备 |
| Sandbox PASS evidence | 未生成 | 五份网络运行证据不完整时脚本必须拒绝生成 PASS |

## 7. 安全与边界

- 未在 Pilot 主机部署或覆盖 Sandbox 服务。
- 未复用 Pilot 数据库、Redis、Docker 卷、TLS、账号或运行端口。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未提交或输出真实密码、Token、Cookie、Session、API Key、API Secret 或私钥。
- 未启用自动采购、清仓、改价、生命周期自动变更、真实 RPA 或资金操作。
- 未修改 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/` 或配置代码。

## 8. P0

无。

## 9. P1

1. **SANDBOX-ARCH-R3-P1-001：独立 Sandbox 现场基础设施不完整。** 必须提供独立应用主机、独立数据库主机和第三台未授权来源探针主机；不得复用现有 Pilot 主机。
2. **SANDBOX-ARCH-R3-P1-002：固定摘要尚未在独立 Sandbox 完成运行验证。** 必须部署本报告记录的固定 Git SHA 和镜像摘要，完成 TLS、运行设置、迁移、测试及最小权限 JWT/API E2E。
3. **SANDBOX-ARCH-R3-P1-003：五份网络证据及重启持久化证据未形成。** 必须归档应用运行、应用重启、数据库重启、第三来源拒绝和数据库 REJECT 计数器证据，并由 PASS evidence 固化其哈希。

## 10. P2

1. 基础镜像 tag 仍建议进一步固定为 digest。
2. SBOM/provenance 后续建议增加独立签名及部署前验签。
3. 前端第三方依赖 PURE 注释警告继续作为非阻断观察项。

## 11. 下一次现场复审前置条件

1. 新建或批准三台互相可识别的主机：`sandbox-app`、`sandbox-db`、`sandbox-probe`，并分配独立 IP、主机名和唯一 UUID/MAC。
2. 为 Sandbox 配置独立数据库、Redis、Docker 网络、卷、端口、TLS 和短期测试账号。
3. 将本报告记录的 manifest 以 mode `0400`/`0600` 放入应用主机，不在目标主机构建镜像。
4. 配置并审批 Redis/MySQL 官方固定摘要，执行数据库和应用安装。
5. 执行两台主机重启及三主机网络探针，归档五份 mode `0400` 网络证据。
6. 使用非超级、精确权限、sandbox-only scope 的短期账号执行 JWT/API E2E，完成后删除账号和密码文件。
7. 仅在 `sandbox-verification-evidence.json` 为 PASS 且无 P0/P1 后，重新执行现场准入复审。

## 12. 准入建议

- 是否允许继续准备独立 Sandbox 主机：**允许**。
- 是否允许将当前 Sandbox 标记为 PASS：**不允许**。
- 是否允许晋级 controlled-pilot：**不允许**。
- 是否允许进入 Production：**不允许**。
- 是否允许真实平台接入或高风险自动化：**不允许，必须另行专项安全评审**。
