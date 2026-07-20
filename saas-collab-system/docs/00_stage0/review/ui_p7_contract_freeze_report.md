# UI-P7 治理与受控试点合同冻结报告

## 1. 冻结对象

- 阶段：UI-P7 治理与受控试点。
- 分支：`feature/ui-p7-governance-pilot-readiness`。
- 基线：UI-P6 PR #24 merge commit `17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`。
- 冻结日期：2026-07-17。
- 性质：仅冻结页面、API、权限、data_scope、状态、测试和发布边界，不修改业务代码。

## 2. 冻结文件

- `docs/01_architecture/ui_p7_governance_pilot_scope.md`
- `docs/03_api/ui_p7_governance_pilot_contract.md`
- `docs/05_test/ui_p7_governance_pilot_acceptance.md`
- `docs/06_release/ui_p7_entry_notes.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/00_stage0/review/ui_p7_arch_contract_recheck_prompt.md`

## 3. 页面冻结结果

冻结 API治理、智能体占位、试点就绪、双主机拓扑、备份恢复、灰度回滚和容量观测七个工作面；复用平台准入、安全运维和操作审计页面。未新增真实平台连接页、凭据录入页、Web shell 或资金操作页。

## 4. API冻结结果

- 新端点仅位于 `/api/internal/governance/*` 和 `/api/internal/pilot/*`。
- API治理使用 `api-contracts`；智能体占位使用 `assistants`。
- 恢复和发布端点只管理计划及结果记录，不执行主机命令。
- 列表保持统一分页；错误保持 400/401/403/404/409/422。
- 非统一 HTTP 200 响应不能标记 connected。
- 所有新端点当前为 pending；带 mock 的固定示例端点为 `pending（planned mock）`，在 handler、测试和证据齐备前不得标记 mock。
- 每个端点已冻结允许参数、请求体、响应模型、字段类型/枚举、分页上限、header、幂等、版本和错误语义；API合同详情四类嵌套item已具名并冻结字段、排序和空值规则。

## 5. 权限与data_scope冻结结果

- 冻结 `governance.api.*`、`governance.assistants.*`、`pilot.readiness.*`、`pilot.topology.*`、`pilot.recovery.*`、`pilot.release.*` 和 `pilot.capacity.*` 精确权限；恢复/发布单独增加 review，记录和回滚不继承 view/plan scope。
- external 和 RPA 全部拒绝；普通 internal 不因登录或 view 其他模块而默认获得试点权限。
- API治理、智能体、容量等模块分别冻结 scope key；未知 key 和非法值统一返回 `403 DATA_SCOPE_INVALID`。
- readiness、topology、recovery、release 同样按 exact permission 冻结 environment、gate、service、plan 和 channel scope key；`ALL`、无 scope、列表/详情/请求体越权语义已统一。
- system scope 不包含 tenant 业务明细；tenant 引用必须脱敏并按 scope 过滤。

## 6. 状态机冻结结果

- 试点门禁：`not_started/in_progress/passed/failed/blocked/expired`。
- 恢复计划：`draft/review_pending/approved/rejected/scheduled/running/success/failed/manual_required/cancelled`。
- 发布计划：`draft/review_pending/approved/rejected/scheduled/running/success/failed/rollback_required/rolled_back/manual_required/cancelled`。
- 智能体占位：`placeholder/review_pending/sandbox/disabled`，不允许 production/connected。
- 能力状态额外包含 stale，用于证据过期；stale 不得用于放行。
- 恢复和发布已冻结逐动作 from/to、exact permission、职责分离、版本/幂等/门禁前置条件及409/422语义。
- 发布人工恢复与回滚人工恢复使用不同端点和权限；回滚要求独立 approve-rollback、rollback approval ref 及批准/记录人员分离。
- 不提供通用状态 PATCH；直接save、QuerySet update/delete、admin或批处理绕过状态服务必须被拒绝，不可变审计采用保护语义。

## 7. 安全与高风险边界

- 不接入真实平台、真实 AI provider、银行或支付系统。
- 不提交或展示真实 `.env`、密码、Token、Cookie、Session、API Key、API Secret、私钥或备份密钥。
- 页面不直接执行部署、备份、恢复、回滚、Docker、SQL 或网络策略修改。
- 不自动采购、改库存、刊登、改价、清仓、停售、归档或资金操作。
- 智能体、预警、治理和容量检查不得触发真实 RPA。

## 8. 修改范围

本次仅新增或修改 `docs/01_architecture/`、`docs/03_api/`、`docs/05_test/`、`docs/06_release/` 和 `docs/00_stage0/` 文档。未修改 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/`、部署配置或环境示例。工作区中的无关 DOCX 未处理。

## 9. 当前结论

合同材料已完成 R2 遗留两项 P1 的定向整改，尚需独立 R3 确认。当前只允许文档级准备，不允许进入 UI-P7 业务实现、真实平台接入或试点放行。

## 10. 下一门禁

执行 `UI-P7-ARCH-CONTRACT-R3`。只有 R3 结论为 PASS 且无未关闭 P0/P1，才允许开始 UI-P7 实施。
