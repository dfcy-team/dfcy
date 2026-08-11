# SC-F2-2 API 契约、权限与 DataScope P1 整改复核报告

## 1. 复核结论

复核结论：

`PASS_FOR_SC_F2_2_LOCAL_API_IMPLEMENTATION`

`SC-F2-2-R1-P1-001` 至 `SC-F2-2-R1-P1-005` 的合同关闭条件全部通过。
本轮未发现新增 P0、P1 或 P2；整改稿已具备唯一、可实现、可自动化验收的 API、
权限、DataScope、原子幂等和标签合同，可以进入架构员主机上的 SC-F2-2 本地 API 实现。

该结论不授权网页端或小程序端实现、联调、发布、数据迁移、双写、同步、切流、
线上连接或生产部署。

## 2. 复核基线

| 项目 | 复核值 |
| --- | --- |
| 分支 | `codex/scm-f2-packing-local` |
| SC-F2-1 最终归档 | `71341fb5e85307bdb0ed505ef65c1df2d7a901b9` |
| SC-F2-2 首轮冻结 | `b8d701f3e56e4828a5950da6ca4b9b7685a2a63b` |
| SC-F2-2 独立审核 | `c5093d5689615d55688a7d5e3a0407354de0e43d` |
| P1 整改提交 | `cee176476058853e77975d093dffc5d71fe812ef` |
| 主契约版本 | `v2-p1-remediated` |
| 复核日期 | 2026-07-28 |
| 执行环境 | 架构员主机本地隔离环境 |
| 生产连接或变更 | 无 |

被复核文件及 SHA-256：

| 文件 | SHA-256 |
| --- | --- |
| `docs/03_api/supply_chain_f2_packing_api_contract.md` | `1bc31671f79908859b5204c9c25bb61431cfb2db0da2e1efaff37daf22391cfe` |
| `docs/00_stage0/review/scm_f2_2_api_permission_datascope_review_baseline.md` | `979a6e4421493e38a4b87a802277716ea2f62aff6eb17c5a7f397d984558328a` |
| `docs/00_stage0/review/scm_f2_2_p1_remediation_report.md` | `51089315281c60b3cc6474450a1740a5f102942b5c0bce180a510d61c55d500a` |

复核报告不回写上述被复核文件，避免在得出结论后改变审核输入。

## 3. P1 逐项复核

### SC-F2-2-R1-P1-001：取消批次订单 DataScope

复核结果：`PASS`

- 既有批次授权固定读取全部历史 `PackingBatchOrder.order_id`。
- `active_guard` 明确不参与既有资源授权，只用于创建资格、业务校验和活动占用。
- `draft`、`in_progress`、`completed`、`cancelled` 四状态已进入实现验收矩阵。
- 取消后原订单 scope 可见、其他订单 scope 返回 404 的回归条件已冻结。

空活动关联集合不再能够形成跨订单 DataScope 自动通过。

### SC-F2-2-R1-P1-002：API 冻结响应原子持久化

复核结果：`PASS`

- 唯一 HTTP 幂等来源固定为 `PackingApiIdempotencyRecord`。
- `scope_key` 非空，并固定 MySQL
  `(tenant_id, scope_key, idempotency_key)` 唯一约束。
- 唯一约束不依赖 nullable 资源列，也不通过 actor、channel、action 或 hash
  扩展唯一键来掩盖冲突。
- actor、channel、action、resource、request hash、HTTP status、response kind、
  JSON body 或 label snapshot 的持久化字段完整。
- API 最外层 `transaction.atomic()` 覆盖领域写入、事件、日志、响应序列化和 API 记录。
- 快照保存前故障回滚、MySQL 同键并发单结果测试已经进入实现门禁。

合同已消除“领域事务先提交、HTTP 冻结响应后保存”的半成功窗口。

### SC-F2-2-R1-P1-003：移除箱传输协议

复核结果：`PASS`

- 内部端、供应商 Web 和小程序统一使用
  `POST batches/{id}/boxes/{box_id}/actions/remove/`。
- `expected_version` 由严格 JSON body 承载。
- exact permission、供应商能力、Idempotency-Key、200 状态和冻结响应均已固定。
- 旧 DELETE 路径只作为明确禁止项出现，不注册、不兼容、不保留别名。
- 三通道、缺失版本、过期版本、同键重放和旧路由不可达均已列入验收矩阵。

移除箱不再依赖 DELETE request body 的客户端和网关互操作行为。

### SC-F2-2-R1-P1-004：确定性标签 PDF

复核结果：`PASS`

- 仅 `in_progress|completed` 且存在非空箱时允许生成标签。
- 批次标签按箱 `sequence asc` 一箱一页；箱标签固定一页。
- QR 固定为非 URL 规范 JSON，schema、字段顺序、摘要算法和敏感字段禁止清单完整。
- 标签快照冻结 event time、标准、布局、渲染器、字体摘要、文件名、箱内容和 QR payload。
- PDF 禁止当前时间、随机标识和不稳定元数据；ETag 固定为最终字节 SHA-256 强 ETag。
- 同 key 重放要求 PDF 逐字节一致，布局升级后仍按冻结资产重建旧版本。
- `generate_label` 事件和 API 幂等记录使用同一业务快照且不保存 PDF 二进制。

标签合同已经能够形成确定性生成、敏感信息负向检查和跨布局版本重放测试。

### SC-F2-2-R1-P1-005：全局当前标准 DataScope

复核结果：`PASS`

- 内部端固定要求活动 internal、正确 channel、exact `supply.packing.view`
  和至少一个合法 permission-specific scope。
- ALL、OWN 和合法 CUSTOM 仅满足合法 scope 门禁，不对全局标准执行资源 ID 交集。
- 无 scope 与任一非法 scope 分别固定为
  `DATA_SCOPE_MISSING` 和 `DATA_SCOPE_INVALID`。
- 供应商 Web 和小程序固定要求有效 external 供应商绑定，不要求 `can_self_pack`。
- 输出仍只允许已登记的四个 boolean 规则键。
- ALL、OWN、CUSTOM、缺失、非法 scope 和三通道矩阵已进入实现验收。

全局标准端点不再存在“仅 permission”“必须 ALL”或“CUSTOM 资源相交”等实现分歧。

## 4. 一致性与边界复核

| 检查项 | 结果 |
| --- | --- |
| 整改提交文件范围 | PASS，仅 3 份 SC-F2-2 文档 |
| 契约权限与权限种子 | PASS，严格等于 5 个 `supply.packing.*` 权限 |
| 内部、供应商 Web、小程序通道隔离 | PASS |
| 错误码和防枚举顺序 | PASS |
| MySQL 非空唯一键与并发语义 | PASS |
| JSON/PDF 冻结响应和重放语义 | PASS |
| backend/frontend/miniapp 相对 SC-F2-1 基线 | PASS，未变化 |
| F2 URL、view、serializer | PASS，尚未创建 |
| 线上连接、真实数据、通知或部署 | PASS，均未发生 |

权限集合复核值：

- `supply.packing.view`
- `supply.packing.create`
- `supply.packing.manage`
- `supply.packing.complete`
- `supply.packing.change.review`

## 5. 风险统计

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 0 | 无生产或数据安全越界 |
| P1 | 0 | 首轮 5 项均已关闭 |
| P2 | 0 | 未发现新的合同歧义 |
| 观察项 | 1 | 供应商能力配置 API 继续留待独立冻结 |

观察项不阻断 SC-F2-2 本地 API 实现，但实现阶段不得临时增加供应商能力配置端点。

## 6. 下一阶段准入

允许的下一步：

`SC-F2-2 本地 API、权限、DataScope 与原子幂等实现`

实现必须严格以本报告记录 SHA-256 的 `v2-p1-remediated` 契约为输入，并至少完成：

1. `PackingApiIdempotencyRecord` 模型、MySQL migration 和并发/回滚测试；
2. 三通道 API、exact permission、permission-specific DataScope 和防枚举；
3. POST remove action，旧 DELETE 路由不可达；
4. 确定性标签快照、PDF、QR 和 ETag 测试；
5. 当前标准 ALL/OWN/CUSTOM/缺失/非法 scope 与外部绑定测试；
6. backend 自动化测试及 MySQL 8 专项测试。

仍不允许网页端或小程序端实现、真实外部调用、线上数据库连接、数据同步、切流或生产部署。
