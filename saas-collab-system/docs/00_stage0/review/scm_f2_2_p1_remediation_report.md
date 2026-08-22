# SC-F2-2 API 契约 P1 整改报告

## 1. 整改结论

`SC-F2-2-R1-P1-001` 至 `SC-F2-2-R1-P1-005` 已在契约层完成整改。

当前状态为：

`P1_REMEDIATED_PENDING_RECHECK`

本轮只修改 SC-F2-2 API 契约和审核基线，没有创建 F2 URL、view、serializer、
前端 API 或小程序页面，也没有连接供应链线上系统、导入真实数据或执行部署。
在独立整改复核给出 `PASS_FOR_SC_F2_2_LOCAL_API_IMPLEMENTATION` 前，仍不得进入 API 实现。

## 2. 整改基线

| 项目 | 值 |
| --- | --- |
| 分支 | `codex/scm-f2-packing-local` |
| 整改前 HEAD | `c5093d5689615d55688a7d5e3a0407354de0e43d` |
| 首轮冻结提交 | `b8d701f3e56e4828a5950da6ca4b9b7685a2a63b` |
| 独立审核提交 | `c5093d5689615d55688a7d5e3a0407354de0e43d` |
| 主契约版本 | `v2-p1-remediated` |
| 执行环境 | 架构员主机本地隔离环境 |
| 生产连接或变更 | 无 |

## 3. P1 逐项关闭记录

### SC-F2-2-R1-P1-001：取消批次订单 DataScope

已冻结：

1. 既有批次授权读取全部历史 `PackingBatchOrder.order_id`，不按 `active_guard` 过滤。
2. `active_guard=TRUE` 只用于创建资格、布局业务校验和活动占用判断。
3. 实现验收必须覆盖 draft、in_progress、completed、cancelled 四状态。
4. 取消后原订单 scope 仍可见，其他订单 scope 统一返回 404。

关闭状态：`REMEDIATED_PENDING_RECHECK`

### SC-F2-2-R1-P1-002：API 冻结响应原子持久化

已冻结：

1. 唯一持久化模型为 `PackingApiIdempotencyRecord`。
2. 非空 `scope_key` 与 MySQL
   `(tenant_id, scope_key, idempotency_key)` 唯一约束不依赖 nullable 资源列。
3. actor、channel、action、resource、request hash、HTTP status、response kind、
   JSON body 或 label snapshot 均有唯一字段合同。
4. 最外层 `transaction.atomic()` 同时覆盖领域服务、业务写入、事件、日志、响应序列化和 API 记录。
5. 唯一记录命中后逐项比较身份与请求，差异统一返回 `IDEMPOTENCY_CONFLICT`。
6. 验收加入“领域写后、快照保存前”模拟失败全量回滚。
7. MySQL 同键并发首次请求只能形成一条业务结果和一条 API 幂等记录。

关闭状态：`REMEDIATED_PENDING_RECHECK`

### SC-F2-2-R1-P1-003：移除箱协议

已冻结：

1. 唯一路径改为 `POST batches/{id}/boxes/{box_id}/actions/remove/`。
2. `expected_version` 使用严格 JSON body。
3. 内部端使用 `supply.packing.manage`；供应商 Web/小程序要求 `can_self_pack=true`。
4. 三通道均要求 Idempotency-Key，成功为 200 和冻结 `PackingBatchDetail`。
5. 旧 DELETE 路径不注册、不兼容、不保留别名，并加入不可达测试。

关闭状态：`REMEDIATED_PENDING_RECHECK`

### SC-F2-2-R1-P1-004：确定性标签 PDF

已冻结：

1. 仅 `in_progress|completed` 且至少一个非空箱允许生成标签。
2. 批次 PDF 一箱一页并按 sequence 排序；箱 PDF 固定一页。
3. QR 为固定字段的非 URL 规范 JSON，并明确敏感字段禁止清单。
4. 标签快照 schema 固定事件时间、布局/渲染器/字体版本、箱内容和 QR payload。
5. 禁止当前时间、随机 ID 和不稳定元数据；ETag 固定为 PDF 字节 SHA-256 强 ETag。
6. 同 key 重放必须字节级一致；后续布局升级仍须按冻结版本重建旧 PDF。
7. `generate_label` 事件和 API 幂等记录保存同一规范业务快照，不保存 PDF 二进制。

关闭状态：`REMEDIATED_PENDING_RECHECK`

### SC-F2-2-R1-P1-005：全局当前标准 DataScope

已冻结：

1. 内部端要求活动 internal、非 miniapp、exact `supply.packing.view` 和至少一个合法 permission-specific scope。
2. ALL、OWN、合法 CUSTOM 仅满足合法 scope 门禁，不执行资源 ID 交集。
3. 无 scope 返回 `DATA_SCOPE_MISSING`；任一非法 scope 返回 `DATA_SCOPE_INVALID`。
4. 供应商 Web/小程序要求有效 external 供应商绑定，不要求 `can_self_pack`。
5. 输出仍只允许四个已登记 boolean 规则键。
6. 实现验收覆盖 ALL/OWN/CUSTOM/缺失/非法 scope 和三通道矩阵。

关闭状态：`REMEDIATED_PENDING_RECHECK`

## 4. 保持不变的边界

- 供应商能力配置 API 继续排除，后续必须独立冻结权限、supplier DataScope、乐观锁、
  持久化幂等、审计、并发和回滚合同。
- SC-F2-1 模型与领域服务审核结论不被本轮文档整改修改。
- F2 不推进 SC-F1 `production_completed`，不产生 F3 或物流状态。
- 不允许线上连接、双写、同步、切流、真实通知、客户端发布或生产部署。

## 5. 下一步门禁

下一步仅允许执行：

`SC-F2-2 API 契约、权限与 DataScope P1 整改复核`

复核必须逐项验证 P1-001 至 P1-005 的契约唯一性、实现可测试性、MySQL 语义和生产隔离，
并重新确认 backend、frontend、miniapp 实现树相对 SC-F2-1 最终归档未发生变化。
