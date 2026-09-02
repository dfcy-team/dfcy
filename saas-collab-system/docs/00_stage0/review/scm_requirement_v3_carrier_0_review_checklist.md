# SCM-V3-CARRIER-0 P1 整改复核清单

| 检查项 | 通过标准 |
| --- | --- |
| 聚合边界 | Carrier 不承载费用历史、发运状态或结算 |
| 唯一性 | tenant+normalized_code，trim/lower 与 MySQL 语义明确 |
| 计费模型 | freight_type 与 rate_unit 一一映射；rate_amount/currency/null/零值约束完整 |
| 区域 | region_codes 非空；GLOBAL 显式且不可混用；来源、规范化、重复和 active 校验冻结 |
| 可选择性 | `is_selectable(at)` 公式唯一；过期延长/重新启用不能由普通 update 绕过 |
| 生命周期 | 禁止 delete；停用不破坏历史；code/tenant 不可修改 |
| 引用快照 | FK PROTECT，业务身份快照与 Cost 费用版本分离 |
| PII | 列表和详情默认脱敏；日志、事件、错误、幂等账本禁完整值 |
| 权限 | 四个 exact code 逐动作校验，不按角色名授权 |
| DataScope | ALL/CUSTOM 明确；CUSTOM 同时覆盖 carrier_ids 和全部区域；GLOBAL 仅 ALL |
| 渠道 | internal-only，supplier/miniapp token 不可调用 |
| API | 路径、DTO、HTTP、严格 PUT、expected_version、404 防枚举明确 |
| 幂等 | 重放重新执行当前授权/DataScope；响应按当前脱敏 DTO 重建 |
| 并发/ORM | 创建、更新、停用竞争及 DB/ORM 绕过门禁完整 |
| 历史迁移 | alias 三元唯一、不可变、只读；计数守恒、回滚、隔离明确 |
| P2 决定 | PUT、联系人 PII、alias 保留三项均有冻结决定 |
| 范围 | 合同不授权实现、迁移或生产操作 |

复核输出必须给出 PASS/BLOCKED、P1/P2 关闭状态及下一准入门。
