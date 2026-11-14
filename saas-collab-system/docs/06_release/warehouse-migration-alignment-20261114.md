# 仓库基础迁移与主线对齐

本 PR 只提交仓库接入所需的数据库基础：百世枚举、百世平台初始化、开发接口仓库授权引用、平台连接器字段及授权回填。协议调用、配置页面及后续出库、售后、财务功能仍须独立 PR；本 PR 不开放百世实际调用能力。

## 两条已存在的历史

主线从 integrations 0058 经 0059_shopee_advertising_order_index 到 0060_gmv_max_audit_lookup_index。本地仓库分支从同一个 0058 经 0059_developer_warehouse_account、0060_best_ecapi_platform 到 0061_best_platform_master。

迁移名称是完整文件名，两个 0060 的操作不同，不能相互覆盖、重命名已应用记录或伪造迁移历史。本 PR 保留两条分支，并增加空操作的 0062_merge_warehouse_gmv_branches，依赖上述主线 0060 与仓库 0061。平台连接器回填 masterdata 0024 仍依赖 0023 及仓库 0061；各历史迁移文件保持原样。

回填只根据未撤销仓库授权及配置的同一供应商判定连接器。冲突、未知供应商或无授权保持待确认；人工选择及“暂不接入”保留。不得仅根据平台名称猜测极风或百世。

## 验证方法

`manage.py makemigrations integrations masterdata --check --dry-run` 检查模型与迁移状态；`pytest tests/test_warehouse_migration_alignment.py` 检查唯一叶节点及两分支依赖。

该测试文件还提供 `verify_upgrade(connection, legacy_first=False/True)`，供真实 MySQL 隔离验证。必须是全新、名称以 test_warehouse_alignment_ 开头的测试库；禁止连接业务库。它分别验证从主线 0060 与旧仓库分支升级，覆盖极风、百世、供应商冲突、撤销授权、无授权五种平台，核对授权行原样保留、百世平台不重复、主线审计索引保留、迁移历史一致及再次升级无操作。

2026-11-14 验证结果：模型迁移一致性通过，迁移图专项 1 项通过；隔离 MySQL 3313 的两个全新库分别从主线 0060、旧仓库分支升级成功。每个路径 5 种平台、5 条授权均符合预期，审计索引保留，历史一致，目标待执行迁移数为 0。原 5 个仓库历史迁移与开发目录内容一致，新增合并节点没有 DDL 操作。日志保留在本机工作树外层 mysql-upgrade-verification.log，不包含凭据。

## 本地目录边界与后续 PR

D 盘日常目录已经有 0064_merge_local_best_vm410，将仓库 0061 与经主线 0060 的本地开发接口分支合并；另有 0065～0067，其中 0067 添加 config.platform_master。C 盘旧开发目录则以 0062_config_platform_master 添加同一字段。两份字段迁移不能同时导入；本 PR 不含该字段迁移，也不修改或迁移日常数据库。

连接器页面和百世基础协议 PR 应以本 PR 的数据库状态为基础，再单独选择与目标环境匹配的 platform_master 字段迁移与回填。出库调度、售后回仓依赖仓库身份/授权接口；财务流水和仓库费用依赖对应业务模型。不得把 D 盘完整迁移目录批量覆盖到 main，也不能在只有本 PR 的状态下声称百世业务接入或财务功能已经提交。

本 PR 为基础 Draft，不合并、不发布、不登记版本、不执行目标环境迁移。业务负责人需在后续 PR 中核对目标部署分支的实际迁移历史。
