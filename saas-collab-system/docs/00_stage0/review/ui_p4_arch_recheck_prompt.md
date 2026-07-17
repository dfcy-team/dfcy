# UI-P4-ARCH-R1 架构复审提示

你现在在 `saas-collab-system` 中执行 UI-P4 独立架构复审。

任务编号：`UI-P4-ARCH-R1`

任务名称：审批、报表、异常与协同回填架构复审

本任务只审核、不修复，只允许创建：

- `docs/00_stage0/review/ui_p4_arch_r1_recheck.md`

禁止修改：

- `backend/`
- `frontend/`
- `rpa-agent/`
- `docs/04_rpa/`
- 配置、迁移和业务代码

## 1. 复审依据

- `docs/03_api/ui_p4_approval_report_exception_collaboration_contract.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/00_stage0/review/ui_p4_approval_report_exception_change_log.md`
- `docs/05_test/ui_p4_approval_report_exception_test_report.md`
- 本分支相对最新 `main` 的实际代码差异

不得复制变更日志或测试报告结论作为独立复审结果。

## 2. 页面、路由与权限合同

检查以下路径存在且采用显式路由合同、未登记非公开路径默认拒绝：

- `/workflow/approvals`
- `/workflow/approvals/{id}`
- `/workflow/exceptions`
- `/workflow/exceptions/{id}`
- `/workflow/collaboration-events`
- `/reports/exports`

确认菜单和页面动作同时受角色、route permission 和 action permission 约束；前端权限只用于展示，可信授权仍由后端执行。

## 3. 审批状态机

确认：

1. 审批查询按 tenant 和 `workflow.approvals.view` 的 data_scope 过滤。
2. 提交、通过、驳回、撤回分别使用对应动作权限。
3. 请求人不能审核自己的申请。
4. 仅待审状态可通过或驳回，仅请求人可撤回自己的待审申请。
5. 重复请求具备幂等或 409 冲突语义。
6. 审批通过只形成授权结果，不直接执行采购、改价、清仓、RPA 或资金操作。

## 4. 异常状态机

确认异常查看、分配、解决和关闭按 tenant、data_scope 与动作权限执行；状态流转非法时返回 409/422；external 和 RPA 用户不能访问 internal 异常管理接口；每次变更均写入审计事件。

## 5. 协同回填安全

检查微信/飞书接口仅为 Mock 回调，并确认：

1. 使用 HMAC 或等价签名校验。
2. 时间窗不超过合同约定，过期请求被拒绝。
3. `event_id` 或等价键阻止重放。
4. 日志和响应不泄露签名、Token、Cookie、Session 或完整敏感 payload。
5. 回调只写协同事件，不直接改写审批、财务、RPA 或业务状态。
6. 人工确认/驳回需 `workflow.collaboration.confirm`。
7. production 配置强制关闭真实执行。

## 6. 报表导出与下载审计

确认创建导出和申请下载分别使用 `reports.export`、`reports.download`；下载时重新校验 tenant、owner、data_scope 和报表权限；未完成导出不能下载；下载引用短期、占位且不可作为真实对象存储凭据；下载动作有不可篡改审计。

## 7. 审计不可变性

检查工作流审计是否拒绝普通 update/delete/bulk update；审批、异常、协同确认和报表下载是否记录操作者、tenant、动作、对象、时间和必要上下文，且不记录真实凭据。

## 8. 前端状态与离线边界

确认页面具备 loading、error、empty、list/detail 和分页状态；读取失败仅在允许条件下回退 Mock；401/403/404/409/422 不得伪装为成功或 connected；Mock 写操作默认拒绝；只有实际 API 成功才可标记 connected。

## 9. 实际测试

环境允许时独立运行并记录：

- Django check
- migration 一致性检查
- UI-P4 专项 pytest
- 全量 pytest
- UI-P4 专项 Vitest
- 全量 Vitest
- `npm run build`
- Docker Compose 配置检查
- RPA JSON 校验
- API 路径、真实平台连接和密钥扫描
- 1440 x 900 与 390 x 844 浏览器页面验证

未执行项必须记录原因，不得伪造。

## 10. 安全边界

确认无真实微信/飞书/BigSeller/Shopee/TikTok 接入，无真实账号、密码、Token、Cookie、Session、API Key、API Secret 或真实业务数据；无自动采购、自动清仓、自动改价、真实 RPA、付款、转账或提现。

## 11. 报告结构

# UI-P4-ARCH-R1 审批、报表、异常与协同回填复审报告

## 1. 复审对象
## 2. 复审结论
## 3. 页面与路由合同
## 4. tenant、data_scope 与权限
## 5. 审批状态机
## 6. 异常状态机
## 7. 协同回填安全
## 8. 报表导出与下载审计
## 9. 审计不可变性
## 10. 前端状态与离线边界
## 11. 测试、构建与浏览器验证
## 12. 安全扫描
## 13. P0
## 14. P1
## 15. P2
## 16. 是否建议 UI-P4 收尾

结论规则：有 P0 为 `FAIL`；无 P0 但有 P1 为 `CONDITIONAL_PASS`；无 P0/P1 为 `PASS`。
