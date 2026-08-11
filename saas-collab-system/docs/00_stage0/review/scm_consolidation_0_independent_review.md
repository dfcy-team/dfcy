# SC-CONSOLIDATION-0-R1 散货区域集货契约独立审核

- 日期：2026-08-08
- 审核对象：`scm_consolidation_0_domain_api_permission_contract.md`
- 审核范围：领域边界、集货状态、箱消费、API、权限、DataScope、供应商裁剪视图、附件与发运前置依赖
- 结论：`PASS_WITH_P1_REMEDIATED_LOCALLY`
- 限制：本轮未编码、未注册路由、未连接线上系统

## 1. 模型路由记录

本轮属于架构、规划与独立审核，由主代理直接完成。后续 `SC-CONSOLIDATION-1` 的模型、迁移、服务和测试是独立编码任务，按 Codex 路由交给 `luna-worker`，主代理负责复核。

## 2. P1 发现与整改

### SC-CONSOLIDATION-0-R1-P1-001 草稿更新错误复用 create 权限

- 风险：拥有创建权限但没有管理权限的用户可以修改他人集货单。
- 整改：新增并冻结 `supply.consolidation.manage`，草稿更新只使用该 exact permission 及其 permission-specific DataScope。
- 状态：`CLOSED`

### SC-CONSOLIDATION-0-R1-P1-002 发布后箱清单可被静默改变

- 风险：供应商看到的集货安排与内部实际箱清单不一致，交接证据失去版本基础。
- 整改：release 冻结站点、时间窗和当前 allocation；首期发布后禁止增删箱。仅无交接/收货事实时允许受控撤回并重新发布。
- 状态：`CLOSED`

### SC-CONSOLIDATION-0-R1-P1-003 交接提交后仍可直接取消

- 风险：货物可能已在途或到达集货点，直接释放会导致同一物理箱再次分配。
- 整改：取消只允许所有箱仍为 allocated；交接后必须走异常、确认实际位置、退回/未交付后受控释放。
- 状态：`CLOSED`

### SC-CONSOLIDATION-0-R1-P1-004 transfer 接受未验证的通用 consumer ID

- 风险：任意整数可被当成 shipment，造成孤立消费记录或跨租户引用。
- 整改：transfer API 必须读取真实同租户 Shipment、校验状态和版本后调用 packing 原子转移；`SC-SHIPMENT-0` 未通过前不开放 transfer API。
- 状态：`CLOSED_AT_CONTRACT`

### SC-CONSOLIDATION-0-R1-P1-005 假定交接附件服务已经存在

- 风险：直接接收 URL/临时路径或无租户绑定的文件会造成越权、恶意文件和证据不可追溯。
- 整改：新增 `SC-CONSOLIDATION-ATTACH-0` 前置合同；附件门禁未通过前不开放证据上传 API/客户端入口。
- 状态：`CLOSED_AT_CONTRACT`

### SC-CONSOLIDATION-0-R1-P1-006 多供应商历史数据的 DataScope 泄漏

- 风险：仅按当前 allocation 授权却返回完整历史快照，可能泄漏已移除供应商信息。
- 整改：完整内部详情要求 scope 覆盖当前和历史对象；动作按当前有效对象授权。无历史范围时只能返回不可枚举审计摘要，不返回历史商业快照。
- 状态：`CLOSED`

## 3. P2 处理决定

### P2-001 自动区域推荐

- 决定：延期。首期 region/site 全部由采购确认；建议算法不得自动发布。

### P2-002 货代/报关 API

- 决定：延期。首期只保留受控外部引用，未来另审凭据、API 配额、回调验签、对账和重试。

### P2-003 OWN/DEPARTMENT DataScope

- 决定：拒绝进入首期。多供应商聚合只允许 ALL 或结构完整的 CUSTOM。

### P2-004 发布后增补箱

- 决定：首期不支持。无交接事实时撤回、修改、重新发布；有交接事实时新建另一集货单。

## 4. 准入范围

准入 `SC-CONSOLIDATION-1` 的仅有：

- `ConsolidationSite`；
- `LooseCargoConsolidation`；
- `ConsolidationBoxAllocation`；
- append-only `ConsolidationEvent` 和领域幂等；
- draft 创建/更新、箱分配/移除、release、receive、exception、ready、cancel 的领域服务；
- Permission seed 和 DataScope 解析可以设计，但 API 路由留到下一波。

暂不准入：供应商证据上传、shipment transfer API、Web/小程序页面、第三方连接、正式数据迁移。

## 5. `SC-CONSOLIDATION-1` 强制测试

- MySQL 同箱双分配、同一集货单并发分箱、release 与 allocate/cancel 竞争；
- 跨租户、柜货、未完成批次、停用站点和不匹配区域拒绝；
- 发布快照不可变；发布后增删箱拒绝；
- handover/received 后取消拒绝；
- 集货收货不增加 `shipped_quantity`；
- DataScope ALL/CUSTOM/缺失/非法及残缺维度不拼接；
- 外部供应商 DTO 不包含其他供应商或内部字段；
- ORM save/update/bulk/admin/command 绕过及 append-only event；
- MySQL 1205/1213、幂等重放、payload 冲突和失败整批回滚。

## 6. 结论

六项 P1 已在契约层关闭，`SC-CONSOLIDATION-0` 通过本地独立审核。下一步可按模型路由启动 `SC-CONSOLIDATION-1 本地模型、迁移、领域服务与 MySQL 并发开发`。
