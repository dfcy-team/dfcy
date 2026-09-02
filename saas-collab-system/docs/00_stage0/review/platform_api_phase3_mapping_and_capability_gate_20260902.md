# API 平台分层第三阶段实施说明（2026-09-02）

## 本阶段结果

本阶段把第二阶段的数据结构接入可控的运营流程，但仍保持“只读优先、人工确认、禁止平台写入”的安全边界：

1. 历史店铺可先预览、再确认关联到平台站点。
2. 店铺主数据页可查看和维护授权连接的能力矩阵。
3. 实时只读同步在调用适配器前校验对应能力，未明确启用时拒绝执行。

## 历史店铺站点映射

接口：`/api/internal/master-data/platform-sites/migration-preview/`

- `GET` 只生成预览，不修改数据。
- `POST` 仅在 `confirmed=true` 时执行，并要求 8 至 100 字符的 `idempotency_key`。
- 匹配键为同一租户内的 `platform_id + 标准化 country_code`。
- 只有唯一活动站点匹配的 `exact` 记录可以写入；多候选为 `ambiguous`，无候选为 `unmatched`。
- 已有关联的店铺不会被覆盖；提交过程使用事务、行锁和操作日志，并支持幂等重放。
- 返回应用、跳过、冲突数量及逐行明细，便于留档和复核。

推荐上线步骤：先按租户调用 GET 导出预览，人工处理 ambiguous/unmatched，再以小批量 store_ids 调用 POST，核对结果后扩大批次。

## 连接能力矩阵

能力矩阵复用店铺主数据页面，不增加新菜单。操作员先选择店铺授权连接，再维护读取开关、同步方式、来源优先级和状态。

- 无授权连接时只提示，不创建虚拟授权。
- 授权非 Active 时给出警告，服务端继续执行最终约束。
- 写入能力在界面硬禁用，提交负载也强制为 `false`。
- 未配置能力以关闭状态展示，避免把“缺失”解释为“允许”。

## 同步能力门禁

门禁仅作用于真实 `live_readonly` 店铺授权同步；mock 测试和非店铺授权任务保持兼容。检查发生在适配器配置校验和拉取数据之前。

| 同步资源 | 所需能力 |
| --- | --- |
| sales_order | ORDER |
| refund_return | RETURN_REFUND |
| inventory_snapshot | INVENTORY |
| inbound | WAREHOUSE |
| shipment | FULFILLMENT |
| settlement_bill | SETTLEMENT |
| withdrawal | PAYMENT |

允许执行的必要条件为：授权 Active、能力记录存在、能力 Active、`read_enabled=true` 且 `write_enabled=false`。任何条件不满足时返回 `CAPABILITY_NOT_ENABLED`，默认拒绝执行。

## 验证结果

- 本阶段与平台目录定向后端测试：通过。
- 平台站点、能力矩阵、目录类型和权限相关组合回归：22 项通过。
- 前端主数据定向测试：10 项通过；Vue 单文件组件编译通过。
- Django system check：通过；`makemigrations --check --dry-run` 无待生成迁移。
- 旧 `test_phase2_sync_framework.py` 有 16 项在测试夹具直接创建旧式凭据引用时，被现有凭据托管安全规则拦截；失败发生在同步任务创建前，与本阶段能力门禁无关。应后续更新测试夹具为轮换服务创建方式，不应放宽生产安全规则。

## 回滚与后续

- 应用层回滚不要求删除新表或旧字段；历史店铺仍可保持未关联状态。
- 若需撤销某批映射，应根据操作日志中的 store_ids 进行经审批的反向迁移，不提供无确认的批量清空接口。
- 禁用或删除能力配置会使相应实时只读同步立即失败关闭；不会触发平台侧写操作。
- 下一阶段可加入能力建议生成、映射预览的前端批量确认页，以及基于 `source_priority` 的多来源选择和审计。
