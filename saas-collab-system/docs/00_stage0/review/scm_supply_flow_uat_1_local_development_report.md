# SC-SUPPLY-FLOW-UAT-1 本地开发报告

日期：2026-08-08  
数据版本：`SC-UAT-DATA-V1`  
范围：本地合成数据生成、自检和定向清理。未连接线上系统、正式 `.env`、生产对象存储或第三方服务。

## 交付文件

- `backend/apps/purchasing/uat_data.py`：受控 UAT fixture、版本/载荷指纹、生成与自检逻辑，以及按 tenant 的停用清理逻辑。
- `backend/apps/purchasing/management/commands/seed_supply_flow_uat.py`：`generate`、`check`、`cleanup` 管理命令。
- `backend/tests/test_sc_supply_flow_uat_1_local.py`：SQLite（`--nomigrations`）定向门禁。

本轮没有新增迁移，也没有修改业务模型、状态机、API、权限/DataScope 语义、Web 或小程序。

## 数据和安全边界

生成器固定创建两个租户 `SC-UAT-A`、`SC-UAT-B`，租户 A 包含三个供应商，租户 B 包含一个供应商；所有业务编号、用户和商品均以 `SC-UAT-` 标识。每个租户名称保存数据版本和 payload SHA-256 指纹。相同版本和 payload 只能重放，版本相同但 payload 不同会在写入前 fail-closed。

生成前必须显式传入 `--environment local`、`--confirm-local` 和与已加载 Django connection 完全相同的 `--database-name`。已加载的 `DJANGO_SETTINGS_MODULE` 还必须是明确的本地/开发/测试模块（当前允许 `config.settings.dev` 等白名单），含 `prod`、`production`、`pilot` 或 `sandbox` 的模块显式拒绝，即使 `DEBUG=True` 也不例外。SQLite 文件名必须带 `uat/test/local/dev` 标记，并拒绝 UNC、网络路径和非本地 `file:`/`sqlite://` URI；内存 SQLite 只在自动化测试显式传 `--allow-inmemory-test` 时允许。MySQL 只接受回环地址。命令不会读取 `.env`、复制真实数据或输出密码、token、Cookie、session。

采购订单、生产完成、6+4 两批次装箱、集货分配/发布/收货/异常/受控释放/ready，以及 shipment 转移、报关、两次 dispatch、到港、到仓、清货均通过现有领域服务完成。合成附件使用 fake storage/scanner，仅保留 accepted、rejected、quarantined 三种样本；附件服务生成的 opaque `ATT-*` 编号不被改写。

自检验证租户/供应商隔离、订单和明细数量（每单 2 条、每条 10）、8 个完成批次和物理箱、6+4 守恒、3 个集货单、两个 shipment/四个 shipment allocation、重复箱消费及附件状态。South-02 的一个隔离箱走 quarantine→exception→controlled release，因此下游 active consumer 预期为 7（其余 7 个物理箱各一个 active consumer），这是有意的可审计终态，不是重复消费。

清理只接受精确的 `SC-UAT-A`/`SC-UAT-B` tenant code，先停用 UAT 用户和小程序身份，再将 tenant 标记为 `INACTIVE`；清理前后记录对象计数。append-only 事件、附件账本及受外键保护的业务记录不物理删除，并返回 `DEACTIVATED_WITH_AUDIT_RETENTION`。非 UAT tenant 不受影响。生成的所有账号密码均为 unusable，仅完成数据、角色和 scope 准备；人工 UAT 所需的短期凭据激活属于下一独立步骤，本命令不会创建可直接登录的凭据。

## 本地验证

通过：

```text
DJANGO_SETTINGS_MODULE=config.settings.dev DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
  python -m pytest tests/test_sc_supply_flow_uat_1_local.py -q --nomigrations
8 passed in 10.72s

python manage.py check
System check identified no issues (0 silenced).

python -m py_compile apps/purchasing/uat_data.py \
  apps/purchasing/management/commands/seed_supply_flow_uat.py \
  tests/test_sc_supply_flow_uat_1_local.py
git diff --check -- <本轮文件>
无输出/通过
```

测试覆盖错误环境拒绝且不创建租户、生产 settings 标识（DEBUG=True）拒绝、UNC/网络 SQLite 路径拒绝且零写入、首次生成与同 payload 重放、篡改供应商后自检失败、异 payload 冲突、双 tenant/supplier scope、指定 tenant 清理以及审计图保留。

全仓 `makemigrations --check --dry-run` 仍被工作树已有的 permissions 迁移叶子冲突（`0024_seed_global_listing_permissions` 与 `0026_seed_shipment_permissions`）阻塞；本轮未擅自修改或 fake 迁移。该冲突与 UAT tooling 无关，因此未在此报告中伪造全仓迁移通过。

## 未覆盖项与残余风险

- 本轮未启动新的 MySQL 8.4 容器；真实 MySQL fresh migrate 需先解决上述既有迁移图冲突，不能用 `--nomigrations` 结果替代。
- 未运行真实 HTTP/API、Web、小程序或生产附件上传/下载；这些仍由既有 API2/客户端阶段门禁负责。
- 本地测试使用 `--nomigrations` 的内存 SQLite，不能证明 MySQL 锁、约束或死锁映射；如进入下一波，应在独立 loopback MySQL 库运行同一 command，并记录并清理容器、库和卷。
- 自检覆盖合成 fixture 的核心数量与状态，不替代完整 UAT-01～UAT-20 业务验收矩阵。
