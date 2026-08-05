# A-PR2 OAuth Callback Query Redaction 发布门禁登记

## 1. 登记背景

- 来源：R6 独立复审报告（`docs/00_stage0/review/a_pr2_arch_security_r6_review.md`）§6 第 1 项观察项。
- 现象：marketplace OAuth callback 为 GET 端点，原始 query 携带 `state`、`code`、`signature` 等敏感参数。
- 缺口：仓库内未见 Sandbox / Pilot / Production 反向代理与 access log 的 query redaction（脱敏）配置或验证证据。
- 登记日期：2026-08-05。
- 登记任务：A-PR2-R7-T4。

## 2. 门禁要求（发布前置条件）

在 Sandbox、Pilot、Production 任一环境启用真实 callback 域名之前，必须逐项完成并留证：

1. 反向代理（Nginx / Traefik / 云 LB 等）access log 不得记录 OAuth callback 请求的原始 query string；须配置 `$args` 脱敏、仅记录路径或对敏感参数掩码（如 `code=***&state=***`）。
2. 应用层（Django/ASGI 服务器、结构化日志）不得将 callback 的 `code`、`state`、`signature` 原值写入任何日志；如需排障，仅允许记录长度、前缀哈希或掩码值。
3. 每个环境部署后须执行一次验证：发起一次合成 callback 请求，确认 access log 与应用日志中无原始 query 值，留存掩码后的日志样本作为证据。
4. 上述证据须经架构员确认后，方可在该环境放行真实回调域名。

## 3. 状态与边界

- 观察项状态：由“开放”更新为“已登记至发布门禁”。
- 本项为 Sandbox / Pilot / Production 的发布前置条件，不阻塞当前 synthetic/mock 合同（PR #40 的合并评审）。
- 本文档不改动任何生产网络 / 代理配置，不授权标记 `connected`，不放宽真实回调域名。
- 本文档不记录任何真实凭据或完整 query 原值；后续证据一律以掩码样本引用。

## 4. 架构员确认

- 确认人角色：架构员（独立只读核对）。
- 结论：登记内容与 R6 §6 第 1 项一致，门禁要求完整，接受为发布前置条件。
- 后续跟踪：在 `SANDBOX-ARCH-002` 生产发布门禁的“发布输入”核对中，将本项 redaction 验证证据纳入必查清单。
