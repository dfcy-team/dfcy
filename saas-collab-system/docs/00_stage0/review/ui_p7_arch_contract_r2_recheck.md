# UI-P7-ARCH-CONTRACT-R2 治理与受控试点合同复审报告

## 1. 复审对象

- 任务：`UI-P7-ARCH-CONTRACT-R2`。
- 日期：2026-07-17。
- 分支：`feature/ui-p7-governance-pilot-readiness`。
- 基线：`17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`，与 `origin/main` 一致。
- 原结论：`UI-P7-ARCH-CONTRACT-R1 = CONDITIONAL_PASS`。
- 原问题：UI-P7-CONTRACT-P1-001、P1-002、P1-003。
- 复审性质：独立合同复审，只生成本报告，不修改合同或业务代码。

## 2. 复审结论

**CONDITIONAL_PASS**

原 P1-001 已关闭；原 P1-002、P1-003 仍各有一处关键缺口。当前无 P0，但仍有 P1，不能进入 UI-P7 实施。

## 3. 分支与修改范围

- 当前 HEAD 与 `origin/main` 均为 UI-P6 merge commit `17fc2a2`，符合 UI-P7 合同分支基线。
- UI-P7 变更位于允许的 `docs/00_stage0/`、`docs/01_architecture/`、`docs/03_api/`、`docs/05_test/` 和 `docs/06_release/`。
- 未发现 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/`、`deploy/`、环境文件或依赖配置被本轮合同任务修改。
- 无关 DOCX 保持未处理，不属于本轮复审或后续提交范围。

## 4. 原P1关闭情况

| 原P1编号 | 原问题 | 是否关闭 | 独立证据 | 备注 |
|---|---|---|---|---|
| UI-P7-CONTRACT-P1-001 | 未实现能力的 mock 状态缺少实现和测试证据 | 是 | 当前仓库扫描未发现 UI-P7 实现；合同、范围和总映射均将能力保持为 pending，三个 Mock计划端点为 `pending（planned mock）`；35个端点无 mock/connected 提前标记 | 状态升级已要求 handler、自动化、真实会话、联调和验收证据 |
| UI-P7-CONTRACT-P1-002 | 逐端点请求、响应、分页及校验字段未精确冻结 | 否 | 已补充通用字段、公共模型、分页、header、幂等、逐端点请求/data和错误语义；但 `ApiContractDetail` 仍使用未定义结构的 `request_fields:object[]`、`response_fields:object[]`、`error_codes:object[]`、`change_history:object[]` | 无法据此生成稳定 serializer/schema 或构造字段级兼容性测试，详见 P1-001 |
| UI-P7-CONTRACT-P1-003 | 恢复与发布审批状态机缺少合法迁移矩阵和防绕过约束 | 否 | 已增加专用动作、迁移矩阵、职责分离、防直接save/update/delete及不可变审计；但回滚阶段 manual_required 的 resume 使用 `pilot.release.record`，且“已批准回滚”的审批来源/引用未冻结 | 破坏 record/rollback 独立权限边界，详见 P1-002 |

## 5. 状态证据复审

- 实际扫描 `backend/` 和 `frontend/`，未发现 UI-P7 URL、view、permission、页面、API或Mock handler。
- API合同中共识别 35 个唯一 method/path 组合，无重复；35项均为 pending，其中 planned mock 仅作为计划状态。
- 总接口映射 UI-P7 节未发现 `mock` 或 `connected` 提前标记。
- `mock/sandbox/connected/degraded/stale` 的升级条件包含 handler、固定数据、自动化、真实会话、联调、权限/data_scope和CI证据。
- 原 P1-001 关闭。

## 6. 逐端点合同复审

已确认：

- 对象/列表统一响应及失败结构明确。
- `page=1`、`page_size=20`、最大100及非法分页400明确。
- POST要求 `Idempotency-Key`；既有对象动作要求 `version` 和 `reason`。
- 35个端点均登记方法、唯一完整路径、exact permission、查询/请求、data和当前状态。
- 400/401/403/404/409/422及具体code足以覆盖大部分端点测试。
- nullable字段、主要枚举、禁止字段和scope值格式已补充。

仍未关闭：

- `ApiContractDetail` 的四类嵌套对象仅声明为 `object[]`，未定义每项字段、类型、必填性、排序和兼容性语义。
- API治理详情正是前端展示请求/响应字段和错误合同的核心数据源；该缺口会使开发A serializer与开发B字段映射继续各自解释。

## 7. 状态机与审计复审

已确认：

- recovery/release 已提供 submit-review、approve、reject、schedule、start、resume、cancel及结果动作。
- from/to、exact permission、版本、幂等、门禁、职责分离和终态已写入迁移矩阵。
- 通用 PUT/PATCH/DELETE 和任意status更新端点被禁止。
- 合同要求模型/manager阻止直接save、QuerySet update/delete、admin、信号和批处理绕过。
- 成功与失败动作均要求写不可更新、不可删除、关联删除受保护的审计事件。

仍未关闭：

- `manual_context=rollback` 时，`resume` 从 manual_required 返回 rollback_required，但端点和矩阵要求 `pilot.release.record`，不是独立的 `pilot.release.rollback`。
- permission-specific data_scope 又明确 record/rollback不能互相继承，两个条款发生冲突。
- `record-rollback` 的前置条件写“已批准回滚”，但请求体、ReleasePlan模型和迁移矩阵未明确该批准来自原发布审批还是独立 `rollback_approval_ref`，也未冻结验证规则。

## 8. 权限与data_scope复审

- external、RPA和无精确权限的普通 internal 默认拒绝。
- governance/pilot 按动作拆分权限，允许scope key及值格式已冻结。
- `ALL`、空/未知/非法scope、OWN/DEPARTMENT、列表/详情/请求体越权语义明确。
- review、record、rollback声明为独立计算，不能继承view/plan。
- 除回滚人工恢复路径外，权限与迁移矩阵总体一致。

## 9. Web执行与高风险边界

- 恢复、发布和回滚 API 只登记计划与受控主机外部执行结果。
- 未设计shell、Docker、SQL、备份、恢复或部署执行API。
- 禁止真实AI provider、BigSeller、Shopee、TikTok/TK、银行和支付接入。
- 禁止自动采购、库存修改、刊登、改价、清仓、上下架、RPA和资金操作。
- 审批通过不等于生产或外部平台授权。

## 10. 静态检查与未执行项

实际执行：

- 分支、HEAD、`origin/main`和修改范围核验。
- UI-P7实现、权限码和Mock handler扫描。
- 35个method/path唯一性及状态扫描。
- Markdown合同表格结构检查，11组表格结构一致。
- 禁止修改路径、固定密钥、私钥头、真实内网地址、连接串和平台配置扫描。
- `git diff --check`，仅存在Windows换行转换提示，无空白错误。

未执行：

- Django check、迁移、pytest、npm测试/构建、Docker Compose和浏览器E2E未执行。原因是本轮只复审合同，当前无UI-P7实现；这些命令不能替代合同缺口判断，应在合同PASS后的实现复审中实际运行。

## 11. 安全扫描结果

- 未发现真实`.env`、密码、Token、Cookie、Session、API Key、API Secret、私钥或证书。
- 未发现真实主机IP、代理、数据库/Redis连接串、备份正文或备份秘密。
- 未发现真实平台、银行、支付、AI provider或真实RPA连接。
- 未发现高风险自动化被放行。

## 12. P0

无。

## 13. P1

| 编号 | 问题 | 风险 | 整改标准 |
|---|---|---|---|
| UI-P7-CONTRACT-R2-P1-001 | `ApiContractDetail` 的 `request_fields/response_fields/error_codes/change_history` 仍为未定义 `object[]` | 前后端无法共享字段级schema，兼容性与错误展示测试不可复现，原P1-002未完全关闭 | 为四类数组分别定义item schema：字段名、类型、required、nullable、enum/约束、description；error包含http/code/condition；history包含version/change_type/changed_at/owner/deprecation_at，并冻结排序和空值语义 |
| UI-P7-CONTRACT-R2-P1-002 | 回滚人工接管resume使用record权限，且回滚批准来源未冻结 | 仅有record权限的用户可能推进回滚工作流，违反rollback独立授权；无法验证“已批准回滚”，原P1-003未完全关闭 | `manual_context=rollback` 使用独立rollback动作端点或要求 `pilot.release.rollback`；按该permission重新校验data_scope。明确原发布审批是否包含条件回滚授权，或新增 `rollback_approval_ref` 及校验/审计字段；补403/404/409/422及越权测试合同 |

## 14. P2

| 编号 | 观察项 | 建议 |
|---|---|---|
| UI-P7-CONTRACT-R2-P2-001 | `deploy/pilot/database/` 遗留单机模板仍含Redis，而两机拓扑将Redis置于应用主机 | 实施阶段增加禁用提示或静态检查，避免两机试点误用；本轮禁止修改deploy |
| UI-P7-CONTRACT-R2-P2-002 | 浏览器、双主机、恢复、回滚和容量证据尚未产生 | 合同PASS并实现后按验收清单实际执行，不得复用UI-P6证据代替 |

## 15. 是否允许进入UI-P7实施

**不允许。**

当前仅允许定向修复 UI-P7-CONTRACT-R2-P1-001 和 P1-002。修复后应执行独立 `UI-P7-ARCH-CONTRACT-R3`；只有无 P0/P1 且结论为 PASS，才允许进入 UI-P7 实施。即使合同通过，也不允许直接接入真实平台、真实AI、真实RPA、生产环境或高风险自动化。
