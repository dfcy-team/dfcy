# SC-F2-MULTI-1 MySQL 8 本地隔离门禁报告

- 日期：2026-08-08
- 范围：仅本机临时 MySQL 8.4 容器与 SC-F2-MULTI-1 相关代码/测试
- 结论：`MYSQL_LOCAL_GATE_PASSED_WITH_TEST_ISOLATION_NOTE`

## 1. 隔离环境

- 启动前检查：`127.0.0.1:13308` 未占用。
- 容器名：`sc-f2-multi-mysql8`。
- 镜像：`mysql:8.4`，镜像 ID `sha256:c592c15aaf4a1961e15d82eb31ea5987dda862d1c4b1e93424438c0e91dc1f8d`，本机 digest `mysql@sha256:c592c15aaf4a1961e15d82eb31ea5987dda862d1c4b1e93424438c0e91dc1f8d`。
- 实际服务：MySQL `8.4.10`。
- 绑定：仅 `127.0.0.1:13308 -> 3306`；未使用 pilot/sandbox volume，也未读取仓库或线上凭据。
- 专用数据库/账号：`sc_f2_multi_mysql` / `sc_f2_local`；密码为临时本地值，本文不记录。
- 服务参数：`character_set_server=utf8mb4`、`collation_server=utf8mb4_0900_ai_ci`、`transaction_isolation=REPEATABLE-READ`。

## 2. 迁移与静态门禁

显式环境变量：`DB_ENGINE=django.db.backends.mysql`、`DB_HOST=127.0.0.1`、`DB_PORT=13308`，仅使用专用本地库。

- 全量 `manage.py migrate --noinput`：从空库成功完成全部项目迁移。
- 初次迁移暴露 `development.0002_product_sales_summary_view` 在 MySQL 事务内执行 `DROP/CREATE VIEW` 的真实问题；按 Django 非原子迁移方式增加 `Migration.atomic=False`，保留各数据库原有 forward/reverse SQL。全新空库复跑成功。
- `manage.py check`：通过。
- `manage.py makemigrations --check --dry-run`：无漂移。
- 新增迁移测试：`test_development_sales_summary_migration.py`，验证非原子属性及 view forward/reverse round-trip：`2 passed`。

## 3. 真实 MySQL 测试结果

使用 `--reuse-db` 仅复用容器内专用测试库，未连接主机名 `mysql`：

| 测试范围 | 结果 |
| --- | ---: |
| `tests/test_sc_f2_multi_1_mysql.py` | **6 passed** |
| `tests/test_supply_chain_f2_packing_mysql_concurrency.py` | **8 passed** |
| `tests/test_sc_f2_multi_1_local_models.py` + `tests/test_supply_chain_f2_packing_services.py` | **23 passed** |
| `tests/test_supply_chain_f2_packing_api.py`（全新测试库、完整迁移生成） | **22 passed** |
| `tests/test_development_sales_summary_migration.py` | **2 passed** |
| service 1205/1213 映射模拟 | **2 passed** |
| API 1205/1213 映射及恢复模拟 | **4 passed** |

新增 MySQL 门禁测试覆盖：

- 同一明细 6+4 并发预留成功；随后超量竞争全部拒绝，投影总量保持 10。
- 完成/取消并发仅产生一个批次终态，allocation 与投影守恒。
- 同箱 consolidation/shipment 双预留最多一个活动消费，验证 `uniq_pack_box_active_consumption`。
- consolidation → shipment 转移可回放；重复 shipment commit 只增加一次 shipped。
- ORM `update/bulk_update` 绕过被拒绝；SQL 直写违反履约 CheckConstraint 时由 MySQL `IntegrityError` 阻断。
- `packing.0004` 超额历史回填分类为 `reversed` allocation 并记录批次 anomaly，不产生不透明约束失败。
- 既有并发测试覆盖同 key 回放、跨 scope 幂等冲突、不同 key 多活动批次、箱操作版本竞争和 ORM 封堵。

### 3.1 测试隔离说明

曾在“先运行 migration TransactionTestCase、再单独运行 API 文件”的顺序下观察到 API 创建返回 409、标准查询 404。首个 409 的错误码为 `STATE_CONFLICT`，根因为 pytest 对 TransactionTestCase flush 清除了迁移 seed 的 `packing-v1` 标准；不是 MySQL 业务逻辑或约束差异。删除测试库后从完整迁移直接运行 API 全文件得到 `22 passed`，因此最终结果采用 fresh test DB 证据，不伪造连锁失败为通过。

## 4. 真实缺陷修复

- MySQL 并发创建同一 idempotency key 时，赢家提交后竞争事务可能在 `Model.full_clean(validate_unique=True)` 抛 Django `ValidationError` 而非 `IntegrityError`；`create_packing_batch` 现在对两种唯一键竞争路径统一回放同主体同 payload 结果，非同键冲突仍原样抛出。
- 旧 MySQL concurrency 测试中“不同 key 必须只能一个活动批次”的断言已更新为 V2 多活动批次合同；未修改 serializer、views、Web、miniapp 或权限目录。

## 5. 1205/1213 与未覆盖项

- 已有 service/API 测试对 1205（lock wait timeout）和 1213（deadlock）做映射模拟并通过；本轮真实双连接压力未稳定构造 1213，真实并发锁竞争已覆盖并记录结果。
- 未连接线上系统，未进行生产数据回填；MySQL 门禁只针对临时本地库。

## 6. 清理记录

- 已删除专用数据库 `sc_f2_multi_mysql` 和 `test_sc_f2_multi_mysql`。
- 已停止并移除 `sc-f2-multi-mysql8`，并删除该容器自动创建的匿名临时 volume `73bdf71ce83040aa7a6c803385e3222b589646b595bd6b2fd536edf86f65b6c6`。
- 清理后复核：`docker ps -a` 无该容器；临时 volume 不存在；`127.0.0.1:13308` 为 `PORT_FREE`。现有 pilot/sandbox named volume 未触碰。
