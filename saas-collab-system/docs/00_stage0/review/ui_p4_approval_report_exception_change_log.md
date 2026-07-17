# UI-P4 审批、报表、异常与协同回填变更日志

## 1. 实施目标

UI-P4 在 UI-P1 至 UI-P3 的登录、权限、页面骨架和 RPA 管理底座上，补齐审批中心、异常中心、报表导出下载审计，以及微信/飞书 Mock 协同回填。所有高风险动作继续由后端权限、状态机和人工确认约束，不直接触发采购、RPA、资金或真实平台操作。

## 2. 合同与映射

- 新增 `docs/03_api/ui_p4_approval_report_exception_collaboration_contract.md`，冻结页面、API、权限、状态机、响应、审计与安全边界。
- 更新 `docs/00_stage0/frontend_api_mapping.md`，登记审批、异常、协同回填和报表下载路径及当前状态。

## 3. 后端变更

- 新增 `backend/apps/workflows/`，包含审批单、业务异常、协同事件和不可变工作流审计事件。
- 新增审批提交、查看、通过、驳回和撤回状态机；请求人不得自审，终态不可重复处理。
- 新增异常查看、分配、解决和关闭流程；所有写操作生成审计事件。
- 新增微信/飞书 Mock 回调验签、时间窗校验、重放防护、敏感字段遮罩和人工确认边界。
- 报表导出补充下载授权：下载时重新校验 tenant、所有者、data_scope 与权限，并记录下载审计。
- 新增 UI-P4 权限码种子迁移和报表审计动作迁移。
- 生产配置强制关闭协同回调执行模式；阶段内不调用真实微信、飞书或其他平台。

## 4. 前端变更

- 新增审批列表/详情、异常列表/详情、协同回填列表页面。
- 新增工作流 API 与 Mock 数据；读取支持受控 Mock fallback，Mock 写操作默认拒绝。
- 报表导出页补充创建和下载权限控制、下载状态限制及占位引用提示。
- 路由与菜单采用显式登记和默认拒绝，动作按钮按后端 action permission 显示。
- 页面具备 loading、error、empty、list/detail 和分页解析。
- 异常列表支持“分配给我”、解决和关闭；协同事件支持人工确认或驳回。

## 5. 主要新增文件

- `backend/apps/workflows/`
- `backend/tests/test_ui_p4_workflow_collaboration.py`
- `frontend/src/api/workflow.js`
- `frontend/src/mock/workflow.js`
- `frontend/src/components/WorkflowDetailPage.vue`
- `frontend/src/views/workflow/`
- `frontend/tests/ui-p4-workflow-collaboration.spec.js`
- `docs/03_api/ui_p4_approval_report_exception_collaboration_contract.md`

## 6. 安全确认

- 未接入真实微信、飞书、BigSeller、Shopee 或 TikTok/TK。
- 未提交真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- Mock 回调采用 HMAC、时间窗和事件幂等校验，且不直接改写业务状态。
- 审批、异常和报表下载均按 tenant、data_scope 和动作权限校验。
- 未启用自动采购、自动清仓、自动改价、真实 RPA 或资金操作。

## 7. 待复审事项

由架构人员依据 `ui_p4_arch_recheck_prompt.md` 独立执行 `UI-P4-ARCH-R1`，不得以本变更日志替代实际代码、测试和安全复核。
