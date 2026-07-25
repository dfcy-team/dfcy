# 发布合同 API 合同 V1

## 1. 范围

本合同定义发布候选版本、门禁证据、职责分离审批、构建制品和状态迁移。接口只记录受控动作及外部平台结果，不直接调用微信发布、自动回退、数据库迁移或其他生产写操作。

小程序端仅提供只读工作台和详情。所有状态变更只允许内部 API 调用专用服务完成。

## 2. 核心对象

- `ReleaseContract`：候选提交、应用、环境、API 合同版本、范围、风险、停止条件、回退点和状态。
- `ReleaseArtifact`：唯一构建号、候选 commit、制品 SHA-256、配置版本和脱敏 manifest；创建后不可变。
- `ReleaseGateResult`：门禁代码、结果、证据引用、评估时间和到期时间。
- `ReleaseApproval`：业务、技术、安全或回退审批；审批记录不可变。
- `ReleaseAuditEvent`：动作、前后状态、执行人、原因、证据、请求 ID、对象版本和幂等键摘要；不可更新或删除。

## 3. 必须门禁

- `engineering-quality`
- `miniapp-special`
- `backend-compatibility`
- `end-to-end`
- `release-readiness`
- `evidence-integrity`
- `miniapp-filing-approved`（仅生产环境必需，证据必须证明小程序备案审核已通过）

所有门禁必须为 `passed` 且未过期，合同才能提交评审；正式开始发布前再次校验。
生产环境在备案审核通过前不得进入提交评审、上传、平台审核或发布状态。本接口只记录
受控动作与脱敏证据，不代替微信公众平台备案、审核或发布操作。

## 4. 主状态机

```text
draft
  -> review_pending
  -> approved
  -> built
  -> uploaded
  -> platform_review
  -> scheduled
  -> releasing
  -> released
  -> observing
  -> completed
```

异常分支：

- 评审拒绝：`review_pending -> rejected`
- 平台审核失败：`platform_review -> review_failed`
- 发布失败：`releasing -> release_failed`
- 回退：`released|observing|release_failed -> rollback_required -> rolled_back`
- 合法未执行状态可进入 `cancelled`

通用模型写入、QuerySet `update`、批量更新和删除不得修改受保护字段。

## 5. 审批规则

- 正常发布必须分别获得 `business`、`technical`、`security` 三类批准。
- 合同创建人不能审批自己的发布或回退。
- 同一人员不能满足多个审批角色。
- 回退执行前必须有独立 `rollback` 批准。
- 任一正常审批拒绝后合同进入 `rejected`。

## 6. 内部 API

基础路径：`/api/internal/releases/`

- `GET|POST contracts/`
- `GET contracts/{id}/`
- `POST contracts/{id}/gates/`
- `POST contracts/{id}/approvals/`
- `POST contracts/{id}/build/`
- `POST contracts/{id}/actions/{action}/`

所有写操作必须携带：

- `Idempotency-Key` 请求头
- 当前 `version`
- 可审计 `reason`

权限：

- `release.contract.view`
- `release.contract.manage`
- `release.contract.approve`
- `release.contract.execute`

## 7. 小程序只读 API

基础路径：`/api/miniapp/releases/`

- `GET workbench/`
- `GET contracts/{id}/`

需要小程序通道 JWT、`release.contract.view` 权限及数据范围。响应固定包含 `read_only=true`。未提供 POST、审批、执行或回退端点。

## 8. 验收标准

- 缺失、失败或过期门禁不能提交评审或开始发布。
- 三类正常审批全部通过后才进入 `approved`。
- 制品 commit 必须与候选 commit 一致，制品哈希必须为 SHA-256。
- 旧版本写操作返回版本冲突，重复幂等键只能重放相同动作。
- 跨租户合同不可见。
- 小程序仅能读取合同、门禁、审批和脱敏证据。
- 发布与回退动作只记录结果，不自动调用真实平台。
