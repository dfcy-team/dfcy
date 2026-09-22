# BD 配置业务逻辑交接

## 1. 范围

本版配置中心只包含以下 4 个租户级配置：

| 页面名称 | JSON 字段 | 默认值 | 可选范围 |
| --- | --- | --- | --- |
| 默认指标视图 | `default_metrics` | `core` | `core` / `full` |
| 每日归因补偿 | `daily_attribution_reconciliation_enabled` | `true` | `true` / `false` |
| 送样逾期时长 | `sample_video_overdue_days` | `20` | 1-365 天的整数 |
| 送样逾期提醒 | `sample_overdue_notification_enabled` | `false` | `true` / `false` |

配置键为 `influencers.bd.performance`，作用域为当前租户。默认币种和默认归因方式不在本版配置中；BD 绩效仍默认使用 `CNY` 和 `strict`，页面查询时仍可手动切换。

完整配置值示例：

```json
{
  "default_metrics": "core",
  "daily_attribution_reconciliation_enabled": true,
  "sample_video_overdue_days": 20,
  "sample_overdue_notification_enabled": false
}
```

## 2. 入口与权限

- 菜单：`达人管理 -> BD配置`
- 路由：`/influencers/bd-config`
- 查看：`config.view`
- 创建新版本：`config.manage`
- 审批：`config.approve`
- 创建者不能审批自己创建的版本。

## 3. 版本与生效逻辑

1. 点击“提交新版本”会创建不可变的配置版本，状态为 `pending_approval`。
2. 具有 `config.approve` 权限的其他用户审批后：
   - 生效时间已到：立即变为 `effective`。
   - 生效时间在未来：先变为 `approved`。
3. Celery Beat 每 60 秒执行 `configcenter.activate_due_config_versions`，将已到时间的 `approved` 版本转为 `effective`。
4. 新版本生效后，同一租户同一配置键的旧生效版本变为 `superseded`。
5. 业务代码只读取 `effective_at <= 当前时间` 的最新 `effective` 版本；无生效版本或字段值非法时使用安全默认值。

## 4. 四个配置项的业务逻辑

### 4.1 默认指标视图

- `core`：进入 BD 绩效页后默认优先展示 GMV、投入和 ROI。
- `full`：默认展示完整指标，包括建联、送样、商品件数、佣金和视频结果等。
- 该值只决定页面初始视图，不修改统计口径，用户仍可在页面上手动切换。

### 4.2 每日归因补偿

- Celery Beat 每天上海时间 `03:00` 执行调度任务。
- 只处理已存在联盟订单快照、且开启本开关的租户。
- 每个租户独立入队，同时计算 `strict` 和 `fallback` 两种归因结果。
- 近期增量：处理最近 7 天内更新的联盟订单。
- 历史回扫：按租户保存游标，每次最多补偿 5,000 条 7 天前的订单；一轮扫描完成后游标归零，后续周期重新检查历史遗漏。
- 开关关闭时只跳过每日自动补偿，不删除既有归因快照，也不阻止其他明确发起的归因刷新。

### 4.3 送样逾期时长

- 数值必须为 1-365 之间的整数，默认 20 天。
- 新建送样时，截止时间默认为 `送样时间 + 配置天数`。
- 送样记录进入已发货，或来源数据提供了发货时间时，以 `发货时间 + 配置天数` 计算。
- 修改配置只影响之后新建、发货或按来源日期重算的记录，不批量改写已存在的 `video_deadline_at`。

### 4.4 送样逾期提醒

- Celery Beat 每天上海时间 `02:00` 执行送样逾期扫描。
- 候选状态为 `pending`、`processing`、`shipped`、`delivered`，且记录未删除、截止时间已过。
- 已匹配发布视频的记录不会标记为逾期，而是进入视频状态对账。
- 符合条件且没有发布视频的记录转为 `overdue`，写入状态事件和审计日志，并重算关联建联任务进度。
- 提醒开启时，向该送样记录的负责人创建 `NotificationMessage`。
- 通知键为 `sample_overdue:<送样ID>`，使用唯一获取或创建逻辑，同一送样只会生成一条逾期通知。
- 提醒关闭时仍会更新逾期状态，只是不创建通知记录。
- 当前 PR 不包含全局站内消息入口和未读红点；通知已落库，但页面显著性需后续功能补齐。

## 5. 创建送样的负责人规则

- 从建联任务创建送样时，当前用户或所选送样负责人必须是该建联任务的主负责人或多负责人之一。
- 不符合时返回 HTTP `409`，前端展示：`需要该建联任务负责人创建送样。`
- 飞书全量送样快照导入保留专用兼容路径，不受手工创建界面的负责人阻断影响。

## 6. 10 主机部署要求

1. 合并 PR #181 后更新后端、前端、Celery Worker 和 Celery Beat 到同一提交。
2. 执行 Django migrations，确保 `influencers.0024` 和 `influencers.0025` 已应用。
3. 确认 Celery Worker 正在消费任务，Celery Beat 只运行一个调度实例，避免重复投递。
4. 确认服务器 `TIME_ZONE=Asia/Shanghai`；代码中 Beat 时间按 UTC 配置，分别对应上海时间 02:00 和 03:00。
5. 确认操作人具有 `config.view`、`config.manage` 或 `config.approve` 对应权限。
6. 不需要删表、清空数据或批量重写历史送样截止时间。

## 7. 验收清单

- `/influencers/bd-config` 只显示本文档的 4 个配置项。
- 无生效版本时显示默认值：`core / 开启 / 20 / 关闭`。
- 创建新版本后不立即影响业务，审批并到达生效时间后才应用。
- 设置逾期时长后，新建送样的 `video_deadline_at` 按新值计算，历史记录不变。
- 开启提醒后，过期且无已发布视频的送样转为 `overdue`，负责人获得一条去重通知。
- 关闭每日归因补偿后，对应租户不再自动入队；重新开启后下一次日调度恢复。
- 非建联任务负责人创建送样时，页面显示“需要该建联任务负责人创建送样。”

