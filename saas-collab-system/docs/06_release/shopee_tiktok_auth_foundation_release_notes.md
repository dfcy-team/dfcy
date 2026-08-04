# Shopee / TikTok Shop 授权基础发布说明

## 发布内容

- 冻结 Shopee/TikTok Shop 授权、身份、限流、错误、字段和安全合同。
- 新增 tenant/store scoped 门店授权模型，复用 `StoreMaster`。
- 将连接配置收敛到 `PlatformIntegrationConfig`，`APIIntegrationConfig` 保持 legacy。
- 业务库改为仅保存 Credential ID/Token ID 引用和脱敏元数据。
- 新增六个 exact action permission、`store_ids` scope 和只读 internal 查询。
- 授权审计改为只追加，禁止修改或删除。

## 非发布内容

不包含 OAuth、callback、Token 刷新、webhook 业务处理、真实平台请求、SKU 映射、订单/库存导入、真实 Sandbox、Pilot、Production 或 VM 部署。

## 迁移门禁

1. 上线前在数据库副本统计旧三个敏感字段的非空记录数，不输出值。
2. `integrations.0007` 只新增结构，`0008` 对全部旧记录执行只读预检后统一转换，`0009` 条件删除旧列。
3. 只接受显式批准的 Mock provenance 与受控测试元数据，不根据凭据内容关键字推断来源。
4. 任一未知或部分旧 schema 都会在业务写入前阻断；先完成密钥托管审批和专门迁移方案。
5. MySQL 8.4.10 已验证全新迁移、安全 Mock、未知记录零写入失败、修正后重跑和既有旧 `0007` 数据卷兼容。

## 回滚

- 应用回滚到基线 `bdad2fe` 前，可将 schema 退到 `integrations.0006`；本地临时 SQLite 已验证结构回退成功。
- 反向迁移只恢复空的旧列，不恢复已删除的旧凭据内容。真实凭据必须始终从密钥托管系统重新下发，不得从数据库或日志恢复。
- 若 `0008` 被未知旧内容阻断，因全量预检尚未开始业务写入，引用字段保持零写入且 `0008` 不登记完成；修正来源审批后可直接重跑。不得依赖 MySQL DDL 事务回滚，也不得手工清空或跳过检查。
- 新只读路由可通过应用版本回滚移除，不影响旧 integrations/sync 路由。

## 已知限制

- Local Sandbox integration 已通过；本次验证仅使用合成数据和本机 MySQL 8.4，不代表真实平台 Sandbox 已连接。
- 现有前端依赖审计仍有 high advisory，由独立前端依赖任务处理。
- 当前状态仅为 `pending/mock`；不得解释为真实平台已连接或获准生产使用。
