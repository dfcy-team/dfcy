# SCM-V3-MAP-1 P1整改报告

- 日期：2026-08-12
- 状态：`READY_FOR_P1_RECHECK`
- 约束：仅映射合同，不授权实现

| P1 | 整改证据 | 结果 |
| --- | --- | --- |
| P1-001字段级映射 | `map_1_field_matrix`：31个唯一FIELD ID，覆盖源21实体及后端核心扩展，含类型/约束/PII/转换 | 待复核关闭 |
| P1-002 exact权限/DataScope | `permission_datascope_matrix`：9个领域权限组，冻结exact codes、通道及ALL/CUSTOM/OWN决定 | 待复核关闭 |
| P1-003 API具体合同 | `api_matrix`：method/path/channel/permission/request/response/幂等/version；新路径标PROPOSED | 待复核关闭 |
| P1-004 direct聚合 | `direct_dispatch_contract`：选择独立DirectShipment，冻结5态、箱消费、附件、取消更正和历史分类 | 待复核关闭 |
| P1-005迁移回滚 | `migration_rollback_matrix`：每波摘要、阈值、checkpoint、回滚和零容忍项 | 待复核关闭 |

P2同步决定：字段矩阵包含PII/附件安全；Rating边界留给独立合同；API矩阵为后续页面→API→权限→测试证据链提供稳定API ID。

本轮没有修改Django模型、迁移、API实现、客户端或数据库。下一步执行`SCM-V3-MAP-1 P1整改复核`；通过前不得进入任何新领域开发。
