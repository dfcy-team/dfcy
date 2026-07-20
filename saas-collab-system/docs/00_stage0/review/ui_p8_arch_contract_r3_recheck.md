# UI-P8-ARCH-CONTRACT-R3 独立合同复审报告

## 1. 复审对象与基线

- 复审分支：`feature/ui-p8-production-pilot-security-readiness`
- 当前 HEAD：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- `origin/main` 共同基线：`30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 原报告：`ui_p8_arch_contract_r2_recheck.md`
- 整改记录：`ui_p8_contract_r2_p1_fix_change_log.md`
- 复审依据：UI-P8 scope、API 合同、验收清单、总映射和进入说明。

本次仅新增本复审报告，未修改合同或业务代码。无关 DOCX 与 `docs/00_stage0/architecture/` 未纳入审核范围，后续提交仍须排除。

## 2. 复审结论

**PASS**

R2 的 3 项 P1 已全部关闭。未发现新增 P0/P1；保留 1 项不阻断 P2。UI-P8 页面、API、tenant、permission-specific data_scope、请求响应、状态机、过期、职责分离、证据审计和安全边界已经达到进入受控实现与测试阶段的合同条件。

## 3. 原P1关闭情况

| 原P1编号 | 原问题 | 是否关闭 | 证据 | 结论 |
|---|---|---|---|---|
| UI-P8-ARCH-CONTRACT-R2-P1-001 | PATCH 修改环境、owner 和 finance_scope 时目标授权不完整 | 是 | API合同第3.3、3.5、4.2和6节；验收第2节 | 目标环境、owner只读和财务目标scope规则唯一可测 |
| UI-P8-ARCH-CONTRACT-R2-P1-002 | 创建和结果字段精度不足 | 是 | API合同第2.1、6至9节；验收第6节 | required/nullability、数量、长度、格式、范围和跨字段关系已冻结 |
| UI-P8-ARCH-CONTRACT-R2-P1-003 | draft 到期和 entry decision 有效期未闭合 | 是 | API合同第6、9、11.1至11.2节；scope第5节；验收第3节 | draft 可达 expired，读写结果、审计和并发规则完整 |

## 4. PATCH目标授权属性

- PATCH 改变 environment 时同时要求目标资源 ID、原环境和目标环境均命中 exact plan permission 的 scope；目标越 scope 返回 403 且不写入。
- 环境迁移审计固定记录 `source_environment/target_environment`，并对目标环境重新校验全部资源引用。
- `owner_id` 由后端固定为创建 actor，是响应只读字段；POST/PATCH 均未登记该请求字段，按全局禁止字段规则返回 422。当前不存在未冻结 owner 转移入口。
- review_type 或 finance_scope 变化按修改后的目标组合重新执行 `finance.view` 和 platforms/currencies scope；离开 finance_boundary 必须显式清空 finance_scope。
- entry decision 的五类证据在环境变化后重新执行来源 view permission、scope、tenant 和 environment 校验。

原 P1-001 已关闭。

## 5. 请求与结果字段精度

- body 字段默认 required；optional/nullable 必须显式声明。PATCH 省略表示保持原值，显式 null 只允许用于 nullable 字段。
- 数组拒绝 null、空值和重复项；对象拒绝未知 key；字符串先 trim 再校验。
- target_alias 使用受控别名格式并要求 tenant/environment 注册，不接受 IP、主机名、URL 或连接串。
- success_criteria 已冻结 1 至 20 项、单项 1 至 500 字符和去重规则。
- verification 结果的 summary、时间、error code/message 已按 passed、failed、manual_required 分别冻结 required/nullability 和长度。
- performance 的 measured/manual_required、五项指标 nullability、数值范围及 `p50_ms <= p95_ms` 已冻结，最终 passed/failed 由后端阈值计算。
- security review 有效期固定在未来 180 天内；entry decision 固定在未来 30 天内；创建和 PATCH 使用相同校验。
- 违反上述字段规则统一可构造 422，未知或禁止字段使用 `FORBIDDEN_FIELD`，业务字段失败使用 `VALIDATION_ERROR`。

原 P1-002 已关闭。

## 6. draft、过期与职责分离

- 安全评审和准入决策均允许 `draft/submitted/approved -> expired`；其余矩阵外迁移返回 409。
- 定时任务和惰性过期调用同一 system 服务，使用事务、行锁、version 和不可变审计。
- GET/list/control-room 触发过期后返回 200 expired/stale；PATCH/submit/approve/reject 等写动作先提交过期事务，再返回 `409 STATE_CONFLICT`。
- 过期与人工 action 并发时只允许一个事务成功，另一方返回 409。
- 创建人不能批准自己的四类计划；验证和性能结果记录人不能是批准人；cancel 固定使用专用 permission，submitted/approved 不允许创建人取消。
- 通用 PATCH、模型 save、QuerySet update/delete、bulk、admin 和级联删除均不得绕过状态机或不可变审计。

原 P1-003 已关闭。

## 7. 安全与修改范围

- UI-P8 变更位于允许的 docs 范围，未发现 backend、frontend、rpa-agent、`docs/04_rpa/`、deploy、环境或依赖修改。
- 无真实平台、AI、银行、支付或真实 RPA 连接授权。
- 无 Shell、Docker、SSH、SQL、Redis、部署、恢复、回滚、网络或流量执行端点。
- 未允许自动采购、供应商通知、库存修改、刊登、改价、清仓、停售、归档或资金动作。
- pending、Mock、HTTP 200 和 `go` 均未被解释为 connected、已部署或已接入生产。
- 本轮为合同复审，未运行尚不存在的 UI-P8 Django、pytest、组件、build 或 E2E；这些必须在实现复审中实际执行并记录，不得以本次 PASS 替代。

## 8. P0

无。

## 9. P1

无。

## 10. P2

| 编号 | 问题 | 建议 |
|---|---|---|
| UI-P8-ARCH-CONTRACT-R3-P2-001 | scope_summary、result_summary、review_reason、cancel_reason 和错误说明仍属于自由文本 | 实现时增加敏感模式拒绝/脱敏和审计测试，防止凭据、完整内部地址或真实业务数据进入记录 |

该 P2 不阻断合同放行，但必须纳入 UI-P8 安全测试和实现复审。

## 11. 是否允许进入UI-P8实现

**允许。**

允许进入 UI-P8 后端模型/API、前端页面、Mock/sandbox、组件测试、权限矩阵、状态机、不可变审计和受限角色 E2E 实现阶段。

该 PASS 不允许真实平台接入、生产部署、真实凭据使用、主机执行或高风险自动化。UI-P8 实现完成后仍须执行独立实现复审，并以实际测试、构建和远端 CI 作为收尾依据。
