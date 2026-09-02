# SCM-V3-MAP-1 逐域追踪矩阵

| Map ID | 最新需求范围 | 当前目标 | 处理 | 状态 | 下一合同/证据 |
| --- | --- | --- | --- | --- | --- |
| `MAP-ACC-001` | 用户/账号/微信身份 | accounts profiles + MiniAppIdentity | 复用扩展 | PARTIAL | 账号/偏好合同 |
| `MAP-PERM-001` | 内置/自定义角色、菜单 | Permission/Role/DataScope | 技术替代 | PARTIAL | 权限矩阵审核 |
| `MAP-PROD-001` | 分类/商品 | ProductCategory/SPU/SKU | 复用扩展 | PARTIAL | 字段差异审核 |
| `MAP-SUP-001` | 供应商 | SupplierMaster/profile/capability | 复用扩展 | PARTIAL | PII/绑定审核 |
| `MAP-CARRIER-001` | 货运方 | CarrierMaster | 新建 | MISSING | Carrier领域合同 |
| `MAP-PO-001` | 订单/明细/生产 | SupplyPurchaseOrder/Line/Event | 复用扩展 | PARTIAL | 状态/字段/API审核 |
| `MAP-FUL-001` | 履约累计 | Fulfillment projection/event | 复用 | IMPLEMENTED_CORE | 守恒回归 |
| `MAP-PACK-001` | 批次/箱/明细/审核/标签 | packing + files | 复用扩展 | PARTIAL | admin_status/开关/证据类别 |
| `MAP-ATT-001` | 图片/视频/附件 | ControlledAttachment | 合并转换 | PARTIAL | 生产存储/下载合同 |
| `MAP-SET-001` | site_settings/业务开关 | SupplyChainSetting | 新建 | MISSING | Settings合同 |
| `MAP-CONS-001` | 区域集货 | consolidation聚合 | 复用 | IMPLEMENTED_CORE | V3 DTO补齐 |
| `MAP-SHIP-001` | 散货发货/后段物流 | direct dispatch + LooseCargoShipment | 扩展 | PARTIAL | 双模式领域合同 |
| `MAP-CONT-001` | 货柜9态/装柜/封条 | Container聚合 | 新建 | MISSING | Container合同 |
| `MAP-BOXCHG-001` | 箱号调换 | ContainerBoxChangeRequest/Event | 新建 | MISSING | 调箱审批合同 |
| `MAP-COST-001` | 订单/货运/供应商费用 | Cost/Allocation/Settlement | 新建 | MISSING | 费用合同 |
| `MAP-CLEAR-001` | 仓库清单 | Clearance聚合 | 新建 | MISSING | 清单合同 |
| `MAP-NOTIFY-001` | 站内/微信/飞书/偏好 | Notification/Attempt/Preference | 新建映射 | MISSING | 通知合同 |
| `MAP-RATING-001` | 供应商评级/Excel | Versioned report query/export | 新建 | MISSING | 评级数据合同 |
| `MAP-WEB-001` | 后端网页完整模块 | Vue供应链页面族 | 分波扩展 | PARTIAL | WEB-CORE/COST/NOTIFY |
| `MAP-MINI-001` | 小程序完整页面/81验收 | 原生小程序页面族 | 分波扩展 | PARTIAL | MINIAPP-CORE/ACCOUNT |
| `MAP-HIST-001` | Supabase历史数据 | discover/classify/add/backfill/verify/switch/retire | 受控迁移 | NOT_AUTHORIZED | 独立迁移立项 |

## API与渠道矩阵

| 渠道 | 当前可复用 | 必须新增/扩展 | 安全边界 |
| --- | --- | --- | --- |
| internal Web | purchasing/packing/consolidation/shipping/accounts | carrier/container/cost/clearance/report/notification/settings | exact permission + DataScope + state/version |
| supplier Web | supplier auth、orders、packing、consolidation | direct shipment、container、notification/settings | supplier binding + capability；裁剪DTO |
| miniapp | auth、orders、packing API、consolidation assignment | 完整装箱UI、发货、货柜、消息、记录、账号 | miniapp identity + supplier binding；真机门禁 |
| internal miniapp（如启用） | 无默认业务授权 | 需独立合同 | 不因移动渠道弱化Permission/DataScope |

## 历史分类矩阵

| 分类 | 判定 | 处理 |
| --- | --- | --- |
| `AUTO_MAPPABLE` | 租户/外键/状态/数量均可证明 | 幂等回填并对账 |
| `MASTERDATA_MISSING` | 货运方、仓库、供应商等引用缺主数据 | 补受控主数据后重跑 |
| `STATE_CONFLICT` | 源状态与事实不一致或未知 | 人工队列，阻断下游 |
| `QUANTITY_CONFLICT` | 预留/装箱/发货超完工或累计不守恒 | 人工核对，不按比例猜测 |
| `TENANT_CONFLICT` | 关联对象跨租户或租户缺失 | 隔离，不自动迁移 |
| `ATTACHMENT_UNVERIFIED` | URL不可取、无hash/扫描/绑定 | 不标accepted；重新采集或人工决定 |
| `DUPLICATE_ACTIVE_BOX` | 同箱多有效消费 | 阻断，人工选择受控撤销路径 |
| `READY_FOR_SWITCH` | 新旧读取、事件重建、权限和并发均通过 | 纳入切换批次 |

## 审核门

本矩阵只证明映射范围已冻结，不证明 `MISSING/PARTIAL` 已实现。下一步为 `SCM-V3-MAP-1 独立审核`，不得直接生成迁移或修改接口。
