# 受控试点执行器

`pilot-runner` 是独立于 Django/Celery 的主机侧执行服务。它只接受
HTTPS 请求；除健康探针外，执行接口必须携带 `Authorization: Bearer ...`。
Bearer token 只能来自配置指定的 root-owned `0400/0440/0600/0640` 文件，服务不会从
环境变量、请求体、命令行参数或仓库读取 token。

## API 合同

创建执行：

```http
POST /v1/executions
Authorization: Bearer <token>
Idempotency-Key: <1..128 个安全字符>
Content-Type: application/json

{"environment":"controlled-pilot","operation":"deploy","expected_release_sha":"<40-char-approved-sha>","release_plan_ref":"<approved-release-plan-ref>"}
```

允许的 `operation` 只有 `deploy`、`recovery`、`rollback`、`performance`。
recovery/rollback 只能包含 `environment` 和 `operation`；deploy 还必须带
服务端 approved candidate 的 `expected_release_sha` 与 `release_plan_ref`，
仅用于等值绑定校验。性能操作可以再包含服务端
配置中存在的 `profile`，以及与该 profile 完全匹配的 `target_alias`；请求
不能传 URL、argv、RPS、并发数或时长。响应为 `202` 并包含 `operation_id`；
如果 key 已完成则返回 `200`，同一 key 的 payload 不一致返回 `409`。

查询执行：

```http
GET /v1/executions/{operation_id}
Authorization: Bearer <token>
```

状态为 `queued`、`running`、`succeeded`、`failed` 或 `manual_required`。
执行器内部的超时、重启中断和并发拒绝统一以 `failed` 终态返回，并用
`error_code` 区分 `COMMAND_TIMEOUT`、`RUNNER_RESTARTED`、`CONCURRENCY_LIMIT`
或 `ENVIRONMENT_BUSY`。终态响应固定包含 `exit_code`、脱敏 `summary`、
单个相对 `evidence_ref`、`error_code`、`started_at`/`deadline_at`、目标发布绑定
字段和（性能操作）`metrics`。指标包含
`p50_ms`、`p95_ms`、`error_rate`；runner 不会使用自身进程资源冒充目标资源。
当 runner 与应用部署在同一 VM 时，HTTP 探针读取内核 `/proc/stat` 与
`/proc/meminfo` 的宿主机摘要，指标标记 `metrics_source=app-vm-host-proc`、
`scope=app_vm_host`；它代表整台应用 VM，而非单个容器。无法取得这类受信
摘要时 `cpu_percent`/`memory_percent` 为 `null`，并以
`failed`（`PERFORMANCE_RESOURCE_METRICS_UNAVAILABLE`）返回，避免把不完整
数据当成生产阈值结论。需要容器级 CPU/内存阈值时必须使用固定的受信 adapter。
HTTP 性能目标必须是配置中的 HTTPS allowlist，且 RPS、并发和时长受服务端上限约束。
生产配置示例预置 `pilot` 与 `controlled-pilot` 两个环境，profile 为 `demo`、
`synthetic`（兼容缺省 `smoke`），目标别名为 `demo-app`。这些标识必须和后端
数据库中的环境 code、workload profile、target alias 完全一致；现场只应通过
root-owned 配置文件调整 allowlist URL，不能由请求覆盖。

`GET /healthz` 与 `GET /readyz` 不返回运行结果，可供本机/容器探针使用；
二者仍只能通过 runner 的 TLS 监听端口访问。生产入口不得把 runner 端口
暴露到公网。

## 安全边界

- 每个环境只有一个互斥执行；全局并发、body 大小、请求/操作超时均有上限。
- `deploy`、`recovery`、`rollback` 由配置中的不可变 argv 列表选择，执行使用
  `shell=False`、`stdin=DEVNULL`，不接受客户端命令、URL 或参数。
- `audit.jsonl` 以追加+fsync 写入；审计失败会使 readiness 失败并拒绝新任务。
- SQLite 状态持久化幂等 key 和结果；重启时未完成任务标记为
  `interrupted`，不会自动重放生产动作。
- 证据目录建议 `0700`，证据文件 `0600`；输出会脱敏常见 API key、token、
  password 和 Authorization 内容，但命令本身仍必须由架构员审查。
- TLS 私钥、runner token、OpenAI key、数据库凭据和 registry token 不得进入
  Git、镜像层、Compose 环境值或日志。OpenAI key 由业务容器以只读文件引用。

## 启动

```sh
python3 /opt/saas-collab/pilot-runner/app.py \
  --config /etc/saas-collab/runner/config.json
```

配置缺失、token/TLS 文件不安全、allowlist 不是 HTTPS、命令不是绝对路径，
服务都会以 fail-closed 启动失败。生产安装请使用
`deploy/pilot/runner/install-runner.sh`，并先完成 V2.44.58 账本、网络和
root-owned production-control 对齐。候选文件使用固定的
`/etc/saas-collab/runner/approved-candidate.json`，由 CI/架构员原子 stage；
V2.44.59 仅是首个样例，runner 不锁定具体版本。
