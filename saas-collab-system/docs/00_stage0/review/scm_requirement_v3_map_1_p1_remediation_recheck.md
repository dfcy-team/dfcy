# SCM-V3-MAP-1 P1整改复核

- 日期：2026-08-12
- 结论：`BLOCKED_REMAINING_P1`
- 实现准入：`NOT_ADMITTED`

## 1. 复核结果

| 原P1 | 结果 | 证据 |
| --- | --- | --- |
| P1-001 逐字段映射 | `PARTIAL` | 31个FIELD ID唯一且覆盖21个小程序实体，但部分FK删除策略及保留期仍未冻结 |
| P1-002 exact Permission/DataScope | `FAIL` | 权限以`supply.carrier.view/create/...`斜杠串表示，不是可seed和逐动作校验的独立code |
| P1-003 API具体合同 | `FAIL` | 26个API ID唯一，但至少一个标为既有/扩展的采购路径与当前真实路由不符 |
| P1-004 DirectShipment聚合 | `PASS` | 独立聚合、5态、箱消费、附件、权限、取消更正和历史分类明确 |
| P1-005 迁移回滚 | `PASS` | 七波均有摘要、阈值、失败处理；零容忍、checkpoint及切换回退边界明确 |

## 2. 剩余P1

### `R2-P1-001A` 字段合同仍含延后决策

通用合同写“tenant FK(PROTECT/CASCADE按生命周期合同)”，PackingBox也写“FK PROTECT/CASCADE按批次合同”。字段级冻结不能把`on_delete`继续留给开发阶段；账号/通知PII和视频只写“独立保留策略”，没有明确是长期审计、停用后匿名化或具体后续门禁。

整改：对每个PROPOSED聚合冻结FK删除策略；通常审计链和被业务引用主数据使用PROTECT，聚合私有明细随聚合CASCADE但完成聚合禁止物理删除。给PII/附件标明确的retention class，具体期限若依法配置则写配置责任和删除/匿名化动作。

### `R2-P1-002A` exact permission code必须逐个展开

例如 ``supply.container.view/create/update`` 不是多个合法code。整改后每个权限必须单独反引号列出，例如`supply.container.view`、`supply.container.create`；同时逐个绑定动作、通道和DataScope。`Box change submit`若供应商只用capability，不得暗示给外部用户分配内部permission。

### `R2-P1-003A` 现有API路径与代码不一致

矩阵中的：

`POST /api/internal/supply-chain/orders/{id}/actions/assign-shipping-route/`

当前真实路由为：

`POST /api/internal/purchasing/supply-orders/{id}/actions/assign-shipping-route/`

小程序完工动作当前路由模式是：

`POST /api/miniapp/supply-chain/orders/{id}/actions/complete-production/`

整改：所有标“既有/扩展”的路径必须从`config/urls.py`和各app `urls*.py`逐条反查；不存在的新路径必须标`PROPOSED`，不能标既有。API矩阵另补明确response status（200/201/204/409等），目前“状态”主要指业务状态而非HTTP状态。

## 3. 已通过检查

- 源第6章21个实体均有对应FIELD条目。
- FIELD ID 31个，唯一31个。
- API ID 26个，唯一26个。
- DirectShipment不污染regional groupage的LooseCargoShipment。
- 同箱单活动消费、accepted附件和跨租户为零容忍。
- BACKFILL数量/金额差异必须为0，SWITCH_WRITE不能无损回放时禁止切换。
- 整改文件均为UTF-8、NUL=0，`git diff --check`无错误。

## 4. 下一步

执行`SCM-V3-MAP-1 剩余P1快速整改`：只修字段删除/保留策略、展开exact permission code、校正API真实路径与HTTP状态。复核通过前不得新建模型、迁移或接口。
