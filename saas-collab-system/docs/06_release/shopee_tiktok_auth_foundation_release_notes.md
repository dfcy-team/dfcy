# Shopee / TikTok Shop 授权基础发布说明

## 发布内容

- 冻结 Shopee Open Platform v2 与 TikTok Shop OAuth/日期版本基础合同。
- 增加 tenant/store scoped 门店授权记录、全局平台身份约束、服务层状态机和不可变审计。
- 增加外部 `credential_id/token_id` 引用元数据和 synthetic Mock 轮换服务。
- 增加六个门店 exact permission 与 `platforms/store_ids` scope。
- 增加 scoped 只读列表/详情。所有真实授权与平台操作仍为 `pending`。

## 迁移门禁

1. `integrations.0007` 新增引用字段、门店授权表、唯一约束和审计 PROTECT。
2. 如果任一旧 `PlatformIntegrationConfig.credential_ciphertext` 非空，迁移会主动失败。
3. 部署人员必须在批准的外部密钥系统中建立引用，并通过受审迁移流程写入 reference 元数据后，才能重新执行迁移。
4. 禁止为了通过迁移而清空、打印、导出到日志或复制旧密文。
5. `permissions.0015` 只新增目录项，不自动给任何角色授予权限。

## 回滚

- 这是 L3 数据结构变更。回滚前必须备份并确认没有需要保留的门店授权或审计记录。
- 不允许通过删除审计或清空凭据字段回滚。若已产生记录，应先由架构与安全人员批准数据保留/迁移方案。
- 权限迁移的 reverse 为 noop，回滚 schema 不会自动删除权限目录项，避免破坏已审计角色关系；如确需清理须另行受控迁移。
- PR #37 未合并期间，本 PR 必须以 stacked Draft 方式依赖 `feature/module-a-sales-inventory-finance`。

## 已知阻塞

- Local Sandbox contract 通过，但 Docker Desktop Linux engine 未运行，integration verify 未完成。
- npm audit 存在既有依赖风险：完整树 2 high，生产树 1 high；需独立前端依赖升级 PR。
- 生产区域允许列表为空，没有真实 OAuth、callback、refresh、revoke、sync、retry 或平台 HTTP。

## 安全声明

- 未连接真实 Shopee 或 TikTok Shop。
- 未提交真实账号、门店、订单、库存、Token、Cookie、Session、API Key 或 API Secret。
- 业务库不接受新原始凭据或新密文；API 只显示掩码与非敏感元数据。
- Mock `active`、HTTP 200、迁移成功或本地测试通过都不代表平台能力 `connected`。
