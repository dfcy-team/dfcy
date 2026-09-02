# SCM-V3-MAP-1 剩余P1第二次快速复核

- 日期：2026-08-12
- 结论：`PASS`
- MAP-1状态：`P1_REMEDIATED_READY_FOR_DOMAIN_CONTRACTS`

## 1. 复核证据

| 门禁 | 结果 | 证据 |
| --- | --- | --- |
| FK删除策略 | PASS | tenant及跨聚合FK=PROTECT；私有明细=CASCADE；完成聚合禁止物理删除；延后字符串`PROTECT/CASCADE按...`数量0 |
| 数据保留 | PASS | `RET-AUDIT/RET-PII/RET-MEDIA/RET-TRANSIENT`已定义，含匿名化、二进制删除和日志禁入责任 |
| Exact permission | PASS | 斜杠缩写数量0；各动作独立code；外部supplier submit使用capability |
| API真实路径 | PASS | 错误`/api/internal/supply-chain/orders/`不存在；当前真实`/api/internal/purchasing/supply-orders/`已写入 |
| HTTP状态 | PASS | 成功200/201/202/204及400/401/403/404/409/429通用合同已冻结 |
| 文件门禁 | PASS | 整改文件NUL=0，UTF-8可读，`git diff --check`无错误 |

## 2. P1关闭

- `SCM-V3-MAP-1-R1-P1-001`：CLOSED。
- `SCM-V3-MAP-1-R1-P1-002`：CLOSED。
- `SCM-V3-MAP-1-R1-P1-003`：CLOSED。
- `SCM-V3-MAP-1-R1-P1-004`：CLOSED。
- `SCM-V3-MAP-1-R1-P1-005`：CLOSED。

## 3. 准入边界

MAP-1现在只准入“新领域合同立项与独立审核”。以下仍未获授权：

- Django模型及migration；
- API实现、前端或小程序业务页面；
- 历史数据读取/回填；
- 正式系统连接、部署或写入。

API矩阵中的`PROPOSED`路径在相应领域合同中仍需拆成逐动作serializer/DTO/error contract并独立审核，不能因MAP-1通过直接编码。

## 4. 建议开发顺序

按依赖关系建议：

1. `SCM-V3-CARRIER-0` 货运方主数据合同；
2. `SCM-V3-DIRECT-0` 散货直发合同；
3. `SCM-V3-CONTAINER-0` 柜货聚合合同；
4. Setting、Cost、Clearance、Notification、Rating依次独立立项。

下一步应启动首个新领域合同，而不是直接进入实现。
