# SC-F2-2 API、权限与 DataScope 独立审核报告

## 1. 审核结论

审核结论：

`REQUIRES_SC_F2_2_CONTRACT_REMEDIATION`

当前冻结稿不允许进入 F2 API 实现。审核发现 5 项 P1 合同缺口，必须先整改并独立复核。

本结论不修改 SC-F2-1 已通过的模型与领域服务结论，也不授权注册 F2 路由、实现 serializer/view、修改网页端或小程序端、连接线上系统、导入真实数据或执行生产部署。

## 2. 审核基线

| 项目 | 审核值 |
| --- | --- |
| 分支 | `codex/scm-f2-packing-local` |
| SC-F2-1 最终归档 | `71341fb5e85307bdb0ed505ef65c1df2d7a901b9` |
| SC-F2-2 冻结提交 | `b8d701f3e56e4828a5950da6ca4b9b7685a2a63b` |
| 主契约 | `docs/03_api/supply_chain_f2_packing_api_contract.md` |
| 审核检查表 | `docs/00_stage0/review/scm_f2_2_api_permission_datascope_review_baseline.md` |
| 审核日期 | 2026-07-28 |
| 执行环境 | 架构员主机本地隔离环境 |
| 生产连接或变更 | 无 |

提交范围核对结果：

- 冻结提交只新增 2 份 SC-F2-2 文档；
- backend、frontend、miniapp 实现树相对 SC-F2-1 最终归档未变化；
- 当前没有 F2 URL、view 或 serializer；
- 契约引用的 5 个 permission 与权限种子完全一致；
- 工作区原有其他修改不属于审核基线。

## 3. P1 审核发现

### SC-F2-2-R1-P1-001：取消批次的订单 DataScope 会空集合自动通过

主契约第 7.3 节规定，`supply_purchase_order_ids` 对既有批次校验“所有活动关联采购单”。取消批次会把 `PackingBatchOrder.active_guard` 从 `TRUE` 改为 `NULL`，但保留历史关联。

如果实现只读取活动关联，取消批次的订单集合为空。空集合天然是任何允许订单集合的子集，因此只配置 `supply_purchase_order_ids` 的用户可能命中并读取所有取消批次，形成跨订单 DataScope 泄露。

关闭标准：

1. 既有批次授权必须使用该批次全部历史 `PackingBatchOrder.order_id`，不按 `active_guard` 过滤；
2. 创建资格和“订单是否仍被活动批次占用”才使用 `active_guard=TRUE`；
3. 增加仅订单 scope 下 draft、in_progress、completed、cancelled 四状态正负测试；
4. 增加取消后原授权用户可见、其他订单 scope 用户仍 404 的回归测试。

### SC-F2-2-R1-P1-002：HTTP 冻结响应未与领域写入形成原子持久化合同

主契约第 10.1 节要求持久化 channel、HTTP 状态和冻结 API 响应，但当前 `PackingEvent` 只有领域 `response_snapshot`，没有 API channel、HTTP status、响应种类或统一 API DTO。现有领域服务在返回给 view 前完成内部事务。

如果 API 层在领域事务提交后再保存 HTTP 快照，进程可能在两步之间退出，造成“业务已成功、事件已存在、API 冻结响应缺失”。重试时只能读取活动对象重新序列化，重新引入 SC-F2-1 已关闭的幂等漂移问题。

关闭标准：

1. 冻结唯一持久化方案。建议新增 `PackingApiIdempotencyRecord`，不得把实现选择留给各 view；
2. 使用非空规范化 `scope_key`，在 MySQL 下建立 `(tenant, scope_key, idempotency_key)` 唯一约束；不得依赖含 NULL 的唯一键；
3. 记录 actor、channel、action、resource key、request hash、HTTP status、response kind、JSON body 或 label snapshot；
4. 最外层 `transaction.atomic()` 必须同时覆盖领域服务、事件/日志和 API 冻结记录；
5. actor/channel/action/resource/payload 不同必须在读取唯一记录后返回 `IDEMPOTENCY_CONFLICT`；
6. 增加“领域写后、快照保存前模拟失败”的回滚测试，证明不会留下半成功业务；
7. MySQL 同键并发首次请求只能形成一条业务结果和一条 API 幂等记录。

### SC-F2-2-R1-P1-003：DELETE JSON body 承载版本门禁不具备唯一传输语义

冻结稿使用：

`DELETE batches/{id}/boxes/{box_id}/`

并要求 JSON body 提供 `expected_version`。DELETE 请求体的处理在客户端、代理和网关间并不具有一致互操作保证；原生小程序请求层也需要额外验证。若 body 被丢弃，版本门禁会变成客户端相关行为。

关闭标准：

1. 固定改为 `POST batches/{id}/boxes/{box_id}/actions/remove/`；
2. `expected_version` 继续使用严格 JSON body；
3. 固定 `supply.packing.manage`、Idempotency-Key、成功状态和冻结响应；
4. 删除旧 DELETE 草案，不允许同时保留两种删除协议；
5. 三通道契约测试均覆盖 remove action、缺失版本、旧版本和同键重放。

### SC-F2-2-R1-P1-004：标签 PDF 的业务状态、二维码和确定性重放未唯一冻结

冻结稿定义了 POST、PDF headers 和“使用冻结快照”，但没有唯一规定：

- 哪些批次状态允许生成；
- 批次标签的页与箱对应关系；
- 二维码的精确 schema；
- PDF 元数据时间、排序、字体和随机值；
- “相同响应”是语义相同还是字节与 ETag 完全相同；
- 标签事件快照的最小字段。

不同实现可以产生互不兼容的二维码、跨版本 PDF 或每次不同的 ETag，无法形成幂等测试，也可能把内部 ID/URL 带入二维码。

关闭标准：

1. 只允许 `in_progress` 和 `completed` 且至少存在一个非空箱；`draft/cancelled` 返回 `STATE_CONFLICT`；
2. 整批 PDF 固定每个箱一页，按 `sequence asc`；单箱 PDF 固定一页；
3. 冻结二维码为无 URL 的规范 JSON，只含 schema 版本、batch_no、box_no、packing_version、standard code/version 和内容摘要；
4. 禁止 tenant ID、数据库主键、Token、内部 URL、来源字段和用户信息；
5. PDF 使用冻结事件时间和固定排序，禁止当前时间、随机 ID 或不稳定元数据；
6. 同键重放必须字节级一致且 ETag 一致；
7. 冻结 `generate_label` 事件/API 幂等记录的 label snapshot schema；
8. 增加后续布局变更后重放旧版本、不同 key 生成新版本和二维码敏感字段负向测试。

### SC-F2-2-R1-P1-005：全局装箱标准端点没有 DataScope 适用规则

`GET standards/current/` 使用 `supply.packing.view`，但 `PackingStandardVersion` 是全局标准，没有 tenant、supplier、batch 或 order 维度。冻结稿没有说明 ALL、OWN 或 CUSTOM 如何作用于该端点。

实现者可能选择“只要 permission 即可”“必须 ALL”“CUSTOM 必须命中某资源”等不同规则，造成同一权限在不同实现中的 200/403 不一致。

关闭标准：

1. 内部端固定要求活动 internal、非 miniapp channel、exact `supply.packing.view` 和至少一个合法 permission-specific scope；
2. ALL、OWN、合法 CUSTOM 均只作为“存在合法 scope”的门禁，不对全局标准做资源 ID 交集；
3. 无 scope 返回 `DATA_SCOPE_MISSING`，任何非法 scope 返回 `DATA_SCOPE_INVALID`；
4. 供应商 Web/小程序固定要求有效 external 供应商绑定，不要求 `can_self_pack`；
5. 返回规则仍限于合同登记的四个布尔键；
6. 增加 ALL/OWN/CUSTOM/无 scope/非法 scope/跨通道矩阵测试。

## 4. 非阻断观察

### OBS-001：供应商能力配置入口仍被排除

冻结稿明确不开放供应商能力配置 API，因此本轮不把它判为合同遗漏。但进入完整客户端融合前，仍需独立冻结能力配置的：

- 专用权限或现有 manage 权限选择；
- supplier DataScope；
- 乐观锁；
- 持久化幂等；
- 创建/更新审计；
- 并发更新和失败回滚。

该观察不允许在 API 实现阶段临时增加未审核端点。

## 5. 已通过的审核项

- 三类 API 通道及 Token 隔离方向正确；
- permission 集合与现有种子一致；
- exact permission 和 permission-specific scope 原则正确；
- OWN 不授权创建、CUSTOM 创建同时校验 supplier 与全部 order 的方向正确；
- 同一 CUSTOM 多维交集、多个有效 scope 并集已明确；
- 供应商只信任服务端绑定且写动作受能力开关控制；
- 内部 DTO 与供应商安全 DTO 已分离；
- 未知/禁止字段、Decimal、分页和错误信封已有明确方向；
- 首次与重放业务响应一致、授权撤销优先于历史重放的要求正确；
- F2 不推进 SC-F1 或进入 F3 的边界清晰；
- 生产隔离、真实数据和客户端发布禁令完整。

上述通过项不能抵消第 3 节的 P1。

## 6. 风险统计

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 0 | 无生产连接、真实数据或发布越界 |
| P1 | 5 | DataScope、原子幂等、删除协议、标签合同和标准端点授权需整改 |
| P2 | 0 | 本轮未单列低优先级缺陷 |
| 观察项 | 1 | 供应商能力配置入口留待独立冻结 |

## 7. 下一步

下一步仅允许：

`修复 SC-F2-2-R1-P1-001 至 SC-F2-2-R1-P1-005`

整改后必须进行：

`SC-F2-2 API 契约、权限与 DataScope P1 整改复核`

在复核结论达到 `PASS_FOR_SC_F2_2_LOCAL_API_IMPLEMENTATION` 前，不得进入 API、网页端或小程序端实现。
