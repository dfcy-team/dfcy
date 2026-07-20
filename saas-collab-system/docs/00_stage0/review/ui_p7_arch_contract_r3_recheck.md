# UI-P7-ARCH-CONTRACT-R3 独立复审报告

## 1. 复审对象

- 任务：`UI-P7-ARCH-CONTRACT-R3`。
- 日期：2026-07-17。
- 分支：`feature/ui-p7-governance-pilot-readiness`。
- 基线：`17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`，与 `origin/main` 一致。
- 原结论：`UI-P7-ARCH-CONTRACT-R2 = CONDITIONAL_PASS`。
- 复审范围：R2 遗留 `UI-P7-CONTRACT-R2-P1-001`、`UI-P7-CONTRACT-R2-P1-002` 及其关联端点、权限、状态机、验收和安全边界。
- 复审性质：独立合同复审；本次只新增本报告，不修改合同或业务代码。

## 2. 复审结论

**PASS**

两项 R2 P1 均已关闭。未发现新增 P0 或 P1；现存 P2 为实施阶段证据和遗留部署模板观察项，不阻断 UI-P7 按已冻结合同进入实现。

## 3. R2 P1 关闭情况

| 原P1编号 | 问题 | 是否关闭 | 独立证据 | 结论 |
|---|---|---|---|---|
| UI-P7-CONTRACT-R2-P1-001 | `ApiContractDetail` 四类数组为未定义 `object[]` | 是 | `ApiContractDetail` 已引用 `RequestFieldSpec`、`ResponseFieldSpec`、`ApiErrorSpec`、`ContractChangeEntry`；合同第3.1节分别登记14、8、5、6个字段，并逐字段冻结类型、required、nullable、枚举/约束和语义 | 字段级 schema、排序、空值与组合规则可直接生成 serializer/schema 和自动化测试 |
| UI-P7-CONTRACT-R2-P1-002 | 回滚人工恢复使用 record 权限且回滚批准来源未冻结 | 是 | `resume` 仅处理 `manual_context=release` 并要求 `pilot.release.record`；`approve-rollback`、`resume-rollback`、`record-rollback` 均要求 `pilot.release.rollback`；ReleasePlan 保存批准引用、批准人、批准时间和失效时间 | 回滚权限、批准来源、有效期、职责分离和审计边界已独立冻结 |

## 4. ApiContractDetail 与 item schema

- 合同中未再出现 `request_fields:object[]`、`response_fields:object[]`、`error_codes:object[]` 或 `change_history:object[]`。
- `RequestFieldSpec` 共14个字段，覆盖字段位置、类型、目标字段 required/nullable、枚举、数组 item、对象 schema、长度、数值、正则和说明。
- `ResponseFieldSpec` 共8个字段，覆盖字段路径、类型、目标字段 required/nullable、枚举、数组 item、对象 schema 和说明。
- `ApiErrorSpec` 共5个字段，覆盖 HTTP 状态、错误码、触发条件、字段路径和可重试语义。
- `ContractChangeEntry` 共6个字段，覆盖版本、变更类型、摘要、变更时间、责任方和弃用时间。
- 四类 item 的 schema 字段自身均明确 required/nullable；未知字段固定为 `422 SCHEMA_FIELD_UNKNOWN`。
- 排序分别按 location/name、field_path、http_status/code、changed_at/version 冻结。
- 无枚举时返回空数组，不适用的约束返回 null；`type/item_type/schema_ref` 组合规则可直接测试。

## 5. 端点、状态和 Mock 证据

- 静态识别37个唯一 method/path 组合，即35项原端点加 `approve-rollback`、`resume-rollback` 两项回滚专用端点。
- 重复 method/path：0。
- 37项端点均保持 `pending`；其中3项计划 Mock 为 `pending（planned mock）`。
- 总接口映射未把 UI-P7 能力标记为 `mock` 或 `connected`。
- 扫描 `backend/`、`frontend/`、`rpa-agent/` 未发现 UI-P7 handler、页面、权限码或 Mock 实现；当前状态与证据一致。

## 6. 发布与回滚状态机

- 发布 `resume` 仅允许 `manual_required + manual_context=release -> running`，exact permission 为 `pilot.release.record`。
- 回滚使用独立 `approve-rollback`、`resume-rollback`、`record-rollback`，exact permission 均为 `pilot.release.rollback`。
- 每个动作重新读取当前 exact permission 的 data_scope；`review`、`record`、`rollback` 不互相继承或合并 scope。
- 原发布审批明确不自动授权回滚；进入 `rollback_required` 时清空旧回滚批准。
- 回滚批准保存 `rollback_approval_ref`、`rollback_approved_by_id`、`rollback_approved_at`、`rollback_approval_expires_at`。
- ref不匹配、过期、重新批准、离开/重新进入 `rollback_required`，以及 commit/tag/rollback_point 变化均有明确失效语义。
- 过期返回 `422 ROLLBACK_APPROVAL_EXPIRED`，ref无效返回 `422 ROLLBACK_APPROVAL_INVALID`，失败请求不得推进状态。

## 7. 职责分离与不可变审计

- 发布审批人与计划创建人分离。
- 回滚批准人不得是计划创建人、发布审批人或回滚结果记录人。
- 回滚结果记录人不得是回滚批准人，且不得修改原审批结论。
- 通用 PUT/PATCH/DELETE、直接 status save/update、admin、信号和批处理绕过均被合同禁止。
- 状态迁移必须在事务和行锁内校验 tenant/system scope、exact permission、data_scope、版本、幂等、职责分离和门禁。
- 成功、失败、替换和过期拒绝均写不可更新、不可删除的审计记录，审计字段包含 `rollback_approval_ref`。

## 8. 错误、并发与越权测试合同

- 400/401/403/404/409/422 及统一错误响应已冻结。
- 所有 POST 动作要求 `Idempotency-Key`；既有对象动作要求 `version` 和 `reason`。
- 非法状态、版本冲突和幂等冲突返回409；字段、门禁、审批或职责分离失败返回422。
- exact permission 或 permission-specific data_scope 不满足返回403；详情和审计资源按ID越权返回404。
- 验收清单已覆盖 schema 字段、未知字段、空值、分页、幂等、版本、状态冲突、回滚批准过期/不匹配、职责分离及403/404/409/422。

## 9. 权限与 data_scope

- UI-P7 端点拒绝 external 和 RPA 用户。
- governance 与 pilot 权限均为独立 exact permission，不由登录状态、其他模块权限或前端菜单替代。
- `ALL`、CUSTOM、无 scope、未知 key、非法值、OWN/DEPARTMENT 以及列表/详情/请求体越权语义已冻结。
- 回滚三个动作按 `pilot.release.rollback` 独立计算 `environment_ids/release_plan_ids/release_channels`，不能复用 record、review、plan 或 view 的 scope。

## 10. Web执行与高风险边界

- 恢复、发布和回滚接口只登记计划、批准及受控主机外部执行结果，不执行 shell、Docker、SQL、备份、恢复、部署或回滚命令。
- 未设计 Docker socket、数据库端口、Web shell、备份正文、连接串或主机命令入口。
- 继续禁止真实 AI、BigSeller、Shopee、TikTok/TK、银行、支付和真实 RPA 接入。
- 继续禁止自动采购、库存修改、刊登、改价、清仓、上下架、付款、转账或提现。
- 合同 PASS 不代表允许真实平台、生产环境或高风险自动化。

## 11. 静态检查与未执行项

实际执行：

- 分支、HEAD、`origin/main` 和工作区范围核验。
- 四类 item schema 定义与字段行数检查：14/8/5/6。
- Markdown 合同表格结构检查：13组表格，结构错误0。
- method/path 唯一性与状态检查：37项、唯一37项、pending 37项。
- UI-P7 backend/frontend/rpa-agent 实现扫描。
- 权限、data_scope、状态机、批准失效、错误码和验收条目扫描。
- 私钥、连接串、固定密钥、真实IP和平台配置快速扫描，未命中。
- `git diff --check`：无空白错误；仅有 Windows LF/CRLF 转换提示。

未执行：

- Django check、迁移、pytest、npm测试/构建、Docker Compose和浏览器E2E未执行。原因是本轮为合同复审，UI-P7尚无实现；这些命令不能替代合同判断，应在UI-P7实现复审时实际运行并保留证据。

## 12. 安全扫描结果

- 未发现真实 `.env`、密码、Token、Cookie、Session、API Key、API Secret、私钥或证书。
- 未发现真实主机IP、数据库/Redis连接串、备份正文、平台凭据或真实业务数据进入UI-P7合同材料。
- 未发现真实平台连接、Web执行命令或高风险自动化被放行。
- 无关 DOCX 保持未处理，不属于本次复审输出范围。

## 13. P0

无。

## 14. P1

无。R2遗留两项P1均已关闭。

## 15. P2

| 编号 | 观察项 | 建议 |
|---|---|---|
| UI-P7-CONTRACT-R3-P2-001 | `deploy/pilot/database/` 遗留单机模板仍含 Redis，而目标双主机拓扑将 Redis 放在应用主机 | UI-P7实施阶段增加静态门禁或禁用说明；本次合同任务禁止修改deploy |
| UI-P7-CONTRACT-R3-P2-002 | 浏览器、双主机、备份恢复、灰度回滚和容量证据尚未产生 | 实现完成后按验收清单实际执行，不得复用UI-P6证据替代 |

## 16. 是否允许进入 UI-P7 实施

**允许。**

UI-P7 可依据已冻结合同进入实现、Mock/dry-run、页面和测试阶段。实现仍须经过独立架构复审，且只能使用示例数据和受控内网试点边界。

本次 PASS 不允许直接接入真实平台、真实 AI、真实 RPA、生产环境或高风险自动化；相关能力仍须单独完成安全、凭据托管、试点、回滚和生产准入评审。
