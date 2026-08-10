# SC-F2-MULTI-1 本地模型、迁移与领域服务开发报告

- 日期：2026-08-08
- 范围：本机开发分支 `codex/scm-f2-packing-local`
- 上游契约：`SC-F2-MULTI-0`（已通过独立审查）
- 结论：`LOCAL_CORE_IMPLEMENTED_WITH_DOWNSTREAM_BOUNDARY`

## 1. 已实现

### 1.1 采购明细履约投影与事件

- 新增 `SupplyOrderLineFulfillment`：每条采购明细独立保存生产完成、装箱预留、已装箱、已发运、到仓、清货数量、版本和迁移分类。
- 新增 `SupplyFulfillmentEvent`：append-only 数量事件，记录来源版本、幂等键、前后快照、操作人和反向事件引用。
- 投影 QuerySet 的 `update/bulk_update/bulk_create/delete` 受控；投影与事件只能在审计写上下文中变更。
- 订单保存只负责补齐缺失投影；历史订单级部分生产量不按比例猜测，标记为 `legacy_partial_manual`。

### 1.2 多批次装箱与明细 allocation

- 新增 `PackingBatchLineAllocation`，唯一键为 `(batch, order_line)`，支持 `reserved/frozen/released/reversed`。
- 创建、加箱、换箱、完成和取消均按租户、订单、明细的确定性顺序加锁，并同步投影与履约事件。
- 允许同一订单跨多个批次部分装箱；完成批次只冻结自身箱明细，取消只释放未冻结预留。
- 已有下游箱消费的完成布局不能直接替换；布局更正追加正向或反向履约事件。

### 1.3 整箱唯一消费与转移

- 新增 `PackingBoxConsumption`，数据库通过 `(box, active_guard)` 约束整箱同时只能有一个活动消费。
- 提供预留、提交、释放和转移领域服务；转移先释放源活动槽，再创建带 `transferred_from` 的目标消费，失败整体回滚。
- 兼容保留 `active_guard` 字段，历史取消链接不再依赖活动批次唯一约束。

## 2. 迁移策略

1. `purchasing.0006_supplyfulfillment_projection` 新增明细投影/事件表并幂等回填：零完成量分类为 `legacy_zero`，整单完成分类为 `legacy_full_order`，部分完成分类为 `legacy_partial_manual`；反向迁移不删除审计数据。
2. `packing.0004_packing_batch_line_allocation_and_box_consumption` 新增 allocation/消费表，按旧批次箱明细回填并移除订单级活动批次唯一约束。部分生产只保留人工分配队列。
3. `packing.0005_packingboxconsumption_request_hash` 为消费记录补充请求哈希。
4. `packing.0006_packingboxconsumptionaction` 新增消费动作 append-only 幂等账本。

迁移仅针对本机数据库设计，不连接线上系统，不删除历史业务表；正式上线前仍需单独完成备份、回滚演练和 MySQL 8 多进程验证。

## 3. P1 整改结果

- **逐明细事件幂等**：packing 事件键稳定派生为 `tenant + request + line + action`；一个箱同时包含多条明细时，每条明细均追加独立事件。
- **消费动作独立幂等**：`PackingBoxConsumptionAction` 保存 commit/release/transfer 的动作键、请求哈希、前后状态和结果消费行。同主体同动作同 payload 重试直接回放，主体或 payload 冲突返回 `StateConflict`（HTTP 层映射 409）。
- **集货/发运分离**：集货确认（包括已提交集货源的转移）不增加 `shipped_quantity`；只有 shipment commit 在同一事务内为每条明细增加一次 shipped。转移目标严格限定为 shipment。
- **生产投影收敛**：`perform_supply_order_action(COMPLETE_PRODUCTION)` 在受控写上下文中将无装箱历史的 partial/manual 投影收敛到各自明细全量，并追加 production 事件。若存在 packing 事件、allocation、消费占用或非零下游量，则阻断收敛并要求人工分配。
- **迁移审计修正**：`packing.0004` 对 cancelled allocation 只保留 released allocation，不再生成无来源 `release_packing` 负事件；回填前检查 production/ordered 上限，超额数据分类为 `reversed` allocation 并在批次 note 留下审计标记，避免由 CheckConstraint 直接抛出不透明 IntegrityError。

## 4. 验证

本机 SQLite（`DB_ENGINE=django.db.backends.sqlite3`）执行：

```powershell
backend/.venv/Scripts/python.exe manage.py check
backend/.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
backend/.venv/Scripts/python.exe -m pytest tests/test_sc_f2_multi_1_local_models.py -q
backend/.venv/Scripts/python.exe -m pytest tests/test_supply_chain_f2_packing_services.py -q
backend/.venv/Scripts/python.exe -m pytest tests/test_supply_chain_f2_packing_api.py -q
```

结果：Django check 通过；迁移检查无变更；本阶段测试 `8 passed`；packing API 回归 `22 passed`；packing services 回归 `15 passed`。两条旧 V1 断言已在本阶段对应测试中更新为 V2 多批次/部分完成合同，未修改业务代码或未授权 API 文件。

## 5. 未实现与残余风险

- 散货集货、集货地点、发运单、报关、到仓和清货的具体模型/API 不在本阶段；消费服务保留通用 `consumer_type/id/version` 边界供后续聚合复用。
- 已发运箱的拆箱/重新装箱 UI/API 未实现；完成布局更正只支持无下游活动消费的受控路径。
- 生产进度仍保留订单级兼容字段；历史部分生产必须先完成人工明细分配。
- 本机未执行真实 MySQL 多进程压测；上线前需验证 MySQL 8 锁顺序、唯一约束和 1205/1213 重试行为。
- API 层 HTTP 快照、权限 DataScope 和三通道路由未在本阶段扩大修改，继续由既有 API 契约及后续波次负责。
