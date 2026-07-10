# 阶段2 API 数据接入沙箱与安全方案

## 1. 适用范围

本方案用于阶段2 API 数据接入准备，覆盖契约、Mock/沙箱、凭据边界、同步质量和审计要求。不授权任何真实平台连接。

## 2. 接口分区

| 分区 | 用途 | 调用方 | 阶段2状态 |
|---|---|---|---|
| `/api/internal/*` | 内部后台业务和同步管理查询 | 经过后端鉴权的内部前端 | 可在 Mock/沙箱下规划 |
| `/api/external/*` | 供应商自身任务和绩效 | 经过后端鉴权的供应商前端 | 可在 Mock/沙箱下规划 |
| `/api/rpa/*` | RPA Agent 领取任务、心跳、日志、截图和结果回写 | RPA Agent | 保持既有协议，不扩权 |
| `/api/finance/*` | 财务独立授权能力 | 经财务权限码鉴权的内部用户 | 仅脱敏样例和设计 |
| `/api/report/*` | 报表查询 | 经后端授权的内部用户 | 仅 Mock/查询契约 |
| `/api/platform/*` | 平台连接器或同步编排占位 | 后端服务 | 仅 sandbox/placeholder，需专项评审后才能连接真实平台 |

禁止将 `/admin/` 作为业务接口；供应商不得调用 `/api/internal/*`；RPA 不得调用财务或管理后台接口。

## 3. 平台连接器契约

每个后续连接器应以统一内部契约实现，而非由页面直接调用第三方平台：

```text
connector.fetch(cursor, scope) -> raw records
normalizer.validate(raw records) -> normalized records + quality findings
sync service.persist(normalized records) -> tenant-scoped business data + audit batch
```

最低字段：`tenant_id`、`connector_name`、`sync_type`、`request_id`、`source_cursor`、`started_at`、`finished_at`、`status`、`quality_result`、`error_code`。

## 4. 凭据与网络边界

- 仓库、前端构建产物、RPA payload、日志和截图不得保存真实凭据。
- `.env.example` 只能使用 `change-me`、`placeholder`、`demo`、`example.com` 等示例值。
- 真实凭据仅在专项安全评审通过后，由部署环境的密钥管理能力注入；不得通过 API 返回给前端或 RPA。
- 平台调用必须使用允许列表、最小网络权限、超时、限流、指数退避和可审计 request_id。
- 真实平台的 webhook、回调地址、IP 白名单和证书必须另行评审。

## 5. 同步正确性要求

- 写入必须具备 tenant 过滤、幂等键和可重放的同步批次标识。
- 失败时记录错误代码、脱敏错误信息、重试次数和人工处理状态；不得记录 Authorization、Cookie、Token 或完整请求体。
- 数据质量至少检查必填字段、来源时间、重复记录、tenant 归属和枚举合法性。
- 未通过质量检查的数据不得直接覆盖最终可信业务数据。

## 6. 阶段2验证场景

1. Mock 模式下可返回统一 `success/code/message/data` 响应。
2. sandbox 配置缺失凭据时应安全失败，并返回脱敏错误。
3. 跨 tenant 请求、供应商越权请求、RPA 访问财务请求必须被拒绝。
4. 重复同步请求不会产生重复可信业务记录。
5. 连接器超时、限流和字段校验失败均可审计、可重试、可人工接管。

