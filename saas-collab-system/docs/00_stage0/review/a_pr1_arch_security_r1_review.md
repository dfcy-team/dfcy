# A-PR1-ARCH-SEC-R1 架构与安全复审报告

## 1. 复审对象

- 对应 PR：[#39](https://github.com/dfcy-team/dfcy/pull/39)。
- 实现分支：`feature/module-a-platform-auth-foundation`。
- 审核 HEAD：`bf90a5d21c1ba9c981f8cb67ef28f53e8801238d`。
- stacked base：`feature/module-a-sales-inventory-finance` / `bdad2fed25b3897f3f6aeae67d18d5f7239ca4a1`。
- 审核范围：A-01 至 A-03 的合同、模型、迁移、引用式凭据、权限、data scope、只读 API、审计、测试与发布边界。
- 审核性质：独立只审核；除本报告外不修改业务实现。

PR #39 当前仍为 Draft，且基线 PR #37 尚未合并。远端检查全部成功，但无独立 review。自动化成功不能替代下述安全不变量复核。

## 2. 复审结论

**不通过（BLOCKED）**。

未发现真实 Shopee/TikTok Shop 请求、真实凭据、生产连接或高风险自动化；但发现 4 项未关闭 P1。当前仅允许定向整改并执行 R2 复审，不允许进入 PR-A2 OAuth/callback 实现，不允许标记 `connected`，不允许真实 Sandbox、Pilot 或 Production 执行。

## 3. 已通过项

- A1 变更范围集中在授权基础模型、迁移、服务、权限、只读 API、测试和文档，未注册 authorize、callback、refresh、revoke、sync 或 retry 业务路由。
- 新只读 API 要求 internal 用户、`integrations.store.view` 和 permission-specific data scope；列表分页、未知参数拒绝、跨 tenant 详情 404 已有测试。
- `credential_id` 与 `token_id` 在配置 API 中为 write-only，在门店授权 serializer 中未直接返回；raw Token、Secret、Cookie、Session 等顶层字段有拒绝逻辑。
- 授权状态转换使用事务与行锁；`revoked` 终态和引用版本递增有测试。
- `IntegrationAuditLog` 实例更新、QuerySet update/delete、bulk update 和管理后台修改/删除均被禁止。
- 新权限目录、迁移和 `platforms/store_ids` CUSTOM scope 的缺失、空、未知、非法、跨 tenant 负向测试已覆盖。
- 未发现本次变更引入真实平台 SDK/HTTP、真实业务数据、生产部署或高风险动作。

## 4. P1 问题

| 编号 | 问题 | 证据与影响 | 关闭标准 |
|---|---|---|---|
| A-PR1-R1-P1-001 | 门店授权的服务层、tenant/身份归属和不可删除不变量可被 ORM 绕过 | `MarketplaceStoreAuthorization.save()` 允许普通代码直接创建 `pending` 记录；`MarketplaceStoreAuthorizationQuerySet` 未覆盖 `delete()`，且 `protected_fields` 不包含 tenant、integration config、store、platform、region、平台门店 ID、身份键、商家主体、shop cipher、scopes 与操作者。独立内存库复现证明：可无服务创建且审计为 0，可用 QuerySet 跨 tenant 更新，也可用 QuerySet 删除。结果是授权归属、全局身份键、审计和不可删除合同均不可信。`PlatformIntegrationConfig` 的引用字段同样可被 ORM 直接更新而绕过原子轮换审计。 | 禁止服务上下文外的所有门店授权创建；保护所有归属、身份、状态、引用、scope 和操作者字段；禁止 QuerySet delete、bulk create、受保护 bulk update/update 及实例 delete；配置引用只能经轮换服务变更。补充 direct save/create、QuerySet update/delete、bulk、admin、跨 tenant、身份键不一致和无审计写入的负向测试。 |
| A-PR1-R1-P1-002 | 旧凭据迁移采用易误判的内容关键字并在 MySQL 上缺少全量预检 | `_is_safe_mock_value()` 只要字符串包含 `mock`、`demo`、`example` 等子串即视为安全；独立复现中 `live-example-credential` 被判为安全。真实随机值或命名值可能偶然命中，随后旧列被删除，构成不可逆凭据丢失。迁移在扫描期间已逐条保存安全记录，最后才因 `blocked_count` 抛错；MySQL DDL 不具备报告声称的整体事务回滚保证，发布说明“数据库事务会回滚”不成立。 | 不以内容子串推断 Mock。先只读预检全部旧记录，在任何写入和删列前完成基于受控来源/显式批准清单的精确判定；发现一条未知记录即零写入失败。将数据迁移与删列分阶段，并在 MySQL 8.4 验证失败原子性、重跑、锁与耗时。修正文档中的回滚承诺，补误命中、混合安全/未知批次和 MySQL 失败重跑测试。 |
| A-PR1-R1-P1-003 | 只读 API 暴露合同规定仅后端持有的授权标识 | `MarketplaceStoreAuthorizationSerializer` 返回 `merchant_subject_id` 和 `shop_cipher`。A1 合同将商家主体 ID 定义为不用于界面明文展示，内部 API 对齐表也未把这两个字段列为响应字段。独立 serializer 复现确认两个字段均进入响应。拥有 view 权限的内部用户因此可读取不必要的平台授权标识。 | 从列表/详情响应移除这两个原值；如业务确需展示，先冻结独立脱敏字段与 exact permission 合同。补列表、详情、序列化文本和日志均不含原值的回归测试。 |
| A-PR1-R1-P1-004 | 门店引用轮换没有保留旧引用撤销证据 | `rotate_store_authorization_references()` 覆盖旧 `credential_id/token_id` 后才调用 `_audit()`；审计仅包含新引用，没有旧引用 ID、旧版本或托管撤销结果。合同要求原子替换并追加旧引用撤销审计，当前无法证明旧引用已撤销，也无法追溯轮换链。 | 在行锁事务内保留旧引用元数据，完成托管撤销或记录明确的 pending/failed 状态，再写不可变审计；不得记录凭据内容。补旧/新版本链、撤销失败回滚、并发轮换与日志脱敏测试。 |

## 5. P2 与非阻断观察

1. `transition_store_authorization(..., target_status="error")` 允许空 `error_code`，与“失败只记录稳定错误码”合同不完全一致；整改时应要求受控非空错误码并限制格式。
2. 前端构建仍有第三方 `@vueuse/core` PURE 注释位置提示，不影响本次构建结果。
3. 本地 `backend/db.sqlite3` 的历史孤立表问题不属于本次复审改动；不得通过删除用户本地数据库掩盖迁移问题。

## 6. 独立验证结果

2026-08-04 在审核 HEAD 执行：

| 检查 | 结果 | 说明 |
|---|---|---|
| `manage.py check` | PASS | 0 issues |
| `makemigrations --check --dry-run` | PASS | 无迁移漂移 |
| A1/集成/系统定向测试 | PASS | 60 passed |
| 后端全量 pytest | PASS | 433 passed |
| 前端全量测试 | PASS | 12 files / 160 tests |
| 前端生产构建 | PASS | 构建成功；仅第三方 PURE 注释提示 |
| GitHub PR #39 checks | PASS | 当前可见检查均为 SUCCESS |
| 安全不变量独立复现 | FAIL | 直接创建无审计、跨 tenant QuerySet update、QuerySet delete、后端专用字段暴露、迁移标记误判均复现 |
| Local Sandbox integration / MySQL 8.4 | BLOCKED | Docker Desktop Linux engine 未运行 |

全量测试通过只说明现有断言通过；现有测试未覆盖上述五个可复现的绕过与误判路径。

## 7. R2 复审前置条件

1. 仅整改 4 项 P1 及其直接产生的测试、迁移和文档，不扩展到 PR-A2。
2. 在固定新 HEAD 重跑 Django check、迁移一致性、A1 定向测试、后端全量测试、前端 test/build 和仓库安全门禁。
3. 启动 Docker Desktop 后，在 MySQL 8.4 Local Sandbox 验证全新迁移、含安全 Mock 数据迁移、含未知记录零写入失败、失败后重跑、结构回退和 integration profile。
4. PR #37 合并后，将 A1 同步到最新 `main`，重新运行全量 CI 与 integration 验证，并以独立 R2 报告确认 P1 全部关闭。
5. R2 PASS 之后，PR-A2 开工前仍须从获批应用控制台复核 Shopee/TikTok Shop 的精确 scope、endpoint、区域、限流、回调域名和密钥托管方案。

## 8. 是否允许进入 PR-A2

**不允许。**

当前存在 4 项未关闭 P1，MySQL 8.4 迁移验证缺失，PR #37 与 PR #39 均仍为未合并 Draft。下一步是 `A-PR1-P1-FIX` 定向整改，完成后执行 `A-PR1-ARCH-SEC-R2`；在 R2 PASS 前不得实现 OAuth/callback 或任何真实平台请求。
