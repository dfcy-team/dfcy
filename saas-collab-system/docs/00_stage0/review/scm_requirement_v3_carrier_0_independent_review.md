# SCM-V3-CARRIER-0 独立审核

- 日期：2026-08-12
- 审核对象：Carrier领域/API/权限合同及审核清单
- 结论：`BLOCKED_PENDING_P1_REMEDIATION`
- `SCM-V3-CARRIER-1`准入：`NOT_ADMITTED`

## 1. 已通过项

- Carrier被定义为独立租户主数据，没有承载费用历史、发运状态或结算。
- tenant+normalized_code唯一，明确trim/lower及MySQL大小写/尾空格风险。
- 禁止物理删除、引用后code不可修改、停用保留历史。
- 业务单据FK PROTECT并冻结code/name/transport_method快照。
- 四个exact permission和internal-only渠道明确。
- OWN/DEPARTMENT拒绝，对象越权统一404。
- 联系人PII不进入列表、错误、事件或幂等快照。
- API、version、幂等、并发创建/更新/停用和历史分类方向正确。
- 正式系统隔离和不授权实现边界明确。

## 2. P1问题

### `SCM-V3-CARRIER-0-R1-P1-001`：计费类型与字段不闭合

`freight_type`支持`by_volume/by_weight/by_container/by_shipment/fixed/negotiated`，模型却只有`cost_per_cbm`，且规定非by_volume必须null。这样无法保存按重量、按柜、按票和固定价的单价，合同不可编码。

整改选择其一并冻结：

1. 推荐通用`rate_amount Decimal(18,6)`+`rate_unit cbm/kg/container/shipment/fixed/negotiated`，negotiated允许amount null；或
2. 为每种类型设置互斥专用字段。

同时冻结currency必填条件、0值是否允许、单位换算和数据库CheckConstraint。Carrier中的费率只能作为报价提示，历史费用仍保存公式版本快照。

### `SCM-V3-CARRIER-0-R1-P1-002`：空区域及CUSTOM语义不确定

`region_codes`允许数组，但未说明`[]`代表全区域、未知还是无服务区域。CUSTOM创建要求命中“全部region_codes”，对空数组会真空通过，可能允许越权创建全区域Carrier。

整改：建议禁止空数组，使用明确`GLOBAL`代码表示全区域；CUSTOM必须逐项命中且`GLOBAL`仅ALL可创建/更新。区域代码来源、规范化、重复和停用校验也需冻结。

### `SCM-V3-CARRIER-0-R1-P1-003`：幂等重放未要求重新授权

合同定义动作账本和回放，但没有规定重放前重新执行当前用户、渠道、tenant、exact permission和DataScope检查。用户权限被撤销后可能利用旧Idempotency-Key读取历史响应或继续操作。

整改：重放查账本前或返回结果前重新执行完整授权；账本响应快照必须使用当前DTO脱敏规则，不能保存/回放完整PII。无权时返回404/403而不是replayed成功。

### `SCM-V3-CARRIER-0-R1-P1-004`：生效窗与active状态的选择条件未闭合

合同说“动作时点校验”，但没有明确列表、创建订单或发运选择Carrier时必须同时满足status=active、effective_from<=now、effective_to为空或>now。也未定义修改生效窗是否允许让已被引用Carrier立即失效。

整改：冻结`is_selectable(at)`唯一规则；历史详情不受可选择性过滤；缩短生效窗只影响新引用并生成审计事件。失效Carrier不得通过普通update重新激活或延长窗口绕过专用权限。

## 3. P2问题

### `P2-001` PUT全量字段与不可变字段边界

PUT称“全量可变字段”，但应明确缺失字段是400而不是清空，并列出code/tenant/status/version/audit不可提交。建议后续serializer合同锁定字段集合。

### `P2-002` 联系信息详情返回过宽

仅`supply.carrier.view`即可看到完整PII可能不符合最小权限。处理决定：第一期详情仍默认脱敏；如业务确需完整联系方式，另设`supply.carrier.contact.view`并审核，不在Carrier-1默认开放。

### `P2-003` alias迁移的唯一性和保留期

重复代码alias映射需明确tenant+source_system+source_id唯一且只读，避免以后作为业务查询入口。进入迁移实现前补测试。

## 4. 准入决定

当前合同可以作为整改草案，不可进入模型和服务开发。不得创建Carrier migration、permission seed或API；不得读取或回填正式历史数据。

## 5. 下一门禁

下一步执行：`SCM-V3-CARRIER-0 P1整改`，关闭计费字段、区域/CUSTOM、重放重新授权和可选择性四项合同，然后进行快速复核。
