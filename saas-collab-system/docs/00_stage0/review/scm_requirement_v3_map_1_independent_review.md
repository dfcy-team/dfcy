# SCM-V3-MAP-1 独立审核

- 日期：2026-08-12
- 审核对象：`scm_requirement_v3_map_1_contract.md`、`scm_requirement_v3_map_1_trace_matrix.md`
- 审核依据：V3完整需求、追踪矩阵、冲突台账、MAP-0及当前本地代码
- 结论：`BLOCKED_PENDING_P1_REMEDIATION`
- 实现准入：`NOT_ADMITTED`

## 1. 已通过的边界

- 正确区分复用、扩展、新建和旧技术弃用。
- 没有用Shipment冒充Container，也没有用普通附件URL冒充受控证据。
- Order后段和Packing审核状态被定义为派生展示，不新增客户端双写状态源。
- internal、supplier Web、miniapp渠道及供应商绑定边界方向正确。
- 历史迁移采用DISCOVER、CLASSIFY、ADD、BACKFILL、DUAL_READ_VERIFY、SWITCH_WRITE、RETIRE分波。
- 未知状态、数量冲突、跨租户、附件不可验证和同箱双消费均要求人工隔离。
- 保留MySQL 1205/1213、正反向、ORM绕过、跨租户和幂等门禁。
- 明确本合同不授权代码、迁移或正式系统操作。

## 2. P1问题

### `SCM-V3-MAP-1-R1-P1-001`：源实体尚未逐一映射到字段级合同

当前实体表以聚合概述为主。小程序源第6章21个实体、后端5.2各表仍未逐项记录：源字段、目标字段、类型/精度、nullable/default、租户、FK删除策略、唯一/索引、PII、保留期和迁移转换。

例如 `Profile`、`ShipmentOrder`、`ShipmentPackingBatch`、`ContainerOrder`、`DispatchPhoto`、`PackingBatchReviewPhoto`、两类InspectionVideo、Notification和SiteSettings被合并描述，无法据此生成模型或迁移审核。

整改：新增逐实体逐字段矩阵；每个源实体拥有唯一Map ID，字段未映射必须明确DROP/ARCHIVE/MANUAL，不能留空。

### `SCM-V3-MAP-1-R1-P1-002`：新领域权限仍停留在权限族

合同仅说新增carrier/container/cost/clearance/report/notification/settings权限，没有冻结exact permission code、读写动作、通道和DataScope维度。开发人员仍需自行命名和决定授权，违反默认拒绝原则。

整改：逐动作冻结权限码，至少覆盖view/create/update/deactivate、allocate/review/dispatch/approve、export/settle/configure；给出ALL/CUSTOM/OWN/DEPARTMENT决定及CUSTOM必须同时覆盖的对象ID集合。

### `SCM-V3-MAP-1-R1-P1-003`：API动作没有method/path/channel/permission级合同

当前使用“purchasing actions”“Container专用API”等概念描述，没有为源7.7-7.12及网页动作冻结具体HTTP method、路径、请求关键字段、响应DTO、权限、DataScope、幂等/version、404防枚举和当前实现状态。

整改：建立API逐动作矩阵，分别覆盖internal、supplier Web、miniapp；复用接口必须记录当前真实路径，新接口使用唯一拟定路径并标PROPOSED。不得把旧RPC直接暴露。

### `SCM-V3-MAP-1-R1-P1-004`：direct_dispatch权威聚合没有确定

MAP-0冻结了散货两个互斥模式，MAP-1却只写“direct shipment或groupage Shipment创建”，没有确定直发单是扩展 `LooseCargoShipment`、新建DirectShipment，还是其他聚合。其状态、箱消费、运单附件和送达事实因此无唯一权威源。

整改：在不编码前冻结direct_dispatch的聚合选择、与Shipment/Container的关系、箱消费权、5态权威写点、取消/更正和历史映射。

### `SCM-V3-MAP-1-R1-P1-005`：迁移波次缺少量化对账与回滚触发条件

合同列出分波顺序，但没有每波输入/输出摘要、成功阈值、失败触发、回滚动作、不可逆边界和恢复后验证。`SWITCH_WRITE`后的回滚如何防止双写数据丢失也未定义。

整改：冻结每波计数/金额/数量/哈希对账项、零容忍异常、checkpoint、回滚责任、双写/单写切换策略；RETIRE前必须有备份标识和恢复演练证据。本机方案不得被视为生产执行方案。

## 3. P2问题与处理决定

### `P2-001` PII与附件保留策略不足

联系人、电话、地址、OpenID、附件hash/storage key虽有安全方向，但缺少脱敏、日志禁入、保留/删除和合法导出策略。决定：在字段矩阵增加classification/retention/redaction列；进入账户、Carrier、Notification和Attachment实现前独立审核。

### `P2-002` 报表公式版本和零分母规则未完整冻结

供应商评级仅概述公式版本，源需求的无抽检=100%、无运费=0%、异常率零订单等边界仍需确定。决定：在Rating独立合同关闭，MAP-1只建立映射，不提前编码。

### `P2-003` 客户端映射缺页面到API证据链

当前只按Web/miniapp整体分波。决定：后续矩阵增加Requirement ID→route→API Map ID→permission→test/UAT列；Android/iPhone证据仍为退出门禁。

## 4. 覆盖结论

| 审核面 | 结论 |
| --- | --- |
| 聚合边界 | 部分通过；direct_dispatch未定 |
| 21实体/后端表 | 范围覆盖，字段级不通过 |
| 状态权威/派生 | 除direct_dispatch外通过 |
| API/RPC转换 | 方向通过，具体合同不通过 |
| Permission/DataScope | 既有领域可复用，新领域不通过 |
| 三渠道隔离 | 原则通过，逐接口未证明 |
| 历史分类 | 通过 |
| 迁移/回滚 | 波次通过，量化与回滚不通过 |
| 正式系统隔离 | 通过 |

## 5. 准入决定

- MAP-1允许作为整改草案保留。
- Carrier、Container、Cost、Clearance、Notification、Setting、Rating及direct dispatch不得进入模型开发。
- 不得生成迁移、修改现有API或启动历史数据回填。
- 正式系统连接、部署、导入继续禁止。

## 6. 下一门禁

下一步执行：`SCM-V3-MAP-1 P1整改`，交付：

1. 逐实体逐字段映射矩阵；
2. exact Permission/DataScope矩阵；
3. method/path/channel/API动作矩阵；
4. direct_dispatch聚合合同；
5. 量化迁移与回滚矩阵；
6. P1整改报告。

上述P1独立复核全部通过后，才可决定首个新领域合同的开发顺序。
