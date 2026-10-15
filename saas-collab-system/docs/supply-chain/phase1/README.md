# 供应链协同第一阶段开发交付

日期：2026年10月12日。候选分支：`codex/supply-chain-phase1-20261012`。父源码：`e63cd14783e0bc99a82097dd776df5e3b7e71001`，来自现有发布记录的正式父基线；不据此声称已实时核验正式运行环境。

本阶段交付可执行的后台基础：13个持久模型、结构与权限两条增量迁移、事务服务、采购与供应商分开的只读接口、接口契约和历史数据预检。旧模块及历史表保留。新版页面和写入HTTP接口在后续阶段接入这些服务，最终切换原供应链入口。

## 已完成的范围

| 内容 | 第一阶段行为 |
| --- | --- |
| 采购来源 | 运营来源分配、直接创建、规范化导入数据；可选、可重复的备注单号。导入记录批次和行号，不处理Excel文件 |
| 采购价格 | 保存商品参考价与本次采购价，允许草稿价格未填；确认下单时要求每行有效价格。供应商价格档案自动维护属于第二阶段 |
| 发货来源 | 供应商与采购代录共用模型，一张采购单多次发货；允许超量和新增SKU，分别保存来源及异常数量 |
| 箱号 | 只建立私有附件与发货单的绑定；不建立逐箱录入依赖。上传、下载和扫描流程在供应商页面阶段接入 |
| 集货 | 整张已提交发货单组批；已标记或未标记集货点到仓均可选择。同批目的国家一致，同发货单仅有一个有效集货关系 |
| 物流 | 在批次上按开船、到港、到仓顺序标记，保存实际时间、操作者及事件；发货单读接口实时继承，不保存另一套可编辑物流状态 |
| 入库 | 到仓后由采购选择该国家有效仓库，逐条保留发货来源生成草稿；重复操作幂等，不写库存快照 |
| 事件通知 | 下单成功与通知事件、outbox同一事务保存。通道未验证，任务标记blocked/channel_not_verified；本阶段不发送企微消息 |
| 权限 | 内部采购权限和供应商归属分别校验；所有查询和引用限定租户。跨供应商批次须全部单据都在采购授权范围内 |
| 历史预检 | SQL聚合统计旧新行数与引用问题，只输出统计JSON，不执行历史导入、不猜国家或采购来源 |

成本、费用分摊和结算状态分别约定在契约中，并明确`implemented=false`；不把这些约定视为已开发功能。原客户群群发接口不接入新版。

## 模型与约束

主干为`PurchaseOrder → SupplierShipment → DispatchBatch → InboundOrder`。商品、供应商、国家、仓库引用原有主数据，不新增商品SKU档案。货运公司模型预留已确认的档案字段，维护页面在第二阶段完成。

运营来源在本阶段保存只读身份引用并校验分配数量合计，尚未连接真实上游订货接口。后续写入API须通过上游适配器核验来源存在、商品、国家和可拆数量；目前的规范化数据服务不能替代该核验，也不能将任意输入的来源ID视为实际拆单已接通。

`PurchaseLine`、`OperatingAllocation`、`ShipmentLine`、`DispatchMembership`和`InboundLine`分别保存明细及来源数量。`BoxInfoAttachment`引用既有私有文件记录。`BusinessEvent`不可修改，`NotificationOutbox`按采购单、版本和通知类型唯一。

服务持有租户行锁，按固定顺序在事务内操作，避免同企业重叠集货、重复创建、累计超量读取之间发生竞争。更新动作校验`expected_version`；重复请求检查幂等键及内容哈希，内容不同拒绝复用同一键。数据库另以唯一约束兜底，同一发货单不能拥有两个`active_guard=True`的集货关系。历史释放关系预留NULL值，本阶段不提供释放或撤销动作。

业务记录禁止普通ORM批量更新、删除及越过服务保存。SQL管理员仍应遵守发布及迁移规则；此保护不替代数据库权限。

## HTTP接口

本阶段均为GET，支持`limit=1..100`和非负`offset`；返回`data/count/limit/offset`。POST、PATCH、DELETE尚不开放。现有登录JWT复用，MiniApp token不能访问这些路由。

| 入口 | 路径 | 范围 |
| --- | --- | --- |
| 采购 | `/api/internal/supply-chain/v2/contract/` | 返回模型、状态、约束及真实能力标识 |
| 采购 | `/api/internal/supply-chain/v2/purchase-orders/` | 有权限的新版采购单 |
| 采购 | `/api/internal/supply-chain/v2/supplier-shipments/` | 有权限采购单下的发货单 |
| 采购 | `/api/internal/supply-chain/v2/dispatch-batches/` | 成员全部在授权范围内的批次 |
| 采购 | `/api/internal/supply-chain/v2/inbound-orders/` | 上述批次对应的入库单 |
| 供应商 | `/api/external/supplier/supply-chain/v2/purchase-orders/` | 所属供应商已确认采购单，不显示草稿 |
| 供应商 | `/api/external/supplier/supply-chain/v2/shipments/` | 所属供应商采购单下的同一套发货数据 |

新权限为`supply.v2.view`和`supply.v2.manage`，由迁移创建，不自动授予任何已有角色。复用ALL、OWN、CUSTOM数据范围；CUSTOM使用现有权限页面可维护的`supplier_ids`。旧`supply_purchase_order_ids`不复用，避免旧新主键碰撞授权；第一阶段不提供单据ID范围配置。新增权限的中文名称及模块名已配置，前端菜单、路由、排序及显示条件无改动。

底层命令位于`apps/supply_chain/services.py`：`create_purchase_order`、`confirm_purchase_order`、`create_supplier_shipment`、`mark_collection_arrival`、`create_dispatch_batch`、`mark_logistics_stage`、`generate_inbound_draft`。它们要求真实账号权限及数据范围，不是绕过权限的导入捷径。

## 本地验证

使用现有Python/Django环境，从backend目录执行。以下只使用内存SQLite，不能在生产环境替换数据库配置后执行。

```powershell
$env:DB_ENGINE = 'django.db.backends.sqlite3'
$env:DB_NAME = ':memory:'
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest tests/test_supply_chain_v2_foundation.py -q
```

测试范围及最终结果见同目录`verification.json`和`test-results-combined.xml`：45个不同测试最终通过，包括15个新版基础测试和30个现有回归测试。完整运行中43项通过、两项测试准备问题修正后复测通过；原始结果及复测结果一并保留。SQLite验证不能替代目标MySQL并发及真实迁移验收；生产切换前必须在目标MySQL版本的隔离库复核租户锁、唯一约束、迁移计划与整链回归。

历史数据只读预检命令为`python manage.py audit_supply_chain_migration --tenant-id <企业ID>`。需先在隔离库应用审阅后的schema；输出行数、缺失表、引用统计和后续行动，无业务明细与敏感信息。本阶段未连接正式库或执行该库上的历史预检。

## 待后续阶段完成

第二阶段接入基础档案补充、采购页面、写入API、Excel导入导出和SKU标签；第三阶段完成供应商门户、发货编辑及私有文件流程；第四阶段接入集货入库页面及权威库存收货接口；第五阶段实现价格和费用版本、可调混合分摊及成本差额；第六阶段联调通过实群验收的自动投递通道。

当前库存`InventorySnapshot`为外部WMS同步观察数据。本阶段不将采购入库伪装为一次WMS同步，不以物流到仓产生库存。本阶段无生产部署、版本登记或原入口切换。
