# SC-F2-MULTI-1 本地模型、迁移与领域服务代码审核

- 日期：2026-08-08
- 审核方式：主代理审查 `luna-worker` 实现和测试证据
- 范围：purchasing/packing 模型、迁移、领域服务及定向测试
- 结论：`PASS_FOR_LOCAL_MYSQL_GATE`
- 限制：尚未通过真实 MySQL 8 多进程门禁，不准入 API/前端开发或生产迁移

## 1. 模型路由记录

- 主代理完成 V2 需求审核、领域契约、代码审查和 P1 定级。
- `luna-worker` 独立负责明确授权的后端模型、迁移、领域服务和测试实现。
- 主代理没有与子代理重复实现；复核发现的 P1 均退回同一 worker 整改后重新验收。

## 2. 已实现范围

- 订单明细履约投影和不可变履约事件；
- 多批次 `PackingBatchLineAllocation` 预留、冻结、释放和反向状态；
- 移除订单级单活动批次唯一约束，保留历史兼容字段；
- 允许部分批次完成，不再要求一次覆盖整单；
- `PackingBoxConsumption` 整箱唯一活动消费；
- 集货消费向发运消费的原子转移；
- `PackingBoxConsumptionAction` commit/release/transfer 独立幂等账本；
- 历史零完成、整单完成、部分完成待人工分配的迁移分类；
- 采购整单生产完成后的明细投影受控收敛。

## 3. 主审 P1 与关闭结果

| 编号 | 问题 | 整改结果 | 状态 |
| --- | --- | --- | --- |
| `SC-F2-MULTI-1-R1-P1-001` | 多明细箱使用同一履约事件幂等键 | 按请求、line、action 派生稳定唯一键 | `CLOSED` |
| `SC-F2-MULTI-1-R1-P1-002` | commit/release 重放没有独立动作结果 | 新增 append-only 消费动作账本和数据库唯一键 | `CLOSED` |
| `SC-F2-MULTI-1-R1-P1-003` | 集货确认可能提前增加发货量 | 只有 shipment commit 增加 shipped；consolidation commit 不记发货 | `CLOSED` |
| `SC-F2-MULTI-1-R1-P1-004` | 历史部分生产投影无法在完工时安全收敛 | 仅无装箱历史/占用时按明细全量收敛，否则阻断人工处理 | `CLOSED` |
| `SC-F2-MULTI-1-R1-P1-005` | 取消批次迁移生成无来源负事件，超额回填不透明 | 取消不制造负事件；超额 allocation 标记 reversed 并记录审计说明 | `CLOSED` |

## 4. 验证结果

worker 在显式 SQLite 隔离配置下提供：

- Django system check：通过；
- `makemigrations --check --dry-run`：无漂移；
- `test_supply_chain_f2_packing_services.py`：`15 passed`；
- `test_sc_f2_multi_1_local_models.py`：`8 passed`；
- `test_supply_chain_f2_packing_api.py`：`22 passed`。

主代理复核了关键模型、迁移和消费动作实现，并重新执行 Django check/迁移漂移检查。主代理尝试不带 SQLite 隔离参数运行测试时，仓库默认配置指向主机名 `mysql`，本机无法解析并以 `OperationalError 2005` 失败；这证明没有连接到正式数据库，也说明当前没有可用于本轮实证的本地 MySQL 8 服务。该失败不是业务测试失败，但真实 MySQL 门禁仍为未完成。

## 5. 残余门禁

以下项目必须在下一波 `SC-F2-MULTI-1-MYSQL` 完成：

1. 启动或指定与正式系统隔离的本地 MySQL 8 测试实例；数据库名、账号和网络不得指向线上。
2. 正向执行 purchasing 0006、packing 0004/0005/0006，并验证迁移重复检查和只读回滚策略。
3. 多进程并发验证同明细 6+4/超量竞争、完成与取消竞争、同箱双消费、集货转发运、重复 commit。
4. 验证 MySQL 条件替代约束 `(box, active_guard)`、CheckConstraint、1205/1213 映射和确定性加锁顺序。
5. 执行 ORM update/bulk/admin/command 绕过测试以及迁移异常数据分类。
6. 记录数据库版本、字符集、隔离级别、迁移耗时、测试命令及结果。

在上述门禁通过前，不启动 `SC-CONSOLIDATION-0` API/权限契约实现，也不提交或部署到正式系统。
