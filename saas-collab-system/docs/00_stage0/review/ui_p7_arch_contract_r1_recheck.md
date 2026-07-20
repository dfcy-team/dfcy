# UI-P7-ARCH-CONTRACT-R1 治理与受控试点合同前审报告

## 1. 审核对象

- 审核任务：`UI-P7-ARCH-CONTRACT-R1`。
- 审核日期：2026-07-17。
- 审核分支：`feature/ui-p7-governance-pilot-readiness`。
- 审核基线：`17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`（UI-P6 merge commit，与 `origin/main` 一致）。
- 审核材料：UI-P7 范围、API合同、总接口映射、验收清单、进入说明、合同冻结报告、`deploy/pilot/` 及当前 `backend/`、`frontend/`、`rpa-agent/` 实现。
- 审核性质：独立合同前审，只生成本报告，不修改合同或业务代码。

## 2. 审核结论

**CONDITIONAL_PASS**

未发现 P0，但发现 3 项 P1：能力状态缺少实现证据且存在自相矛盾、逐端点请求/响应合同不足、恢复与发布审批状态流转未冻结。上述问题会造成开发A/B独立实施时路径虽一致但字段、错误和状态变更行为不一致，必须整改并通过 R2 后方可进入 UI-P7 实施。

## 3. 分支与修改范围

- 当前分支 HEAD 与 `origin/main` 均为 `17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`，满足基于 UI-P6 merge commit 的要求。
- 本次 UI-P7 计划修改位于 `docs/00_stage0/`、`docs/01_architecture/`、`docs/03_api/`、`docs/05_test/`、`docs/06_release/`。
- 未发现 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/`、`deploy/`、环境文件或依赖配置被 UI-P7 合同任务修改。
- 工作区中的无关 DOCX 不属于本次合同审核对象，保持未处理且不得纳入后续提交。
- `git diff --check` 未发现空白错误，仅报告 Windows 换行转换提示。

## 4. 页面与信息架构

- 已覆盖 API治理、智能体占位、试点就绪、双主机拓扑、备份恢复、灰度回滚和容量观测七个工作面。
- 平台准入、安全运维和操作审计明确复用现有页面，未重复创建同义页面。
- 页面职责保持查看、登记计划、记录外部受控执行结果和展示脱敏证据，不包含 Web shell、数据库控制台、真实凭据录入或资金操作页面。
- 路由、按钮、详情继承权限和未登记路由默认拒绝已纳入验收，但尚无 UI-P7 前端实现证据，当前只能作为待实施合同。

## 5. API合同

- 新路径集中在 `/api/internal/governance/*` 和 `/api/internal/pilot/*`，未发现与当前代码中既有路径重复。
- 通用响应、列表分页及 400/401/403/404/409/422 语义已定义；非统一 HTTP 200 必须视为 `INVALID_API_RESPONSE`，不得标记 `connected`。
- 恢复、发布端点只允许登记计划和记录外部执行结果，未设计直接执行 shell、Docker、SQL、部署、恢复或回滚的 Web 端点。
- 当前仓库未发现 UI-P7 URL、view、permission、前端 API 或 Mock handler 实现，因此所有状态必须以“尚未实现”为事实基线。
- 逐端点字段、类型、枚举、必填/可选、分页边界和动作请求合同不足，详见 P1-002。

## 6. 权限与data_scope

- 已按 `governance.api.*`、`governance.assistants.*`、`pilot.readiness.*`、`pilot.topology.*`、`pilot.recovery.*`、`pilot.release.*`、`pilot.capacity.*` 区分查看与动作权限。
- external、RPA 和没有精确权限的普通 internal 用户默认拒绝；前端可见性不替代后端授权。
- permission-specific data_scope 已定义允许 key，并明确 `ALL`、无/空 scope、未知 key、非法值、`OWN/DEPARTMENT`、列表/详情/请求体越权语义。
- system scope 不得返回 tenant 业务明细；tenant 引用要求脱敏并按 exact permission scope 过滤。
- 当前代码中未发现上述权限码或过滤器实现，故权限测试仍属于实施验收项，不能以合同文本证明已生效。

## 7. 状态机与审计

- 已列出试点门禁、恢复计划、发布计划、智能体占位及能力证据状态集合。
- 合同要求状态变化经服务层并写不可变审计，也禁止 UI-P7 新增审计修改/删除端点。
- 恢复和发布状态仅有状态枚举，没有冻结逐状态合法迁移、触发事件、执行权限、前置条件、审批分离和冲突响应；现有端点也未覆盖完整审批/调度流，详见 P1-003。
- `connected`、`degraded`、`stale` 的总原则清楚，但部分初始 `mock` 状态无实现证据，详见 P1-001。

## 8. 双主机与网络边界

- 合同明确数据库主机运行 MySQL，应用主机运行 Nginx、Django、Celery 和 Redis；MySQL、Redis、broker、管理端口不得暴露公网。
- 当前应用 Compose 将后端映射到 `127.0.0.1`，Redis未映射宿主机端口，外部流量由 Nginx 进入，符合目标边界。
- 页面不得展示完整 IP、密码、连接串、代理或备份秘密；新文档未发现真实主机地址或真实凭据。
- `deploy/pilot/database/` 保留的单机 Docker 模板同时包含 MySQL 和 Redis，而两机 README 明确该目录不用于正式两机部署；存在轻微运维误用风险，列为 P2。

## 9. 备份恢复与回滚

- 已覆盖 RPO、RTO、备份摘要、校验、审批、观察窗口、停止条件、回滚点及脱敏证据引用。
- 实际恢复、发布和回滚要求在受控主机人工执行，Web API 只回写结果。
- 禁止未经批准的 `reset --hard`、数据删除和卷删除，高风险业务能力不进入灰度范围。
- 仍需补齐审批、调度、执行结果、失败、人工接管、取消和回滚的合法迁移矩阵及接口触发合同。

## 10. 智能体占位边界

- 智能体仅允许 demo/placeholder 能力声明、数据分类、工具白名单和固定示例评估。
- 明确禁止真实 AI provider、真实 API Key、网络工具、业务数据库写入和 RPA 触发。
- 输出要求包含来源、置信度、限制及 `human_confirmation_required=true`，不得成为权限或业务结论。
- 当前不存在智能体页面/API/Mock handler，实现状态不得提前视为 `mock` 已可用。

## 11. 低风险灰度与容量

- 灰度范围限定 demo tenant 和只读/低风险能力，自动采购、库存变更、刊登、改价、清仓、上下架、RPA 和资金动作均排除。
- 容量合同覆盖 CPU、内存、请求、队列、数据库连接、来源、质量和更新时间；缺失值不补零，过期证据标记 `stale`。
- 停止条件只产生阻断或回滚需要，不由页面直接执行回滚。
- `stale` 的有效期由字段表达，但尚未按门禁/指标冻结默认 TTL 与失效规则，列为 P2。

## 12. 测试与验收

- 验收清单覆盖路由、按钮、统一响应、分页、错误状态、tenant/system scope、权限、data_scope、状态机、审计、双主机网络、恢复、回滚、容量、浏览器 E2E、Docker、RPA JSON、安全扫描和 CI。
- 已实际执行：分支/基线核验、修改范围扫描、UI-P7 路径与权限实现扫描、路径重复扫描、固定高风险密钥模式扫描、主机/连接串模式扫描、Compose端口边界静态核对及 `git diff --check`。
- 未执行 Django check、迁移检查、pytest、npm 测试/构建、Docker Compose 解析和浏览器 E2E。原因：本次为合同前审，仓库中尚无 UI-P7 实现；这些命令不能证明当前合同缺口已关闭，应在合同 R2 通过后的实现复审中实际执行并记录。
- 未伪造任何运行结果，既有 UI-P6/主分支 CI 也未被当作 UI-P7 验收证据。

## 13. 安全扫描

- 固定模式扫描未发现私钥头、GitHub Token、OpenAI风格密钥、AWS Key 或 Google API Key。
- UI-P7 文档未发现真实 IP、连接串、密码、Token、Cookie、Session、API Key、API Secret、真实平台配置或真实业务/财务数据。
- 未发现真实平台、银行、支付、AI provider 或真实 RPA 连接设计。
- 未发现自动采购、改库存、刊登、改价、清仓、停售、归档、付款、转账或提现入口。

## 14. P0

无。

## 15. P1

| 编号 | 问题 | 证据 | 整改要求 |
|---|---|---|---|
| UI-P7-CONTRACT-P1-001 | 未实现能力的 `mock` 状态缺少证据且合同自相矛盾 | API合同第5行声明全部新端点未实现，只有名称含 `mock` 的端点允许固定示例；但 assistants 列表/详情在合同第36-37行、范围第15-16行和总映射第12-13行均标记 `mock`。仓库扫描未发现任何 UI-P7 前后端或 Mock handler 实现，`check-mock/evaluate-mock/verify-mock` 也仅为规划路径。 | 未实现端点统一标记 `pending` 或明确的 `pending（planned mock）`；只有存在可执行 Mock handler、测试和证据后才标记 `mock`。assistants 列表/详情若要保持 mock，必须明确数据来源、handler位置和验收证据。不得标记 connected。 |
| UI-P7-CONTRACT-P1-002 | 逐端点请求、响应和校验合同不足，无法独立实施和构造错误测试 | API合同第24-81行仅给出摘要。未逐端点冻结查询参数、字段类型、枚举、nullability、必填/可选、默认分页与最大 page_size；创建恢复/发布计划及 record-result/record-rollback/check-mock/evaluate-mock/verify-mock 的请求字段和响应字段不完整。第20行“对象版本、原因和审批引用（如适用）”无法判定各端点具体要求。 | 为每个端点补充字段级请求/响应表、允许参数、字段类型/枚举/nullability、分页上限、必需 header、幂等与版本规则、审批引用适用性、禁止敏感字段，以及对应 400/403/404/409/422 条件。 |
| UI-P7-CONTRACT-P1-003 | 恢复与发布审批状态机未冻结合法迁移和防绕过机制 | API合同第62、74行仅列状态并笼统要求服务层变更；端点表没有提交审批、批准、排期、开始、取消或转人工的完整触发合同，也未定义 actor permission、职责分离、前置门禁、from/to、审计字段和冲突响应。开发可能通过通用 PATCH/save 绕过审批。 | 增加恢复/发布合法迁移矩阵，逐项冻结触发事件、源/目标状态、exact permission、审批人与创建人分离、门禁/版本前置条件及 409/422；明确禁止通用状态 PATCH、直接 model save 和审计修改/删除，并规定仅服务层或专用动作端点可迁移。 |

## 16. P2

| 编号 | 观察项 | 建议 |
|---|---|---|
| UI-P7-CONTRACT-P2-001 | `masked_endpoint` 只声明脱敏，未冻结具体显示规则。 | 仅允许服务别名、主机角色和网络区；明确禁止完整 IP、端口、DNS、连接串及代理信息，并补字段测试。 |
| UI-P7-CONTRACT-P2-002 | readiness/capacity 使用 `expires_at`、`stale`，但未按 gate/metric 冻结默认 TTL、时钟来源和过期降级规则。 | 在实施前给出门禁和指标的有效期表，统一 UTC 时间、刷新责任人及过期后阻断/降级语义。 |
| UI-P7-CONTRACT-P2-003 | `deploy/pilot/database/` 的遗留单机模板含 Redis，而两机拓扑要求 Redis 位于应用主机。 | 保留模板时增加醒目禁用标识或静态检查，防止两机试点误启用数据库目录中的 Redis；不在本次前审修改部署文件。 |

## 17. 是否允许进入UI-P7实施

**暂不允许。**

当前仅允许整改合同文档。关闭 UI-P7-CONTRACT-P1-001 至 P1-003 后，应执行独立 `UI-P7-ARCH-CONTRACT-R2`。R2 达到 PASS 后，方可开始 UI-P7 后端模型、前端页面和 Mock/受控验证实施；该放行仍不代表允许真实平台、真实 AI provider、真实 RPA、生产发布或任何高风险自动化。
