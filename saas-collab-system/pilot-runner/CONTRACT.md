# V2.44.59 Runner/Backend 共享合同

## 请求

`POST /v1/executions`，必须有 `Idempotency-Key` 和 `Authorization: Bearer`。
JSON 允许字段：

| 字段 | 要求 |
| --- | --- |
| `environment` | 服务端 `environments` 中的安全标识符；生产示例同时预置 `pilot` 与 `controlled-pilot`，须与数据库环境 code 一致 |
| `operation` | `deploy` / `recovery` / `rollback` / `performance` |
| `profile` | 仅 performance；服务端 profile 名称（生产示例为 `demo`/`synthetic`，兼容缺省 `smoke`） |
| `target_alias` | 仅 performance；必须等于 profile 的服务端 target（生产示例为 `demo-app`） |
| `expected_release_sha` | 仅 deploy；40 位小写 SHA，必须等于 root-owned approved candidate |
| `release_plan_ref` | 仅 deploy；必须精确等于 approved candidate 的 release plan ref |

不得传 `argv`、`command`、`url`、`rps`、`concurrency`、`duration_seconds`
、镜像、actor、reason、token 或任意未知字段。deploy 的两个绑定字段只用于
服务端等值校验，绝不进入 shell/argv；绑定失败即 fail-closed。

## 响应

创建执行返回 `202`（新任务）或 `200`（幂等回放）：

```json
{
  "operation_id": "opaque-id",
  "idempotency_key": "request-key",
  "environment": "controlled-pilot",
  "operation": "deploy",
  "target_release_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "target_release_version": "2.44.59",
  "target_release_plan_ref": "release/system-v2.44.59",
  "status": "running",
  "exit_code": null,
  "summary": "safe summary",
  "evidence_ref": null,
  "metrics": null,
  "error_code": null,
  "started_at": "2026-09-03T00:00:00Z",
  "deadline_at": "2026-09-03T00:05:00Z",
  "finished_at": null
}
```

后端应把 `202` 的 `operation_id` 持久化并轮询
`GET /v1/executions/{id}`。只把 `evidence_ref` 作为单个脱敏引用展示，不能
尝试拼接本地路径或读取证据目录。runner 内部的拒绝、超时和重启中断在
线协议中统一为 `failed` 终态，并以 `error_code` 区分；后端不得将其误报为
成功，`exit_code` 为 `null` 时以 `error_code` 判断阻断原因。

`started_at`/`deadline_at` 在 runner 接受任务后稳定返回，终态不会被轮询
客户端改写；`deadline_at` 来源于服务端固定命令或性能配置的超时。超时会
杀掉整个命令进程组，并以 `failed`/`COMMAND_TIMEOUT` 终结。后端必须继续
轮询直到 runner 的终态，不得因 Celery 单次软/硬时限先把仍在执行的生产动作
标记为成功或失败；若后端自身达到任务预算，应转入人工核验而不是重放同一个
幂等键。

HTTP 性能在 runner 与应用同机时可报告 `metrics_source=app-vm-host-proc`、
`scope=app_vm_host` 的宿主机 `/proc` CPU/内存摘要；这些指标不是容器级数据。
若内核摘要不可用，CPU/内存为 `null` 并以
`PERFORMANCE_RESOURCE_METRICS_UNAVAILABLE` fail-closed。容器级阈值应改用
固定的受信性能 adapter。

## 生产门禁

runner 的 `deploy`/`rollback` argv 指向 root-owned 固定桥接脚本。桥接脚本
只消费 owner/CI 原子发布的 `/etc/saas-collab/runner/approved-candidate.json`
和独立 token 文件，然后调用现有 `production-control/bin/production-deploy`
或 `production-rollback`；不从 API 接收镜像 digest、release SHA、actor、reason
或 registry token。候选 manifest 必须由 `stage-approved-candidate.sh` 校验，
其父 SHA 与 production-control `current.json.release_sha` 相等、release plan
版本与候选版本相等、镜像为固定 digest，且包含 main ancestry/image/migration
三项 CI 门禁证明。缺失、权限不安全、原子快照变化或任一门禁不匹配时，桥接器
必须直接失败。V2.44.59 仅作为首个候选示例，不应写入长期执行器逻辑。
