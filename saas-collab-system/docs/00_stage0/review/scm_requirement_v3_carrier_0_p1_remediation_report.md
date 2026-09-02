# SCM-V3-CARRIER-0 P1 整改报告

- 日期：2026-08-12
- 范围：合同与审核清单；未修改代码、模型、迁移、数据库或生产环境

## 整改结果

| 编号 | 结果 | 关闭证据 |
| --- | --- | --- |
| R1-P1-001 | CLOSED | 以 rate_amount/rate_unit 替代单一 cost_per_cbm，冻结六类映射、金额/币种/零值和数据库约束 |
| R1-P1-002 | CLOSED | region_codes 禁空；GLOBAL 显式且仅 ALL；CUSTOM 逐区域校验并禁止 GLOBAL |
| R1-P1-003 | CLOSED | 幂等重放必须按当前身份、权限、DataScope 重新授权，并按当前脱敏 DTO 重建 |
| R1-P1-004 | CLOSED | 冻结唯一 is_selectable(at)；普通 update 不得恢复停用或已过期记录 |

## P2 决定

- P2-001 CLOSED：PUT 为严格全量替换，缺字段400，首期不支持 PATCH。
- P2-002 CLOSED：详情默认脱敏；完整联系人权限另立项。
- P2-003 CLOSED：alias 采用 tenant/source_system/source_id 唯一且不可变，只用于迁移审计。

## 下一门禁

执行 `SCM-V3-CARRIER-0 P1 整改快速复核`。只有复核 PASS 才能进入 Carrier-1 本地模型与领域服务开发。
