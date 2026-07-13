# P3-A-006 配置中心后端模型变更日志

## 交付

- 新增全局 `SystemConfigDefinition`、tenant/系统范围 `TenantConfigVersion` 和不可变 `ConfigChangeLog`。
- 使用 `scope_key` 明确区分 `system` 与 `tenant:<id>`，支持版本递增、生效时间、审批、创建/审批分离和回滚生成新版本。
- 新增定义、版本、审批、回滚和变更日志接口，并按 tenant、系统配置权限和动作权限过滤。
- 配置版本与变更日志只能通过服务写入，普通 create/update/bulk 无法绕过版本和审计。

## 安全边界

- 禁止密钥、Token、Cookie、Session、密码和凭据类配置键和值。
- 敏感定义不允许明文默认值，只允许明确 demo/placeholder 引用元数据；API 永远返回 `***`。
- 高风险/需审批配置必须由不同于创建人的授权审批人批准。
- external 与 RPA 用户不能访问 internal 配置接口。

## 验证

- P3-A-006 定向测试：`15 passed`。
- 全量 pytest：`233 passed`。
- Django check：通过，`0 issues`。
- 迁移一致性：通过，`No changes detected`。
- 全新临时数据库迁移与权限目录检查：通过，`Permission catalog is complete`。
- 安全文件扫描、Docker Compose 配置与 `git diff --check`：通过。
