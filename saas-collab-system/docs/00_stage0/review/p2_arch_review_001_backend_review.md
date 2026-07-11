# P2-ARCH-REVIEW-001 开发A阶段2后端成果审核报告

## 1. 审核对象与方法

- 审核对象：`origin/feature/phase2-a-api-status-finance`。
- 对比基线：`origin/main`，提交 `ff726fe2e0e5868d9d754c17a797bdded499ec64`。
- 审核 HEAD：`fb00be6c7e44edebf49c56a06426a9b3a3d33586`。
- 审核方式：`origin/main...origin/feature/phase2-a-api-status-finance` 差异审阅；项目目录外 detached worktree 静态检查；GitHub PR #5 远端 CI 结果核验。
- 未将开发A分支合并到架构审核分支，未修改开发A代码。

## 2. 分支基线与修改范围

目标分支包含 `origin/main` 和阶段2规划基线，相对 `origin/main` 领先 14 个提交、落后 0 个提交。无写入 `merge-tree` 预检未发现与当前 main 的冲突。

修改范围覆盖开发A约定的后端 API、模型、迁移、测试、CI、示例环境变量及交付文档；未包含前端、RPA Agent 脚本或 `docs/04_rpa` 协议改动。

## 3. API接入配置与凭据安全

- `APIIntegrationConfig` 保存 `api_key_encrypted`、`api_secret_encrypted` 等加密字段，而不是普通明文字段。
- 静态扫描发现的 `not-a-real-secret` 位于 Mock adapter demo 记录中；未发现真实 URL、真实账号或高置信度真实凭据。
- 未发现 `requests`、`httpx`、`aiohttp` 等真实平台 HTTP 客户端实现；本地开发允许的地址仅为 localhost。
- 交付代码与文档声明 production adapter 默认拒绝执行，Mock 运行限定为精确 Mock adapter，真实平台连接不在本次范围内。

结果：通过。

## 4. Mock/Sandbox同步任务框架

已增加同步任务、运行记录、游标、幂等、锁和重试相关模型/服务/迁移。同步框架使用 demo/Mock adapter，并有锁租约、游标和恢复性重试提交。未发现把 sandbox placeholder 当作真实或 Mock 平台执行的证据。

结果：通过。

## 5. 商品状态机

已增加状态快照、建议和流转模型，以及评估、确认、拒绝服务。状态建议与最终确认分离；`products.status.confirm` 和高风险确认权限控制确认/清仓等业务状态。API/RPA 数据只能作为建议来源，RPA 不得自行决定业务状态。

结果：通过。

## 6. 财务对账基础模型

平台账单、取款、银行回单、匹配、异常和财务审计模型均具有 tenant 关联。财务查询按当前用户 tenant 过滤；确认接口使用财务权限类，确认匹配前再次校验 tenant。导入和匹配服务均为 demo/Mock 流程，未发现真实银行接口或真实资金操作。

结果：通过。

## 7. 供应商绩效统计

供应商绩效快照和统计服务按 `tenant_id + supplier_id` 聚合。供应商外部接口从认证档案取得 supplier_id，并拒绝请求中伪造的其他 supplier_id；内部汇总由权限和数据范围控制。

结果：通过。

## 8. RPA稳定性增强

RPA 增加任务尝试、证据、账号锁和页面签名能力。代码和测试覆盖最大重试次数、重试转 `manual_required`、心跳超时人工接管、失败步骤和最后成功步骤。RPA 执行端点保持 `/api/rpa/*` 边界；静态检查未见 RPA 访问 `/api/finance/*`、`/api/internal/finance/*` 或 `/admin/` 的调用。

结果：通过。

## 9. tenant隔离

产品状态、财务、供应商绩效、同步和 RPA 新增核心模型均具有 tenant 关联；静态审阅的列表、详情、确认和统计路径均以当前用户 tenant 过滤。产品状态目标和确认路径额外检查 tenant 一致性。

结果：通过。

## 10. internal/external/rpa/finance权限边界

- 集成管理使用内部授权边界。
- 财务读写和确认使用独立财务权限；普通 internal、external、supplier、RPA 不应默认获得财务确认能力。
- 供应商本人绩效使用 external 路径与认证 supplier_id；内部汇总使用内部路径与 DataScope。
- RPA Agent 只执行 RPA 协议动作，不承载财务、内部管理或业务判断权限。

结果：通过。

## 11. 测试与迁移证据

已核验：PR #5 的 GitHub Actions 中仓库安全、Django/pytest、前端构建、Docker Compose 配置、RPA 样例与文档门禁均为 `SUCCESS`。

本地 detached worktree 实际执行情况：

| 项目 | 结果 | 说明 |
|---|---|---|
| Django check | 未执行 | 本机无可用 `py`/Python 解释器 |
| migration 一致性检查 | 未执行 | 本机无可用 `py`/Python 解释器 |
| pytest | 未执行 | 本机无可用 `py`/Python 解释器 |
| CI YAML 静态解析 | 未执行 | 本机无可用 Python YAML 运行时 |
| Docker Compose 配置 | 未执行 | 本机未安装 Docker CLI |
| RPA JSON 校验 | 通过 | detached worktree 内 JSON 均可由 PowerShell `ConvertFrom-Json` 解析 |
| 安全扫描 | 部分通过 | 使用 `rg` 静态扫描代码与敏感模式；完整 `ci_guard.py` 因无 Python 未执行 |

开发A提交的 CI 指南/交付报告记录了完整本地复现命令和测试结果；本报告未将该自述替代架构审核实际执行结果，远端 Actions 成功结果作为独立证据。

## 12. 安全扫描

未发现真实 `.env`、私钥、证书、SQLite 数据库、RPA 运行产物、真实平台 HTTP 调用、真实 BigSeller/Shopee/TK/TikTok/银行/支付配置或高置信度真实凭据。发现的凭据字段均为加密字段名或 demo/placeholder 值，不构成阻断问题。

## 13. P0/P1/P2

### P0

无。

### P1

无。

### P2

1. 架构审核机缺少 Python 与 Docker CLI，未能本地重复 Django、pytest、完整 CI guard 和 Docker 配置检查；PR #5 远端 CI 已成功，后续审核机应补齐运行时以便独立复现。
2. 前端构建仍有非阻断的大 chunk 观察项，非本后端分支合并阻断条件。

## 14. 是否建议合并开发A PR

结论：**PASS**。

建议合并开发A PR #5，前提是合并操作前 GitHub Actions 仍保持成功，且 PR diff 未新增真实凭据或真实平台接入。合并后，开发B必须基于新的 main 进行接口联调、构建和远端 CI 复核后再进入其合并审核。

