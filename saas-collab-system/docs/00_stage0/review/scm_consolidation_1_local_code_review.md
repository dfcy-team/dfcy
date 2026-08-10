# SC-CONSOLIDATION-1 本地代码审核

## 审核结论

结论：`PASS_WITH_REPOSITORY_MIGRATION_BLOCKER_NOTED`。

散货集货领域的本地模型、领域服务、权限种子、追加式事件、迁移和 MySQL 并发门禁已达到进入后续合同阶段的条件。本结论不等同于 API、附件交接凭证或发运域已经完成，也不批准连接或变更正式线上系统。

仓库现有 `products` 模型与历史迁移存在字段漂移，导致 pytest 迁移型测试库在依赖夹具阶段缺少 `products_productsku.product_name`；同时 `makemigrations --check` 会提出既有 `package_volume` 字段迁移。全新隔离 MySQL 业务库执行 `manage.py migrate --noinput` 已成功（含 `consolidation.0002`），因此该问题记录为全仓最终门禁的前置阻塞，不归因于本轮集货域实现，也未在本轮越界修改 products。

## 模型路由与范围

- 主代理：合同边界确认、代码审核、P1 定级、验证结果复核与审核归档。
- `luna-worker`：`consolidation` 模型/服务/迁移、权限种子、定向测试及整改实现。
- 未修改供应链正式线上环境、`.env`、API 路由、Web 或微信小程序代码。
- 未实现供应商交接凭证、附件资产、shipment transfer；这些能力必须先冻结独立合同。

## P1 整改复核

1. `P1-001` 已关闭：异常仅可从 `ALLOCATED`/`HANDOVER_SUBMITTED` 进入；`ready` 只接受全部活动箱均为 `RECEIVED`，异常箱必须先收货或受控释放。
2. `P1-002` 已关闭：分配记录、箱快照和事件保存稳定排序的完整订单 ID/订单号列表；`consolidation.0002` 对旧 singular/嵌入快照做保守回填。
3. `P1-003` 已关闭：站点被集货单引用后禁止修改 `site_code`；动作时点及计划截单/发运时间按 `[effective_from, effective_to)` 校验。
4. `P1-004` 已关闭：创建站点、集货单和事件同时映射 Django 唯一校验异常与数据库完整性异常；同键同载荷重放，异键或异载荷确定性冲突。
5. `P1-005` 已关闭：补齐真实 MySQL 双线程创建、release/cancel 竞争、同箱双分配、整批回滚以及 ORM/事件约束证据。

## 验证证据

- SQLite 当前模型定向测试：`7 passed`。
- MySQL 8.4.10 当前模型本地服务矩阵：`7 passed in 93.05s`。
- MySQL 8.4.10 P1/并发门禁：`5 passed in 102.51s`。
- 全新隔离 MySQL 数据库从零迁移：通过，包含 `consolidation.0001`、`consolidation.0002` 和权限 `0025`。
- Django system check：通过。
- 相关文件 `git diff --check`：通过；仅有工作区 CRLF 提示，无补丁格式错误。
- 临时数据库、容器、匿名卷已删除；`13309`、`13310` 端口均无监听残留。

## 保留边界与后续门禁

- DataScope 的 API 查询过滤、字段脱敏和历史可见性尚未实现，不能仅凭权限种子视为完成。
- 供应商交接凭证及中文标签/附件的文件类型、哈希、病毒扫描、对象存储与审计策略需要独立合同。
- 集货转发至发运域必须由 typed shipment contract 接管；集货收货/ready 不得直接增加 shipped 数量。
- Android 与 iPhone 微信小程序显示兼容性应在 API 合同稳定后进入独立端侧矩阵，不在本轮模型层审核中提前实现。

## 下一步建议

先执行 `SC-CONSOLIDATION-ATTACH-0`（供应商交接凭证与附件合同冻结）和 `SC-SHIPMENT-0`（散货集货转发、报关/发运 typed contract 冻结），通过独立审核后再进入 `SC-CONSOLIDATION-2` API、权限与 DataScope 实现。全仓提交后基线确认前，另行解决 products 历史迁移漂移并运行完整迁移型测试。
