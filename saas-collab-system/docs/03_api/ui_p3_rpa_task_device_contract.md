# UI-P3 RPA 任务与设备合同

## 1. 适用范围

UI-P3 建设 RPA internal 管理面，不替代 RPA Agent 执行协议。浏览器中的 internal 用户只能访问 `/api/internal/rpa/*`；Agent 继续只访问 `/api/rpa/*`。两个分区不得共享身份、Token 或操作按钮。

本期只允许 Mock/dry-run，不连接 BigSeller、Shopee、TikTok/TK，不实现真实浏览器自动化。

## 2. 页面合同

| 页面 | 路径 | 权限 |
|---|---|---|
| 任务中心 | `/rpa/tasks`、`/rpa/tasks/{id}` | `rpa.tasks.view` |
| 运行记录 | `/rpa/runs`、`/rpa/runs/{id}` | `rpa.tasks.view` |
| 设备管理 | `/rpa/devices`、`/rpa/devices/{id}` | `rpa.devices.view` |
| 人工队列 | `/rpa/manual-queue` | `rpa.tasks.view`；动作需 `rpa.tasks.manage` |
| 稳定性 | `/rpa/stability` | `rpa.stability.view` |
| 账号串行锁 | `/rpa/account-locks` | `rpa.stability.view` |
| 页面签名 | `/rpa/page-signatures` | `rpa.stability.view` |

未登记路由默认拒绝。前端权限只控制展示，后端 permission、tenant 和 data_scope 是可信授权结果。

## 3. API 合同

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/internal/rpa/tasks/` | `rpa.tasks.view` | tenant/data_scope 过滤的任务分页 |
| GET | `/api/internal/rpa/tasks/{id}/` | `rpa.tasks.view` | 脱敏 payload/result、日志和占位证据 |
| POST | `/api/internal/rpa/tasks/{id}/assign-manual/` | `rpa.tasks.manage` | 仅为 `manual_required` 任务分配人工负责人 |
| POST | `/api/internal/rpa/tasks/{id}/retry-mock/` | `rpa.tasks.manage` | 仅将失败或人工任务放回 Mock/dry-run 队列 |
| GET | `/api/internal/rpa/runs/` | `rpa.tasks.view` | 运行记录分页 |
| GET | `/api/internal/rpa/runs/{id}/` | `rpa.tasks.view` | 单次运行详情 |
| GET | `/api/internal/rpa/devices/` | `rpa.devices.view` | 设备分页；不返回 Token、IP白名单和完整指纹 |
| GET | `/api/internal/rpa/devices/{id}/` | `rpa.devices.view` | 设备详情 |
| POST | `/api/internal/rpa/devices/{id}/dry-run/` | `rpa.devices.dry_run` | 本地绑定检查；不启动浏览器、不连接平台 |
| GET | `/api/internal/rpa/manual-queue/` | `rpa.tasks.view` | `manual_required` 任务分页 |
| GET | `/api/internal/rpa/account-locks/` | `rpa.stability.view` | 同账号串行锁只读证据 |
| GET | `/api/internal/rpa/page-signatures/` | `rpa.stability.view` | 脱敏页面签名只读证据 |
| GET | `/api/internal/rpa/stability/` | `rpa.stability.view` | 任务/运行状态分组统计 |

分页统一为 `data.count/next/previous/results`。成功响应统一为 `success/code/message/data`；错误使用 400、401、403、404、409、422。

## 4. 权限与 data_scope

- `rpa.tasks.view`：任务、运行、人工队列查看。
- `rpa.tasks.manage`：人工分配和 Mock 重试。
- `rpa.devices.view`：脱敏设备查看。
- `rpa.devices.dry_run`：设备本地 dry-run 检查。
- `rpa.stability.view`：任务/运行统计、账号锁和页面签名。
- 每个权限必须绑定有效 data_scope；`all` 查看本 tenant 全部数据。
- `custom.rpa_task_ids` 限制任务、运行和账号锁；`custom.rpa_device_ids` 限制设备和运行；`custom.rpa_platforms` 限制页面签名。
- external 和 RPA 用户不能访问 `/api/internal/rpa/*`；internal 用户不能持 Agent 身份调用执行端。

## 5. 双状态机

任务状态：`pending -> claimed -> running -> success`；失败可进入 `failed/retrying/manual_required/cancelled`。internal 管理动作不能把任务直接改为 success。

运行状态：`claimed -> running -> success/failed/retrying/manual_required/cancelled`。每次 claim 创建独立运行记录，运行状态不覆盖任务状态。

`retry-mock` 只允许 `failed` 或 `manual_required`，超过最大重试次数返回 422；状态不允许时返回 409。人工分配只允许 `manual_required`。

## 6. 设备与执行边界

- 设备模式仅为 `mock`、`dry_run`、`production_disabled`。
- 本期只有 active 的 `mock/dry_run` 设备可通过 dry-run 检查。
- `production_disabled` 拒绝 dry-run 和 Agent claim。
- dry-run 只校验设备绑定并写审计；`platform_connection` 和 `browser_automation` 固定为 `not_attempted`。
- 管理前端不得调用 claim、heartbeat、logs、screenshots、complete、fail。
- 账号锁只能由 Agent 执行服务维护；管理前端只读。
- 页面签名变化只暂停任务并转人工，不自动恢复、改价、刊登或清仓。

## 7. 连接状态

- `connected`：关闭 Mock 后 internal API 实际成功。
- `mock`：`VITE_USE_MOCK=true` 使用示例数据。
- `degraded`：网络级失败后回退 Mock。
- 401/403/404/409/422 不回退 Mock，必须展示真实错误。
