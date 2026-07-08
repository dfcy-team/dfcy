# rpa-agent

阶段0 RPA Agent 目录占位，仅用于约定目录、配置示例、任务 payload 和运行边界。

## 阶段0边界

- RPA 不得直连 MySQL。
- RPA 不得直连 Redis 或任何数据层。
- RPA 只能访问 `/api/rpa/*`。
- RPA 不得访问 `/api/finance/*`、`/api/internal/finance/*`、`/admin/`。
- 不得写真实 BigSeller 账号密码。
- 阶段0不实现真实浏览器自动化脚本。
- 阶段0不执行真实改价。
- 阶段0不连接 BigSeller。
- 不写真实选择器、真实账号密码、真实 Token。

## 运行目录

- `screenshots/` 为运行截图目录，占位即可。
- `logs/` 为运行日志目录，占位即可。
- `cache/` 为运行缓存目录，占位即可。
- `downloads/` 为运行下载目录，占位即可。

## RPA Agent 接口边界

阶段0仅约定接口契约，不实现真实接口调用逻辑。

RPA Agent 只能访问：

| 接口 | 用途 | 请求字段占位 | 返回字段占位 |
|---|---|---|---|
| `POST /api/rpa/tasks/claim/` | Agent 领取任务 | `agent_name`、`agent_version`、`capabilities`、`queue_key` | `task_id`、`task_type`、`business_type`、`business_id`、`payload`、`status` |
| `POST /api/rpa/tasks/{id}/heartbeat/` | Agent 上报心跳 | `agent_name`、`current_step`、`progress`、`message` | `task_id`、`status`、`server_time`、`continue_running` |
| `POST /api/rpa/tasks/{id}/logs/` | 上传步骤日志 | `level`、`step_name`、`message`、`occurred_at` | `task_id`、`log_id`、`status` |
| `POST /api/rpa/tasks/{id}/screenshots/` | 提交截图占位 | `step_name`、`screenshot_ref`、`message`、`occurred_at` | `task_id`、`screenshot_id`、`screenshot_url`、`status` |
| `POST /api/rpa/tasks/{id}/complete/` | 回写成功结果 | `task_id`、`status=success`、`message`、`result`、`screenshots`、`page_url`、`page_snapshot` | `task_id`、`status`、`finished_at` |
| `POST /api/rpa/tasks/{id}/fail/` | 回写失败或人工接管 | `task_id`、`status`、`message`、`error_code`、`error_message`、`screenshots`、`page_url`、`page_snapshot` | `task_id`、`status`、`finished_at` |

明确禁止：

1. 禁止访问 `/api/finance/*`。
2. 禁止访问 `/api/internal/finance/*`。
3. 禁止访问 `/admin/`。
4. 禁止直连 MySQL。
5. 禁止直连 Redis。
6. 禁止读取完整财务后台。
7. 禁止绕过后端审批执行改价。
8. 禁止自行决定清仓、补货、上架、下架。
9. 禁止提交真实 BigSeller 账号密码。
10. 阶段0不包含真实浏览器自动化脚本。

## 高风险任务规则

1. `BIGSELLER_UPDATE_PRICE` 必须由后端生成任务。
2. payload 必须包含 `approval_id` 和 `approval_status=approved`。
3. RPA 只执行审批后的 `approved_price`。
4. RPA 执行完成后只回写执行结果，不改变业务审批结论。

## 目录结构

```text
rpa-agent/
├── agents/
├── bigseller/
│   ├── steps/
│   ├── selectors/
│   └── examples/
├── tasks/
│   └── examples/
├── screenshots/
├── logs/
├── config/
├── cache/
├── downloads/
├── .env.example
└── README.md
```
