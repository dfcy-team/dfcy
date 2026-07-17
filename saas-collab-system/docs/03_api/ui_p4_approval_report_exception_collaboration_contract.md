# UI-P4 审批、报告、异常与协同合同

## 1. 范围与边界

UI-P4 只建设 tenant 内审批、报表导出审计、异常闭环，以及飞书/微信 Mock 回填。所有写操作均由后端校验 permission-specific data_scope、当前状态和幂等键；前端权限仅用于展示。外部回填不得直接改变业务状态，真实飞书、微信、平台和 RPA 均保持禁用。

## 2. 页面合同

| 页面 | 路径 | 查看权限 | 动作权限 |
|---|---|---|---|
| 审批中心 | `/workflow/approvals` | `workflow.approvals.view` | `workflow.approvals.review` |
| 审批详情 | `/workflow/approvals/{id}` | `workflow.approvals.view` | `workflow.approvals.review`、`workflow.approvals.withdraw` |
| 异常中心 | `/workflow/exceptions` | `workflow.exceptions.view` | `workflow.exceptions.manage` |
| 异常详情 | `/workflow/exceptions/{id}` | `workflow.exceptions.view` | `workflow.exceptions.manage` |
| 协同回填 | `/workflow/collaboration-events` | `workflow.collaboration.view` | `workflow.collaboration.confirm` |
| 报表导出 | `/reports/exports` | `reports.view` | `reports.export`、`reports.download` |

所有非公开路由必须登记；未登记路径默认拒绝。

## 3. API 合同

### 审批

- `GET /api/internal/workflow/approvals/`
- `POST /api/internal/workflow/approvals/mock/`
- `GET /api/internal/workflow/approvals/{id}/`
- `POST /api/internal/workflow/approvals/{id}/approve/`
- `POST /api/internal/workflow/approvals/{id}/reject/`
- `POST /api/internal/workflow/approvals/{id}/withdraw/`

状态机：`pending -> approved | rejected | withdrawn`。终态不可再次处理；申请人不得审批自己的申请。Mock 创建只生成占位审批，不执行采购、改价、刊登、清仓、财务或 RPA 动作。

### 异常闭环

- `GET /api/internal/workflow/exceptions/`
- `POST /api/internal/workflow/exceptions/mock/`
- `GET /api/internal/workflow/exceptions/{id}/`
- `POST /api/internal/workflow/exceptions/{id}/assign/`
- `POST /api/internal/workflow/exceptions/{id}/resolve/`
- `POST /api/internal/workflow/exceptions/{id}/close/`

状态机：`open -> assigned -> resolved -> closed`；`open`可直接进入`resolved`。关闭必须基于已解决状态。每个动作记录不可变审计事件。

### 协同 Mock 回填

- `POST /api/wechat/mock-callback/`
- `POST /api/feishu/mock-callback/`
- `GET /api/internal/workflow/collaboration-events/`
- `POST /api/internal/workflow/collaboration-events/{id}/confirm/`
- `POST /api/internal/workflow/collaboration-events/{id}/reject/`

回调请求头：`X-UI-P4-Tenant`、`X-UI-P4-Event-Id`、`X-UI-P4-Timestamp`、`X-UI-P4-Signature`。签名为 Mock 共享密钥对`tenant:event_id:timestamp:sha256(payload)`的 HMAC-SHA256；时间偏差不得超过 300 秒。tenant、channel、event_id 唯一；重复且载荷相同返回`duplicate`，重复但载荷不同返回409。有效回填仅进入`pending_confirmation`，必须由`workflow.collaboration.confirm`确认后才标记`confirmed`，且仍不写业务主数据。

### 报表导出与下载

- 保留`GET/POST /api/report/exports/`和`GET /api/report/exports/{id}/`
- 新增`POST /api/report/exports/{id}/download/`

下载只返回短期`placeholder://`引用和审计编号，不返回真实文件。必须重新校验tenant、data_scope、`reports.download`和敏感字段策略；每次下载尝试均记录审计。

## 4. data_scope 合同

- `all`允许访问本tenant全部资源。
- `custom.approval_types`限制审批类型。
- `custom.exception_modules`限制异常模块。
- `custom.collaboration_channels`限制`wechat`、`feishu`。
- 多角色scope取并集；同一custom scope内多个已配置维度取交集。
- 无有效scope时返回空集，不得默认放行。

## 5. 统一响应与错误

成功响应统一为`success/code/message/data`；列表使用`count/next/previous/results`。错误：400请求格式，401未认证，403权限/tenant/data_scope不足，404资源不可见，409状态/幂等冲突，422业务规则失败。

## 6. 安全与审计

- 不保存或返回真实Token、Cookie、Session、API密钥或平台账号。
- 审批、异常、协同确认和报表下载均记录actor、tenant、动作、前后状态、脱敏详情和时间。
- Webhook日志只保存载荷哈希与脱敏摘要。
- 外部回填、报告、异常或审批不得触发真实RPA、采购、改价、清仓、上下架、付款、转账或提现。
- Mock签名密钥仅用于测试，默认值不得用于生产；生产协同接入继续禁用并需专项评审。
