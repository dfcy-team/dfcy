# SCM-V3-CARRIER-0 货运方主数据领域、API 与权限合同

- 日期：2026-08-12
- 状态：`P1_REMEDIATED_READY_FOR_RECHECK`
- 范围：合同冻结；不授权模型、迁移、API、数据回填或生产操作
- 环境：仅架构员本机；正式供应链系统继续隔离运行

## 1. 领域边界

新增 `CarrierMaster` 作为租户内货运方权威主数据。现有 Shipment 的 forwarder/transport 字符串仅保留为历史或外部引用，不能替代 Carrier FK。

Carrier 负责名称、运输方式、报价计费基础、税率、服务区域和联系信息。运价历史、订单费用、发运状态、报关、结算和通知分别归 Cost、Shipment/Container、Settlement、Notification 领域负责。Carrier 报价不得作为历史费用重算依据。

## 2. 模型合同

| 字段 | 合同 |
| --- | --- |
| tenant | FK PROTECT；不可跨租户 |
| code | ASCII slug，max80；trim+lower；`tenant+normalized_code` 唯一；创建后不可修改 |
| name | max160；trim 后非空；列表可搜索 |
| transport_method | `sea/air/rail/road/express/multimodal/other` |
| freight_type | `by_volume/by_weight/by_container/by_shipment/fixed/negotiated` |
| rate_unit | `cbm/kg/container/shipment/fixed/negotiated`；与 freight_type 一一对应 |
| rate_amount | Decimal(18,6)，nullable；非 negotiated 必填且 `>=0`；negotiated 必须为 null；零值表示明确的免费/豁免报价并记录审计 |
| currency | ISO-4217 三位大写；rate_amount 非空时必填，否则必须为空 |
| tax_rate | Decimal(7,6)，`0<=rate<=1` |
| region_codes | 非空 JSON 字符串数组；服务端 trim、转大写、排序去重；每项 max32；只允许受控且写入时有效的区域代码或单独的 `GLOBAL` |
| address | max500，blank；PII，`RET-PII` |
| contact_alias | max80，blank；不要求真实姓名 |
| contact_phone/email | max32/Email，blank；PII |
| status | `active/inactive`；默认 active；只能由受控动作改变 |
| effective_from/to | aware datetime，可空；to 必须晚于 from |
| version | PositiveInteger，默认1；每次业务更新 +1 |
| created/updated_at/by | 审计字段；actor FK PROTECT；迁移 actor 可空但必须记录 migration ID |

计费组合固定映射：`by_volume→cbm`、`by_weight→kg`、`by_container→container`、`by_shipment→shipment`、`fixed→fixed`、`negotiated→negotiated`。Carrier 内不做单位换算、阶梯价、最低价或汇率换算；这些属于 Cost 领域。

数据库必须以 CheckConstraint 保证映射、金额/币种空值组合、金额非负、税率和生效窗口。`GLOBAL` 不得与其他区域并存；空数组、重复、未知或停用区域均拒绝。索引为 `(tenant,status,code)`、`(tenant,name)`。禁止物理 delete，QuerySet delete 和实例 delete 均拒绝；bulk update 不得作为业务入口。

## 3. 生命周期、可选择性与快照

- create：默认 active；校验代码、枚举、计费组合、区域和生效窗口。
- update：仅允许 name、transport_method、freight_type、rate_unit、rate_amount、currency、tax_rate、region_codes、地址/联系人、生效窗口；必须提交 expected_version。
- deactivate：只阻止新的订单、发运、柜货选择；历史引用继续读取。
- reactivate：本期不开放。普通 update 不得修改 status，不得把已过期记录的有效期延长或借此恢复可选；未来须使用独立权限和审核动作。
- `is_selectable(at)` 唯一定义：`status=active AND (effective_from IS NULL OR effective_from<=at) AND (effective_to IS NULL OR effective_to>at)`。
- 缩短尚未到期的 effective_to 仅影响新引用，必须记录前后值、actor、reason；历史详情不受影响。
- 业务单据使用 Carrier FK PROTECT，并冻结 `carrier_code/name/transport_method` 快照。费用另存 Cost 版本快照，禁止读取 Carrier 当前报价重算历史。

## 4. 权限、DataScope 与 PII

exact permissions：

- `supply.carrier.view`
- `supply.carrier.create`
- `supply.carrier.update`
- `supply.carrier.deactivate`

仅 internal 渠道。授权顺序：用户和租户有效 → exact permission → permission-specific DataScope → 对象状态/version。角色名和 `masterdata.manage` 不能替代 exact permission。

DataScope：

- ALL：可访问租户全部 Carrier；只有 ALL 可创建或更新 `GLOBAL`。
- CUSTOM：现有对象必须同时命中 `carrier_ids`，且提交后全部 region_codes 逐项命中 scope 的 `region_codes`；创建时只校验全部区域。CUSTOM 永远不得创建、更新或获得 `GLOBAL` 对象。
- OWN/DEPARTMENT：拒绝并返回 `DATA_SCOPE_INVALID`。
- 对象不存在或越权统一 404；搜索、唯一冲突、停用动作和幂等重放不得枚举其他租户数据。

区域代码来自受控 Region 主数据或冻结 allowlist；写入时必须存在、active 且属于当前租户可用范围。规范化后再做去重和 DataScope 判断。

默认列表和详情均只返回 `has_contact` 及脱敏联系人。完整电话、邮箱和地址需要未来独立权限 `supply.carrier.contact.view`，不纳入 Carrier-1 默认实现。日志、事件、错误和幂等快照禁止保存完整 PII。

## 5. Internal API

前缀：`/api/internal/supply-chain/carriers/`。所有写请求要求 `Idempotency-Key`；更新/停用要求 `expected_version`。

| Method/path | permission | DTO/HTTP |
| --- | --- | --- |
| GET `/` | view | `q,status,transport_method,region_code,page`；200 分页裁剪 DTO |
| POST `/` | create | 201；同键同请求稳定重放；冲突409 |
| GET `/{id}/` | view | 200 脱敏详情或404 |
| PUT `/{id}/` | update | 200；全量替换可变字段；冲突409 |
| POST `/{id}/actions/deactivate/` | deactivate | reason+expected_version；200 inactive DTO；稳定重放 |

PUT 必须包含全部可变字段：name、transport_method、freight_type、rate_unit、rate_amount、currency、tax_rate、region_codes、address、contact_alias、contact_phone、contact_email、effective_from、effective_to；空值也须显式提交。`expected_version` 是并发控制输入，不是模型字段。缺字段返回400。请求提交 tenant、code、normalized_code、status、version、actor 或审计字段返回400。

响应不得返回 DataScope、内部用户 ID、密钥或未脱敏 PII。状态码：校验400、未认证401、渠道拒绝403、未命中404、冲突409、限流429。

## 6. 幂等、并发与 ORM 门禁

- 动作账本以 `(tenant,idempotency_key,action)` 唯一；不同 request_hash 返回409。
- 每次重放前必须重新执行当前用户/渠道、租户有效性、exact permission、当前 permission-specific DataScope 和对象可见性校验；权限撤销后不得返回历史成功响应。
- 重放响应使用当前 DTO 脱敏规则从受控快照重建，账本不得存完整电话、邮箱、地址或历史授权结果。
- create 同 tenant 同 normalized_code 并发只能一个成功；同键同 body 确定性回放，异键或异 body 冲突。
- update/deactivate 锁 Carrier 行并校验 version；映射数据库 1205/1213 为稳定冲突响应。
- model clean/save、受控 QuerySet 和数据库约束共同防止跨租户、非法枚举/精度及 ORM 绕过。

MySQL 门禁覆盖：代码大小写/尾空格、所有计费组合、金额/币种约束、GLOBAL/区域约束、并发创建、并发更新/停用、幂等重放重新授权、CheckConstraint/unique、ORM 绕过和 1205/1213 映射。

## 7. 历史 `shipping_companies` 迁移

DISCOVER 按 tenant 统计代码、名称、方式、计费、税率、区域、联系人和引用。分类：AUTO、DUPLICATE_CODE、UNKNOWN_ENUM/CURRENCY、TENANT_MISSING/CROSS_TENANT、PII_INVALID、REFERENCED_SNAPSHOT；未知信息禁止猜测。

alias 表唯一键为 `(tenant,source_system,source_id)`，映射创建后只读且不可修改/删除；仅供迁移核对和审计，不作为业务查询入口。保留期遵循审计策略，过期只允许受控归档，不得破坏来源追踪。

波次：只读发现 → 新表/权限 → 幂等回填 → 引用 FK nullable 回填 → 新旧对账 → 新写切换 → 观察期后旧表只读/退役。计数必须 `source=mapped+manual`，重大遗漏、跨租户或引用丢失为0；失败只回滚本波新增 FK/行，源表不改。生产迁移另立项。

## 8. P2 决定与退出条件

- P2-001：首期 PUT 采用严格全量语义；缺少任何可变字段返回400，不支持 PATCH。
- P2-002：默认详情继续脱敏；完整联系人权限与访问审计另立项，不进入 Carrier-1。
- P2-003：历史 alias 唯一、不可变、只读、非业务查询入口，按审计保留策略归档。

独立快速复核必须确认 P1-001 至 P1-004 已关闭，且模型、PII、权限、CUSTOM/GLOBAL、API、幂等、MySQL 和迁移合同均可编码；通过后才可进入 `SCM-V3-CARRIER-1` 本地模型与领域服务开发。
