# SC-F2-1 本地模型与领域服务开发报告

## 1. 执行结论

`SC-F2-1` 已按 `SC-F2-0` 冻结契约完成本地模型、MySQL migration、领域服务和自动化测试开发。

阶段结论：

`PASS_FOR_LOCAL_CODE_REVIEW`

该结论只允许进入 SC-F2-1 本地代码审核，不授权 API、网页端、微信小程序端、真实数据迁移、生产连接或部署。

## 2. 基线与执行边界

| 项目 | 值 |
|---|---|
| 分支 | `codex/scm-f2-packing-local` |
| SC-F2-0 提交 | `baeaa92ab857c64da01dbee133abe0cad7fa3e80` |
| 执行日期 | 2026-07-28 |
| 执行环境 | 架构员主机、本地隔离环境 |
| 目标数据库 | MySQL 8 |
| 测试数据 | 全部为自动生成的虚构数据 |
| 线上系统连接 | 无 |
| 真实数据导入 | 无 |
| API/客户端开发 | 未进入 |
| 小程序发布 | 无 |

本轮没有执行源 Supabase migration、RLS、RPC、Edge Function、对象存储或客户端直连数据库代码。

## 3. 实现范围

### 3.1 Django 应用

新增独立 `apps.packing` 应用，并注册到 `INSTALLED_APPS`。

未将装箱逻辑放入现有 `purchasing` 或 `suppliers.SupplierShipment`，保持采购、装箱和后续物流领域分离。

### 3.2 模型

已实现：

- `PackingStandardVersion`
- `PackingSupplierCapability`
- `PackingBatch`
- `PackingBatchOrder`
- `PackingBox`
- `PackingBoxItem`
- `PackingChangeRequest`
- `PackingEvent`

关键设计：

- 所有租户业务记录显式保存 `tenant_id`；
- 批次严格绑定一个供应商；
- 批次—采购单使用显式关联表；
- `active_guard=TRUE/NULL` 配合唯一约束，保证一个采购单只进入一个有效批次，同时保留取消历史；
- 箱序号在批次内唯一；
- 箱号在租户内唯一；
- 箱内同一采购单行唯一；
- 数量、重量、体积和版本具有数据库检查约束；
- 来源三元组和创建幂等键具有唯一约束；
- 装箱事件为不可变审计记录。

### 3.3 冻结标准和权限

首次 migration 写入 `packing-v1` 冻结标准，包含：

- 禁止空箱；
- 完成时必须精确覆盖所有采购单行；
- 混箱标签必须列出明细；
- 推荐单箱单采购单单 SKU。

新增权限种子：

- `supply.packing.view`
- `supply.packing.create`
- `supply.packing.manage`
- `supply.packing.complete`
- `supply.packing.change.review`

API/DataScope 校验将在后续独立阶段实现，本轮未开放任何路由。

## 4. 领域服务

### 4.1 供应商能力

实现 `set_supplier_packing_capability`：

- 只有内部用户可以配置；
- `can_self_pack` 默认关闭；
- `can_mix_order_packing` 默认关闭；
- 供应商、操作者和租户必须一致。

### 4.2 批次创建

实现 `create_packing_batch`：

- 采购单必须处于 `production_completed`；
- 供应商主档必须有效；
- 禁止跨租户、跨供应商批次；
- 外部供应商必须具有自助装箱能力；
- 多采购单时外部供应商必须具有混订单能力；
- 锁定采购单后检查活动装箱关联；
- 同一幂等键并发创建返回原批次；
- 不同幂等键并发创建只有一个批次成功；
- 服务端生成批次号；
- 写入创建事件和操作日志。

### 4.3 箱操作

实现：

- `add_packing_box`
- `replace_packing_box`
- `remove_packing_box`

规则：

- 只允许未完成批次操作；
- 强制乐观版本匹配；
- 同箱重复采购单行合并；
- 服务端从 SC-F1 采购单行生成订单、SKU 和商品名称快照；
- 事务内锁定批次、采购单和采购单行；
- 聚合校验防止并发超量；
- 箱号和序号由服务端产生；
- 每次操作递增批次版本并记录不可变事件。

### 4.4 完成和取消

实现：

- `complete_packing_batch`
- `cancel_packing_batch`

完成条件：

- 批次必须处于 `in_progress`；
- 至少存在一个箱；
- 每条关联采购单行累计装箱数量必须等于采购数量；
- 完成后状态为 `completed`；
- 不修改 SC-F1 采购单的 `production_completed` 状态；
- 不产生 `ready_to_ship`、`pending_loading` 或任何物流状态。

取消时将活动订单关联标记为 `NULL`，释放采购单供后续新批次使用，同时保留原批次、箱、明细和事件历史。

### 4.5 完成后变更

实现：

- `submit_packing_change`
- `approve_packing_change`
- `reject_packing_change`

规则：

- 只接受已完成批次；
- 保存完整拟变更箱布局和请求哈希；
- 申请人不能审核本人申请；
- 审核时重新锁定批次和采购单行；
- 批次版本必须与申请期望版本一致；
- 批准和应用处于同一事务；
- 新布局必须继续精确覆盖采购单行；
- 批次保持 `completed`，仅递增版本；
- 并发批准只允许一次应用；
- 写入批准/应用或驳回事件及操作日志。

## 5. ORM 防绕过

装箱聚合使用受保护 QuerySet 和实例写入门禁，拒绝：

- `QuerySet.update()`
- `bulk_update()`
- 未经领域路径的 `bulk_create()`
- QuerySet 删除
- 未经领域服务的已存在实例 `save()`
- 直接删除批次、箱、明细、关联或事件

数据库唯一约束和检查约束与领域服务校验并存，没有依赖客户端校验或 `clean()` 作为唯一安全边界。

## 6. Migration 验证

执行结果：

- Django system check：通过；
- `makemigrations --check --dry-run`：`No changes detected`；
- SQLite 当前基线完整升级：通过；
- `packing.0001_initial` 回退到 zero：通过；
- 从 zero 重新升级：通过；
- 临时 MySQL 8 空库完整 migration：通过；
- 冻结标准和权限种子：通过。

MySQL 使用无持久卷的临时 `scf2-mysql-test` 容器、虚构账号和本机独立端口。验证结束后容器已删除，未使用现有数据库容器或数据卷。

## 7. 自动化测试证据

### 7.1 SQLite 快速验证

```text
12 passed, 6 skipped
```

6 项跳过项均为显式要求 InnoDB 行锁和唯一键语义的 MySQL 专项测试。

### 7.2 MySQL 8 F2 验证

```text
18 passed
```

覆盖：

- 同幂等键并发创建重放；
- 不同幂等键并发创建互斥；
- 并发箱操作防超量和版本复用；
- 同一箱动作并发重放；
- 完成后变更并发批准只应用一次；
- MySQL 下 ORM 批量写入绕过拒绝；
- 供应商能力默认关闭；
- 跨租户和跨供应商拒绝；
- 非生产完成或停用供应商拒绝；
- 箱增删改、完成、取消和关联释放；
- 精确完成且不推进采购单物流状态；
- 完成后异人审核、拒绝和过期版本冲突。

### 7.3 SC-F1 相关回归

```text
27 passed, 4 skipped
```

该组包含 SC-F1 API、SC-F2 SQLite 服务测试及数据库设置验证。跳过项为 SQLite 环境下的 MySQL 专项测试。

## 8. 生产保护复核

- [x] 未连接供应链正式线上系统。
- [x] 未连接或修改线上 Supabase。
- [x] 未导入真实供应商、采购单或装箱数据。
- [x] 未建立双写、同步、切流或生产任务。
- [x] 未开放装箱 API。
- [x] 未修改网页端或小程序端。
- [x] 未上传或发布微信小程序。
- [x] 未发送真实通知。
- [x] 未实现 F3 装柜、照片审核或发运状态。
- [x] 临时 MySQL 容器不使用持久卷且已删除。

## 9. 风险与后续门禁

| 级别 | 数量 | 说明 |
|---|---:|---|
| P0 | 0 | 无生产连接、真实数据或边界突破 |
| P1 | 0 | MySQL 并发、精确完成、变更和 ORM 绕过均有实现与测试 |
| P2 | 0 | 本阶段未发现需要带入审核的低优先级缺陷 |

本阶段未实现而且不得视为缺陷的后续内容：

- 内部、供应商和小程序 API；
- DataScope 过滤和 API Token 通道验证；
- Vue 页面和原生微信小程序页面；
- PDF 标签生成；
- F3 装柜、发运和照片/视频审核；
- 数据迁移和生产部署。

## 10. 下一步

下一步应执行：

`SC-F2-1 本地代码审核`

审核重点：

- 模型跨表不变量是否完整；
- MySQL 锁顺序与死锁处理；
- 幂等重放和响应快照；
- 完成后变更的原子性；
- ORM 防绕过覆盖；
- migration 和权限种子；
- 未突破 SC-F1/F3 边界。
