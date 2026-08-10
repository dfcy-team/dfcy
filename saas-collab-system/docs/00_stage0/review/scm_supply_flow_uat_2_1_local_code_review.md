# SC-SUPPLY-FLOW-UAT-2-1 本地代码审核

- 日期：2026-08-09
- 审核基线：`3d42f65` 后的 UAT-2-1 工作区变更
- 范围：短期凭据租约、内部/供应商/小程序认证到期门禁、激活/吊销工具
- 结论：`APPROVED_FOR_SCOPED_LOCAL_COMMIT`

## 1. 审核结论

实现为 `CustomUser` 增加四个可空或非秘密的 UAT 租约字段：激活时间、到期时间、批次摘要和状态。普通用户字段为空时认证行为不变；`SC-UAT-*` 用户必须具有 active 且未到期的租约。

统一门禁覆盖内部新登录、内部 refresh、已签发 access Token、小程序登录/签发/refresh，以及供应商 Web 登录、refresh 和 access。吊销或到期后，即使 Token 尚在 JWT 自身有效期内，也会在数据库用户加载后返回认证失败。

## 2. 供应商 Web 认证复核

新增 `/api/external/auth/login/` 和 `/api/external/auth/refresh/`，只允许 external 用户，并要求 active tenant、唯一 `ExternalUserProfile`、同 tenant supplier binding 和 active supplier。

Token 声明由服务端派生并固定包含 `channel=supplier_web`、`tenant_id`、`supplier_id` 和 external user type。refresh 与每次 access 都重新读取当前绑定，claim 过期或绑定变化立即拒绝。

JWT 认证层限制 supplier Web Token 仅访问 `/api/external/supplier/` 范围；访问 internal、miniapp 或其他 API 路径 fail-closed。内部/RPA/miniapp 身份不能通过 supplier Web 登录入口。

## 3. 凭据工具复核

`uat_credentials` 默认 dry-run，只接受冻结用户名白名单、精确 tenant、数据版本和本地数据库门禁。激活最长 8 小时，使用 `secrets` 安全随机源和 Django 密码校验；明文只通过交互式一次性 sink 存在于内存，不进入 JSON、元数据、数据库字段、文件或报告。

批量激活在事务内完成；sink 失败会回滚整个批次。已激活账号不能通过重复调用续期，必须先吊销。吊销将密码恢复为 unusable 并清除租约时间和摘要，不影响非 UAT 用户。

## 4. P1 整改

1. 初版只依赖 `DEBUG` 判断本地环境：已改为 settings 模块白名单、数据库名精确匹配、SQLite 网络路径拒绝和 MySQL loopback 限制。
2. 初版迁移依赖并行未提交的 `accounts.0003`：已改为已提交 `accounts.0002`，迁移仅包含四个 UAT `AddField`。
3. 初版供应商密码无可用 Web 登录入口：经用户授权新增最小 supplier Web login/refresh，并补充 claims、绑定和路径隔离。
4. supplier Token 可能访问通用 `IsAuthenticated` internal 端点：已在 JWT authentication 层增加路径门禁。
5. 提交后隔离工作树发现供应商状态枚举、用户 `full_name` 和 SKU `product_name` 来自其他未提交阶段：已分别改用已提交的通用状态枚举，并移除 UAT 生成器对两个并行字段的依赖，未夹带相关模型迁移。

上述 P1 均已关闭。

## 5. 验证证据

- Django `check`：通过；
- UAT-2-1 定向：`12 passed`；
- UAT-1：`8 passed`；
- 子代理 auth、miniapp、API2 回归：`22 passed`；
- 主工作区主审合并矩阵：`34 passed in 67.12s`；
- 干净 Git 基线：Django check 通过、`makemigrations --check` 输出 `No changes detected`、同一合并矩阵 `34 passed in 62.15s`；
- Python 编译与本轮 diff check：通过；
- 迁移测试确认 `accounts.0004` 仅依赖 `0002` 且只有四个 AddField。

当前共享工作区还存在另一阶段未提交的 `accounts.0003`，因此主工作区迁移图表现为 `0003/0004` 双叶。UAT 提交未包含或修改该并行迁移；干净 Git 基线已证明只有 `0004` 作为 accounts 叶节点且无迁移漂移。

## 6. 未准入事项

- 真实人工 UAT 登录和密码交付；
- MySQL UAT 凭据工具实证；
- Android/iPhone 真机验收；
- Sandbox、Pilot、Production 部署；
- 生产对象存储、微信正式环境和第三方物流/报关连接。

本次提交通过后，下一门禁为提交后干净迁移确认，再决定是否进入 `SC-SUPPLY-FLOW-UAT-3 本机人工 UAT 执行`。
