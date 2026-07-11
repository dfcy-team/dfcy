# 阶段3 API 契约规划

所有接口使用 `{ success, code, message, data }`，支持 tenant过滤、分页、时间范围和审计。未实现接口只能标记 `pending` 或 `mock`，实现并完成契约/权限验证后才可标记 `connected`。

| 分区 | 使用角色 | tenant/数据范围 | 参数与分页 | 导出与敏感字段 | 初始状态 |
|---|---|---|---|---|---|
| `/api/internal/analytics/*` | internal 分析用户 | tenant + data_scope | date_range、维度、page、page_size | 导出需单独权限；财务聚合脱敏 | pending |
| `/api/internal/alerts/*` | internal 预警处理人 | tenant + 负责人范围 | status、level、时间范围、分页 | 处理记录审计；不含凭据 | pending |
| `/api/internal/replenishment/*` | internal 授权人员 | tenant + 商品范围 | 商品、仓库、时间范围、分页 | 只返回建议；不创建采购单 | pending |
| `/api/internal/lifecycle/*` | internal 授权人员 | tenant + 商品范围 | 状态、规则版本、时间范围、分页 | 只返回建议/审计；不改状态 | pending |
| `/api/internal/config/*` | 配置管理员 | tenant级或系统级受限范围 | config_key、version、page、page_size | 敏感值不返回；变更/导出审计 | pending |
| `/api/finance/analytics/*` | 财务权限用户 | tenant + finance permission | date_range、币种、分页 | 聚合/掩码；导出需 finance.export | pending |
| `/api/report/*` | 后端授权用户 | tenant + data_scope | report、日期、维度、分页 | 导出审计；敏感字段脱敏 | pending |
| `/api/external/supplier/performance/*` | external supplier | tenant + 当前 supplier_id | period、page、page_size | 不返回内部/财务字段 | existing/connected |

任何接口不得返回真实平台密钥、完整银行信息、Cookie、Session、Token 或跨 tenant 数据。建议、预警和配置接口不提供真实高风险执行能力。

