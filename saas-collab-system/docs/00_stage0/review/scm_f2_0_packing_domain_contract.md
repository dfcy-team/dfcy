# SC-F2-0 装箱领域契约与审核基线

## 1. 文档控制

| 项目 | 冻结值 |
|---|---|
| 工作包 | `SC-F2-0` |
| 主题 | 装箱领域契约与审核基线冻结 |
| 文档状态 | `FROZEN_FOR_LOCAL_REVIEW` |
| 冻结日期 | 2026-07-25 |
| 执行环境 | 架构员主机、本地隔离开发环境 |
| 目标分支 | `codex/scm-f2-packing-local` |
| 父提交 | `774fb3568220349e70a8345f93b73f442f8ba22e` |
| 父代码树 | `9677e9f9e151fe532de593f0e8c22674a20f8bd0` |
| SC-F1 代码基线 | `813bd4bd63729c4ccd8c05f60c88e31174bcd408` |
| 生产授权 | 无 |
| 真实数据迁移授权 | 无 |
| 小程序发布授权 | 无 |

本文件冻结 F2 的领域边界、数据关系、状态、接口、权限和验证门禁。冻结不等于功能开发授权；后续模型、API、网页端或小程序端实现必须在独立本地开发审核中逐步准入。

## 2. 输入基线

### 2.1 源代码附件

| 来源 | 文件 | SHA-256 |
|---|---|---|
| 原供应链网页端 | `app-cwem2jetaold_app_version-d8xgo3b0aqdc.zip` | `1F7294588C05D44BA266F49F25D43DB1C27E574C0626400505C5A530D095A4D0` |
| 原供应链微信小程序端 | `微信小程序app-d5vs5nlirg1t_app_version-d8yd2egp8zr4.zip` | `EB3BECB5BB8AA314222F1914CB8B3C107CB0C82C0FF03B7B3A619F41877A98A0` |

源代码只作为业务语义和历史风险证据，不作为目标运行时依赖，不直接执行其中 Supabase migration、Edge Function、RLS 或客户端数据库访问代码。

### 2.2 目标系统基线

目标系统继续使用：

- Vue 3 网页端；
- Django/DRF 后端；
- MySQL 8；
- 原生微信小程序；
- 现有租户、身份、RBAC、DataScope、审计和小程序 Token 通道。

F2 复用 SC-F1 的 `SupplyPurchaseOrder` 和 `SupplyPurchaseOrderLine`，不得重新建立平行采购单主数据，也不得破坏 SC-F1 已冻结的状态动作与 ORM 防绕过约束。

## 3. 立项目标

F2 建立可审计的装箱聚合，使内部人员和受控供应商能够：

1. 从已生产完成的供应链采购单创建装箱批次；
2. 在同一供应商边界内选择一个或多个采购单；
3. 创建箱号并登记每箱采购单行、SKU 和数量；
4. 防止欠装、超装、跨租户和跨供应商装箱；
5. 完成批次并冻结箱明细；
6. 生成本地外箱标签；
7. 对完成后的变更执行申请、审批、原子应用和审计；
8. 为后续 F3 提供只读、稳定且可验证的“装箱完成”交接结果。

## 4. 范围冻结

### 4.1 F2 纳入范围

- 装箱标准的版本化读取；
- 供应商自助装箱能力控制；
- 同供应商多采购单装箱能力控制；
- 装箱批次的创建、列表、详情和草稿取消；
- 批次—采购单显式关联；
- 箱号、箱序号、重量、体积和备注；
- 箱内采购单行与装箱数量；
- 剩余数量和整单完成校验；
- 草稿/进行中编辑；
- 装箱完成动作；
- 单箱和整批外箱标签；
- 完成后变更申请及内部审核；
- 不可变动作事件和操作日志；
- 本地 Mock/虚构数据和自动化测试。

### 4.2 F2 明确排除

- `ready_to_ship`、`shipping_review_pending`、`shipping`、`shipped` 状态动作；
- 提交装柜、待装柜、货柜、装柜方案和箱柜分配；
- 散货发运、运单、物流追踪、报关和结算；
- 发货前照片、装车前照片、装柜过程照片、封条照片、视频和抽检审核；
- 对象存储、真实附件迁移、外部文件 URL 和真实打印机集成；
- 线上 Supabase/MySQL 连接、双写、同步、切流或生产数据导入；
- 微信小程序上传、体验版、审核或正式发布；
- 真实通知、短信、邮件、企业微信或第三方接口调用。

名称中包含 “box change” 但实际涉及货柜或装柜的源功能归 F3，不得因名称相似进入 F2。

## 5. 冻结业务规则

### 5.1 可装箱采购单

采购单必须同时满足：

- 与操作者属于同一租户；
- 属于同一个有效 `SupplierMaster`；
- 状态严格为 `production_completed`；
- 采购单至少包含一条正数量明细；
- 不存在其他未取消的装箱批次关联。

一个采购单在 F2 首期最多关联一个未取消装箱批次。不得从 `accepted`、`in_production` 或 `ready_to_ship` 等状态创建装箱批次。

### 5.2 多采购单和混箱

- 一个批次可以关联多个采购单，但所有采购单必须属于同一供应商；
- 供应商端默认禁止多采购单批次，只有 `can_mix_order_packing=true` 才允许；
- 内部端也必须显式选择同一供应商，不能使用首个订单的供应商代替完整校验；
- 一个箱可以包含多个 SKU 或多个采购单行；
- 混箱时标签必须列出箱内所有 SKU、所属采购单号和数量；
- 装箱标准仍推荐“单箱、单采购单、单 SKU”，但该推荐不作为数据库硬拒绝条件。

### 5.3 数量

- 每个箱明细数量必须为正整数；
- 箱明细必须引用批次已关联采购单的有效采购单行；
- 同一箱内相同采购单行只保留一个逻辑明细；
- 同一采购单行在整个批次的累计装箱数量不得超过采购数量；
- 完成批次时，每条已关联采购单行累计装箱数量必须恰好等于采购数量；
- 服务端发现超量、欠量或无效引用时必须拒绝，不得使用 `LEAST`、截断或静默修正；
- 客户端计算的剩余数量只用于展示，服务端事务校验是唯一业务边界。

### 5.4 箱和标签

- 箱号由服务端分配，格式暂定 `{batch_no}-B{sequence:03d}`；
- `sequence` 在批次内唯一且只增不复用；
- 空箱不得保存；
- 重量和体积可为空；提供时必须大于零并使用 `Decimal`；
- 标签固定包含版本、批次号、箱号、采购单号、SKU、数量和混箱标识；
- 二维码不得包含用户 Token、数据库凭据、内部自增主键或可越权查询的匿名 URL；
- PDF 由目标后端按请求即时生成并流式返回，不持久化到对象存储；
- 首期支持单箱 PDF 与整批 PDF，不包含物理打印机驱动。

### 5.5 完成后变更

完成批次后，批次、箱和箱明细不可直接修改或删除。

变更流程冻结为：

1. 供应商或内部人员提交 `PackingChangeRequest`，包含原因、期望版本和完整拟变更内容；
2. 具有审核权限的内部人员批准或驳回；
3. 批准时服务端重新锁定批次、采购单和采购单行，重新执行全部范围及数量校验；
4. 校验通过后原子应用新版本，批次保持 `completed`，版本号递增；
5. 记录申请、审核、应用前后快照和不可变事件；
6. 申请人不得审核本人提交的申请。

变更请求不允许改变租户、供应商或关联到其他供应商的采购单。涉及装柜、货柜或发运的变更必须转交 F3。

## 6. 领域模型冻结

```text
Tenant
  └─ PackingBatch
       ├─ PackingBatchOrder ── SupplyPurchaseOrder
       ├─ PackingBox
       │    └─ PackingBoxItem ── SupplyPurchaseOrderLine
       ├─ PackingChangeRequest
       └─ PackingEvent

PackingStandard
  └─ PackingStandardVersion
```

### 6.1 `PackingBatch`

建议字段：

- `tenant`
- `supplier`
- `batch_no`
- `status`
- `note`
- `version`
- `standard_version`
- `creation_idempotency_key`
- `creation_request_hash`
- `source_system/source_table/source_record_id/source_updated_at/source_payload_hash`
- `created_by/created_at/updated_at/completed_at/cancelled_at`

约束：

- `(tenant, batch_no)` 唯一；
- `(tenant, creation_idempotency_key)` 唯一；
- 完整来源三元组唯一；
- 供应商、创建人和标准版本必须属于同租户或全局标准边界。

### 6.2 `PackingBatchOrder`

建议字段：

- `tenant`
- `batch`
- `order`
- 创建时间

约束：

- `(batch, order)` 唯一；
- 一个采购单最多存在一个未取消批次关联；
- 批次、采购单、供应商和租户必须一致。

目标模型必须使用此显式关联表。禁止复制源系统历史上 `purchase_orders.packing_batch_id` 与 `packing_batches.order_id` 并存的关系漂移。

### 6.3 `PackingBox`

建议字段：

- `tenant`
- `batch`
- `sequence`
- `box_no`
- `weight`
- `volume`
- `note`
- `created_at/updated_at`

约束：

- `(batch, sequence)` 唯一；
- `(tenant, box_no)` 唯一；
- 重量、体积为空或大于零；
- 批次完成后禁止直接写入。

### 6.4 `PackingBoxItem`

建议字段：

- `tenant`
- `box`
- `order_line`
- `quantity`
- `order_no_snapshot`
- `sku_code_snapshot`
- `product_name_snapshot`
- `created_at/updated_at`

约束：

- `(box, order_line)` 唯一；
- 数量大于零；
- `order_line.order` 必须属于 `PackingBatchOrder`；
- 租户和供应商关系一致；
- 快照由服务端从 SC-F1 记录生成，客户端不得指定或覆盖。

### 6.5 `PackingEvent`

不可变事件动作至少包括：

- `create_batch`
- `add_box`
- `update_box`
- `remove_box`
- `complete_batch`
- `cancel_batch`
- `submit_change`
- `approve_change`
- `reject_change`
- `apply_change`
- `generate_label`

事件保存幂等键、请求哈希、操作者类型、批次版本、前后状态、最小必要负载、响应快照和创建时间。事件表禁止更新、批量写入和删除。

### 6.6 `PackingStandard` 与版本

首期至少冻结一个全局标准版本：

- 推荐单箱单采购单单 SKU；
- 混箱标签必须完整列出 SKU、采购单号及数量；
- 空箱禁止；
- 完成时必须整批精确装完。

批次创建时绑定标准版本，后续标准更新不得追溯改变已创建批次的校验语义。

## 7. 状态契约

### 7.1 批次状态

```text
draft ──start──> in_progress ──complete──> completed
  │                   │
  └────cancel─────────┴──────────────> cancelled
```

规则：

- 创建空批次后为 `draft`；
- 保存第一个有效箱时原子进入 `in_progress`；
- `draft` 或 `in_progress` 可以取消；
- `completed` 只能通过批准的变更请求产生新版本，不回退状态；
- `cancelled` 为终态；
- `pending_loading` 不属于 F2。

### 7.2 变更请求状态

```text
pending ──approve/apply──> approved
   └──────reject─────────> rejected
```

批准和应用必须处于同一个事务；任何二次校验失败均不得形成 `approved`。

### 7.3 与 SC-F1/F3 的交接

- F2 只读取状态为 `production_completed` 的 SC-F1 采购单；
- F2 不直接修改 `SupplyPurchaseOrder.status`；
- F2 对 F3 暴露只读结果：批次 `completed`、版本、箱数、总数量、重量、体积和标签数据；
- F3 未来负责从 `production_completed` 到 `ready_to_ship` 及后续状态的受控动作；
- F3 消费批次时必须保存所消费的批次版本；若 F2 批准后续变更，必须由 F3 的独立异常/重审契约处理，F2 不隐式改写物流记录。

## 8. API 契约草案

### 8.1 内部网页端

前缀：`/api/internal/packing/`

| 方法 | 路径 | 语义 |
|---|---|---|
| `GET/POST` | `batches/` | 列表、幂等创建 |
| `GET` | `batches/{id}/` | 详情 |
| `POST` | `batches/{id}/boxes/` | 幂等新增箱 |
| `PUT` | `batches/{id}/boxes/{box_id}/` | 更新未完成箱 |
| `DELETE` | `batches/{id}/boxes/{box_id}/` | 删除未完成箱 |
| `POST` | `batches/{id}/actions/complete/` | 完成批次 |
| `POST` | `batches/{id}/actions/cancel/` | 取消批次 |
| `GET` | `batches/{id}/labels.pdf` | 整批标签 |
| `GET` | `boxes/{box_id}/label.pdf` | 单箱标签 |
| `GET/POST` | `batches/{id}/change-requests/` | 读取、提交变更 |
| `POST` | `change-requests/{id}/actions/approve/` | 审核并应用 |
| `POST` | `change-requests/{id}/actions/reject/` | 驳回 |
| `GET` | `standards/current/` | 当前装箱标准 |

### 8.2 供应商网页端

前缀：`/api/external/supplier/packing/`

只允许当前登录账号所绑定的有效供应商；不得接受或信任客户端传入的 `supplier_id`。

开放列表、详情、受能力控制的创建/箱管理/完成、标签读取和变更申请；不开放变更审核。

### 8.3 原生微信小程序

前缀：`/api/miniapp/supply-chain/packing/`

能力与供应商网页端一致，但必须使用现有小程序 Token 通道。小程序 Token 不得访问内部或普通外部 API；普通 Web Token 不得访问小程序 API。

### 8.4 通用写接口规则

- `POST/PUT/DELETE` 和动作 API 必须携带 `Idempotency-Key`；
- 同一幂等键、相同操作者和相同请求负载返回已保存响应；
- 同一幂等键负载不同或操作者不同返回 `409`；
- 越权对象统一返回范围化 `404` 或既有安全错误，不暴露对象是否存在；
- 状态冲突、并发版本冲突、超量和幂等冲突返回 `409`；
- 请求字段错误返回 `400`，业务规则不满足按现有错误契约返回 `422`；
- 列表和详情必须服务端执行租户、DataScope、供应商三重过滤。

## 9. 权限与数据范围

内部权限代码冻结为：

- `supply.packing.view`
- `supply.packing.create`
- `supply.packing.manage`
- `supply.packing.complete`
- `supply.packing.change.review`

DataScope 自定义配置允许：

- `supplier_ids`
- `packing_batch_ids`
- `supply_purchase_order_ids`

要求：

- 权限存在但无 DataScope 时拒绝；
- 创建和关联采购单必须同时验证供应商范围与采购单范围；
- `OWN` 仅表示由当前内部用户创建的批次，不代表可以越过供应商范围引用采购单；
- 外部供应商依赖账号类型、有效供应商绑定和能力开关，不继承内部权限；
- `can_self_pack` 默认 `false`；
- `can_mix_order_packing` 默认 `false`；
- 前端按钮隐藏仅用于体验，后端权限、范围和状态检查是安全边界。

## 10. MySQL 事务与并发契约

### 10.1 锁顺序

所有装箱写动作使用 `transaction.atomic()`，并固定锁顺序：

1. `PackingBatch`；
2. 按主键升序的 `SupplyPurchaseOrder`；
3. 按主键升序的 `SupplyPurchaseOrderLine`；
4. `PackingBox`；
5. 相关幂等事件或变更请求。

统一锁顺序用于降低死锁概率。数据库死锁仍应转换为可重试错误并保留请求幂等性。

### 10.2 必须防止的竞争

- 同一组采购单并发创建两个批次；
- 同一批次并发生成相同箱序号；
- 两个请求并发装入同一采购单行导致累计超量；
- 完成动作与新增/更新/删除箱并发；
- 完成动作与变更申请/审核并发；
- 相同幂等键并发首次写入；
- 审核人并发批准同一变更；
- PDF 生成读取到跨版本拼接数据。

### 10.3 ORM 防绕过

受控字段、箱明细和事件必须阻止：

- `QuerySet.update()`；
- `bulk_update()`；
- 未经领域服务的 `bulk_create()`；
- 已完成记录的实例 `save()`；
- 受审计记录的 `delete()`；
- 通过 serializer 任意写入状态、租户、供应商、快照或版本。

数据库唯一约束、检查约束与领域服务必须同时存在，不能只依赖客户端或 Django `clean()`。

## 11. 客户端范围

### 11.1 Vue 网页端

内部端首期页面：

- 装箱批次列表；
- 新建/编辑批次；
- 批次详情；
- 变更审核；
- 标签预览/下载。

供应商端首期页面：

- 我的装箱批次；
- 创建批次；
- 批次详情与装箱；
- 标签下载；
- 完成后变更申请。

路由必须登记到 fail-closed `routeCapabilities`，内部页面按冻结权限代码控制，供应商页面限制为 external 用户。

### 11.2 原生微信小程序

首期页面：

- 装箱批次列表；
- 新建批次；
- 批次详情与箱明细；
- 标签下载/打开；
- 变更申请。

不迁移源 Taro 页面，不引入发货前审核页面，不增加照片和视频上传能力。

## 12. 验证矩阵

### 12.1 模型和服务

- 同租户、供应商、采购单和采购单行一致性；
- 来源三元组与创建幂等键唯一；
- 空箱、零数量、负数、超量和欠量拒绝；
- 混箱合并规则；
- 批次完成后直接修改拒绝；
- 变更申请人和审核人分离；
- append-only 事件；
- ORM 批量写入和实例写入绕过拒绝。

### 12.2 权限和通道

- 内部权限无 DataScope 拒绝；
- 自定义供应商/采购单/批次范围；
- 跨租户、跨供应商列表和详情不可见；
- 外部账号不能指定其他 `supplier_id`；
- 无效或停用供应商绑定拒绝；
- `can_self_pack=false` 和 `can_mix_order_packing=false`；
- Mini Program Token、Web Token 和内部 Token 通道交叉拒绝；
- 响应字段最小化，不泄露采购价格、内部用户敏感字段或来源载荷。

### 12.3 MySQL 并发

- 并发创建同订单批次只有一个成功；
- 并发新增箱序号唯一；
- 并发装箱累计数量不超采购数量；
- 并发完成与箱修改只有符合版本的一方成功；
- 并发批准变更只应用一次；
- 幂等重放返回一致响应；
- 幂等键负载冲突返回 `409`。

### 12.4 API 和客户端

- 内部、供应商网页端和小程序端合同测试；
- 标签单箱/整批数据一致；
- 标签不包含内部 ID、Token 或匿名外链；
- 路由能力未登记时默认拒绝；
- 加载、空数据、错误、无权限和状态冲突界面；
- 小程序 Mock 模式不访问网络；
- 所有测试只使用虚构数据。

### 12.5 Migration

- MySQL 8 空库完整升级；
- 从当前基线升级；
- migration 可逆；
- 约束和索引名称符合 MySQL 长度要求；
- 不执行 Supabase SQL，不依赖 PostgreSQL RLS、RPC 或 UUID 主键。

## 13. 审核门禁

### 13.1 进入模型开发

必须满足：

- 本契约与检查表独立提交；
- `P0=0`；
- 所有冻结决策有明确结论；
- 未纳入原有脏工作区文件；
- 开发仍只在架构员主机本地执行。

### 13.2 进入 API/客户端开发

必须满足：

- 模型、migration 和领域服务审核通过；
- MySQL 并发创建、并发动作和 ORM 绕过测试通过；
- 权限/DataScope/供应商绑定测试通过；
- OpenAPI/错误契约与字段最小化审核通过。

### 13.3 本地融合完成

必须满足：

- 内部、供应商网页端和原生小程序端均通过自动化与本地手工验收；
- F2/F3 状态边界未被突破；
- 无生产连接、真实数据、真实通知或小程序发布；
- 固定代码提交和测试证据可复现；
- 独立执行最终本地融合审核。

## 14. 冻结决策

| 编号 | 决策 | 结论 |
|---|---|---|
| F2-D01 | F2 终态 | `completed`，不转换采购单 `ready_to_ship` |
| F2-D02 | 批次—订单关系 | 显式 `PackingBatchOrder` 多对多关联 |
| F2-D03 | 供应商边界 | 一个批次严格一个供应商 |
| F2-D04 | 多订单 | 能力开关控制，默认关闭 |
| F2-D05 | 完成条件 | 所有关联采购单行必须精确装完 |
| F2-D06 | 混箱 | 允许，但标签必须列出完整订单/SKU/数量 |
| F2-D07 | 标签 | 目标后端即时生成 PDF，不持久化、不接打印机 |
| F2-D08 | 完成后变更 | 申请、异人审核、原子应用、版本递增 |
| F2-D09 | 照片/视频/装柜 | 全部归 F3 |
| F2-D10 | 数据库 | MySQL 原生建模，不复制 Supabase SQL/RLS |
| F2-D11 | 客户端 | Vue 3 + 原生微信小程序，不迁移 Taro 运行时 |
| F2-D12 | 生产保护 | 无生产连接、迁移、双写、切流或发布授权 |

冻结决策如需修改，必须新增带原因、影响、审批结论和替代日期的变更记录，不得直接覆盖历史结论。

## 15. SC-F2-0 结论

在本文件和配套检查表完成独立本地提交后，`SC-F2-0` 可判定为：

`PASS_FOR_LOCAL_MODEL_DEVELOPMENT`

该结论只允许下一阶段建立本地 Django 模型、MySQL migration、领域服务骨架和自动化测试，不自动授权 API、网页端、小程序端、真实数据迁移或任何生产操作。
