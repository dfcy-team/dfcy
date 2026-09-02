# SCM-REQ-V3 冲突登记表

- 编号：`SCM-REQ-V3-CONFLICTS`
- 日期：2026-08-12
- 状态：`FROZEN_FOR_RECHECK`
- 原则：冲突未登记、未裁决时一律为 `UNRESOLVED`，开发人员不得自行选择。

## 1. 状态定义

- `UNRESOLVED`：未形成唯一合同，阻断相关开发。
- `RESOLVED_BY_CONTRACT`：已经由指定合同冻结；实现仍需独立立项。
- `SUPERSEDED_TECHNICALLY`：业务要求保留，原技术实现被当前架构适配替代。

## 2. 冲突清单

| Conflict ID | 来源 | 冲突 | 裁决状态 | 唯一裁决 | 影响与迁移要求 | 下一门禁 |
| --- | --- | --- | --- | --- | --- | --- |
| `SCM-CONFLICT-001` | 后端4.4、小程序3.6/4.13；既有V2集货合同 | 散货上传货运单直发 vs 按区域集货后统一拼柜发运 | `RESOLVED_BY_CONTRACT` | `loose_cargo` 下设置互斥 `direct_dispatch` 与 `regional_groupage`；完整箱只能进入一种模式 | 新增模式字段前先盘点历史散货；已有交接/收货/报关/发货事实不得改模式；两模式附件及权限独立 | `SCM-V3-MAP-1` |
| `SCM-CONFLICT-002` | 后端采购创建字段、小程序散/柜分支；既有路线补充合同 | 下单时确定货物类型 vs 生产完成后采购决定路线 | `RESOLVED_BY_CONTRACT` | 新订单初始 `shipping_route=undecided`；生产完成后、首个下游消费前由授权采购决定 | 历史已确定路线保守映射；未知、矛盾或已有下游消费的数据进入人工队列 | `SCM-V3-MAP-1` |
| `SCM-CONFLICT-003` | 小程序4.5/9.11-25/9.79-81；MULTI合同 | 单订单一个活动批次开关 vs 多活动批次 | `RESOLVED_BY_CONTRACT` | 开关为租户级受控规则：true限制一个未结束批次，false允许多个；数量守恒始终生效 | 开关变化不追溯破坏已有批次；数据库不得恢复无条件单活动唯一约束 | `SCM-V3-MAP-1` |
| `SCM-CONFLICT-004` | 小程序4.2；当前Shipping模型 | 源发货单5态 vs 当前Shipment 8态 | `RESOLVED_BY_CONTRACT` | 源5态为跨模式展示合同；权威状态保留在直发/集货/Shipment聚合，按MAP-0派生 | 禁止客户端直接写展示状态；旧值、未知值先盘点并人工隔离 | `SCM-V3-MAP-1` |
| `SCM-CONFLICT-005` | 后端4.7/6.2、小程序4.3；当前Shipping模型 | 源货柜9态及装柜事实 vs 当前缺少独立Container聚合 | `RESOLVED_BY_CONTRACT` | 柜货必须新建独立Container权威聚合；Shipment仅复用后段运输，不承载装柜参与者、封条和调箱事实 | 新模型/迁移另行审核；实现前不得用Shipment字段伪造Container业务完成 | `SCM-V3-MAP-1`后独立Container合同 |
| `SCM-CONFLICT-006` | 两份源需求技术章节；V3第2章 | React/Taro/Supabase/RLS/RPC/Edge Function vs Vue3/原生小程序/Django/MySQL/Permission/DataScope | `SUPERSEDED_TECHNICALLY` | 完整业务不缩减，技术实现统一转换到当前协同系统架构 | 建立原实体/API/文件到当前模型、DRF API和Vue/miniapp路径映射；不导入旧认证和密钥 | 各领域/API合同 |

## 3. 裁决依据

`SCM-CONFLICT-001..005` 的唯一业务映射依据为 `scm_requirement_v3_route_state_mapping_contract.md`。`SCM-CONFLICT-006` 的依据为 `scm_requirement_baseline_v3_full_scope.md` 第2章。

以上裁决只关闭需求歧义，不等于代码、迁移或客户端已经实现。任何裁决变化都必须更新两份源需求摘要影响说明、冲突状态、路线/状态合同及追踪矩阵，并重新独立审核。

## 4. 决策责任与审计

- 业务裁决人：用户/业务负责人；本次依据用户确认的最新完整需求及已确认架构约束冻结。
- 架构适配人：架构审核；不得缩减最新业务范围。
- 实现人员：只能按已冻结合同实现，不能改动冲突状态。
- 每次变更记录日期、原因、影响对象、数据迁移、兼容和回滚方案。
