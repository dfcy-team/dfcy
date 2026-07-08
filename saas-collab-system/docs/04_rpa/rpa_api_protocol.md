# RPA Agent 与后端执行接口协议

本文档为阶段0接口契约说明，不实现后端接口代码，不实现 RPA 浏览器自动化脚本，不连接真实 BigSeller、Shopee、TK 或任何真实平台。

## 1. 总体边界

- RPA Agent 只能访问 `/api/rpa/*`。
- RPA 不得访问 `/api/finance/*`。
- RPA 不得访问 `/api/internal/finance/*`。
- RPA 不得访问 `/admin/`。
- RPA 不得直连 MySQL。
- RPA 不得直连 Redis。
- RPA 不得绕过后端直接写业务状态。
- RPA result 只回写执行结果，不做业务判断。
- RPA 不决定清仓、不决定补货、不决定是否上架。
- 高风险任务必须由后端审批通过后生成，RPA 只执行任务。

## 2. 状态流转

阶段1 RPA 任务状态必须覆盖：

- `pending`：任务已创建，等待领取。
- `claimed`：任务已被 Agent 领取。
- `running`：任务正在执行。
- `success`：任务执行成功。
- `failed`：任务执行失败。
- `retrying`：任务等待重试。
- `manual_required`：任务需要人工接管。
- `cancelled`：任务已取消。

推荐状态流转：

```text
pending -> claimed -> running -> success
pending -> claimed -> running -> failed -> retrying -> pending
pending -> claimed -> running -> manual_required
pending -> cancelled
claimed -> cancelled
running -> cancelled
```

## 3. 领取任务

- 接口用途：Agent 领取一个后端已分配且允许执行的 RPA 任务。
- 请求方法：`POST`
- 路径：`/api/rpa/tasks/claim/`
- 调用方：RPA Agent。
- 权限要求：仅允许具备 RPA Agent 身份的调用方访问。
- 请求字段：`agent_name`、`agent_version`、`capabilities`、`queue_key`。
- 返回字段：`task_id`、`task_type`、`business_type`、`business_id`、`payload`、`queue_key`、`status`。
- 状态流转：`pending` -> `claimed`。
- 失败处理：无可领取任务时返回空任务占位；鉴权失败时拒绝；队列冲突时不发放同账号任务。
- 禁止事项：禁止返回真实平台账号密码；禁止返回数据库连接信息；禁止返回财务后台数据。

## 4. 心跳上报

- 接口用途：Agent 上报任务仍在执行，供后端判断任务超时和运行状态。
- 请求方法：`POST`
- 路径：`/api/rpa/tasks/{id}/heartbeat/`
- 调用方：RPA Agent。
- 权限要求：仅允许领取该任务的 Agent 上报。
- 请求字段：`task_id`、`agent_name`、`current_step`、`progress`、`message`、`occurred_at`。
- 返回字段：`task_id`、`status`、`server_time`、`continue_running`。
- 状态流转：保持 `running`；如后端返回 `continue_running=false`，Agent 应停止并回写失败或人工接管。
- 失败处理：连续心跳失败时 Agent 应记录本地日志并在恢复后补传；后端超时可转 `failed` 或 `retrying`。
- 禁止事项：禁止心跳接口修改业务审批结论；禁止通过心跳传递真实账号密码。

## 5. 步骤日志上传

- 接口用途：上传 RPA 执行步骤日志。
- 请求方法：`POST`
- 路径：`/api/rpa/tasks/{id}/logs/`
- 调用方：RPA Agent。
- 权限要求：仅允许领取该任务的 Agent 上传。
- 请求字段：`task_id`、`level`、`step_name`、`message`、`occurred_at`。
- 返回字段：`task_id`、`log_id`、`status`。
- 状态流转：不改变业务状态；仅记录执行过程。
- 失败处理：上传失败可重试；不可因日志失败直接改业务数据。
- 禁止事项：禁止上传真实账号、密码、Cookie、Session；禁止上传完整财务后台内容。

## 6. 截图提交

- 接口用途：提交失败截图或关键节点截图。
- 请求方法：`POST`
- 路径：`/api/rpa/tasks/{id}/screenshots/`
- 调用方：RPA Agent。
- 权限要求：仅允许领取该任务的 Agent 提交。
- 请求字段：`task_id`、`step_name`、`screenshot_ref`、`message`、`occurred_at`。
- 返回字段：`task_id`、`screenshot_id`、`screenshot_url`、`status`。
- 状态流转：不直接改变业务状态。
- 失败处理：如阶段1暂未实现独立截图接口，可先通过 logs/result 中的 `screenshot_url` 或 `screenshots` 占位字段回传。
- 禁止事项：禁止提交包含真实账号密码、Cookie、Session、银行信息或完整财务后台的截图。

## 7. 任务完成

- 接口用途：回写 RPA 执行成功结果。
- 请求方法：`POST`
- 路径：`/api/rpa/tasks/{id}/complete/`
- 调用方：RPA Agent。
- 权限要求：仅允许领取该任务的 Agent 回写。
- 请求字段：`task_id`、`status=success`、`message`、`result`、`screenshots`、`page_url`、`page_snapshot`。
- 返回字段：`task_id`、`status`、`finished_at`。
- 状态流转：`running` -> `success`。
- 失败处理：回写失败时可重试；重试失败时转人工核查。
- 禁止事项：RPA 只回写执行结果，不改变业务审批结论，不自行决定上架、下架、清仓、补货或改价。

## 8. 任务失败

- 接口用途：回写 RPA 执行失败或人工接管结果。
- 请求方法：`POST`
- 路径：`/api/rpa/tasks/{id}/fail/`
- 调用方：RPA Agent。
- 权限要求：仅允许领取该任务的 Agent 回写。
- 请求字段：`task_id`、`status`、`message`、`error_code`、`error_message`、`manual_required`、`manual_reason`、`last_success_step`、`failed_step`、`screenshots`、`page_url`、`page_snapshot`。
- 返回字段：`task_id`、`status`、`finished_at`。
- 状态流转：`running` -> `failed`、`manual_required` 或 `retrying`。
- 失败处理：如果失败原因是验证码、登录异常、页面结构变化、权限异常，应优先转 `manual_required` 并提交截图。
- 禁止事项：禁止绕过失败状态继续执行高风险动作；禁止自行修改业务状态。
