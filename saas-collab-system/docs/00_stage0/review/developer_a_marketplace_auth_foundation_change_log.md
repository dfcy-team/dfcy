# 开发A Shopee / TikTok Shop 授权基础变更日志

## 1. 基线与提交

- 任务：`A-PR1-PLATFORM-AUTH-FOUNDATION`，A-01 至 A-03。
- 分支：`feature/module-a-platform-auth-foundation`。
- stacked base：`feature/module-a-sales-inventory-finance`。
- 基线：`bdad2fed25b3897f3f6aeae67d18d5f7239ca4a1`。
- A-01：`4d4d09a`，冻结平台授权合同与对齐矩阵。
- A-02：`f2a25e5`，门店授权模型、状态保护和迁移。
- A-03：`06fa8f8`，引用式凭据、权限、scope、只读 API 与负向测试。

## 2. 实际变更

- `PlatformIntegrationConfig` 继续作为唯一连接配置主模型，新增 `credential_id/token_id`、掩码和引用版本元数据。
- `APIIntegrationConfig` 标记为 legacy，不新增 Shopee/TikTok Shop 能力。
- 新增 `MarketplaceStoreAuthorization`，复用 `StoreMaster`，校验 tenant、platform、TikTok `shop_cipher`，并通过全局身份哈希阻止跨 tenant 重复绑定。
- 授权状态只能由事务服务修改；直接模型更新、受保护 QuerySet update 和 bulk 写入不可绕过状态规则。
- 新增引用原子轮换、撤销/过期/失败/重试基础和只追加审计；审计仅保存引用 ID、掩码、状态、错误码和操作者。
- 新 API 拒绝 raw Token、Secret、Cookie、Session 和通用 `credentials`。
- 新增六个 exact action permission 与 `platforms/store_ids` CUSTOM scope。
- 仅开放 `GET /api/internal/integrations/store-authorizations/` 和详情；OAuth、callback、refresh、revoke、sync、retry 路由均未注册。

## 3. 旧字段迁移

- `0007` 先添加引用字段，再检查旧敏感字段。
- 明确 synthetic/mock 内容转换为基于记录 ID 的 synthetic reference；不复制旧值。
- 来源未知或非 Mock 内容会让迁移整体中止，只在异常中报告阻断记录数量，不输出字段值。
- 转换完成后删除 `credential_ciphertext`、`api_key_encrypted`、`api_secret_encrypted`。
- 在全新临时 SQLite 数据库执行完整迁移成功；`0007 -> 0006 -> 0007` 结构往返成功。
- 本机既有 `backend/db.sqlite3` 存在已回退旧实现留下的同名孤立表，默认库迁移因此报 `table already exists`；未删除或修改该本地数据库。
- MySQL 容器级迁移未执行成功，因为 Docker Desktop Linux engine 未运行。专项测试已确认迁移不含 `RunSQL`，数据迁移只使用 Django ORM；MySQL 运行时验证仍是复审前待办。

## 4. 条件性修改

修改 `backend/apps/accounts/system_views.py`：安全运维查询改为返回引用掩码和引用版本，并将合同标识更新为 `external_reference_metadata_only`。影响仅限只读安全元数据；回滚时恢复旧字段列表与合同字符串即可，不涉及业务写入。

## 5. 验证结果

| 检查 | 结果 |
|---|---|
| `manage.py check` | 通过，0 issue |
| `makemigrations --check --dry-run` | 通过，无遗漏迁移 |
| 全新数据库 `migrate --noinput` | 通过 |
| `sync_permissions --check` | 通过 |
| integrations/sync/授权专项 | 53 passed |
| 扩展回归集合 | 60 passed |
| 后端全量 pytest | 433 passed |
| 前端测试 | 160 passed |
| 前端构建 | 成功，无 chunk size warning；有依赖 PURE 注释移除提示 |
| Local Sandbox contract | PASS |
| Local Sandbox verify integration | 阻断：Docker Desktop Linux engine 未运行 |
| CI guard | PASS，无高置信凭据或禁止文件 |
| npm audit | full 2 high；production 1 high，均为既有前端依赖，本任务禁止修改 frontend |
| API 路径扫描 | 未新增 `/api/finance/*`、`/api/rpa/*`、`/admin/` 或真实平台请求 |
| Git artifact 检查 | `dist/node_modules/.npm-cache/db/log/screenshot/.env` 均未跟踪 |

## 6. 权限与安全结论

- 六个门店权限独立求值，旧 `integrations.view/manage/rotate/run` 不替代新权限。
- 缺失、空、未知、非法及跨 tenant `store_ids` scope 均有负向测试。
- 普通 internal、external、RPA 和未认证用户均不能访问新 internal 资源。
- 跨 tenant/store 详情返回 404。
- 未提交真实账号、门店、订单、库存、Token、Cookie、Session、API Key 或 API Secret。
- 未连接 Shopee、TikTok Shop、BigSeller、银行或支付平台。
- 未实现 OAuth、真实平台 SDK/HTTP、销售库存导入或高风险自动化。
- 当前能力状态仅为 `pending` 或 `mock`，无 `connected`。

## 7. 待办与风险

1. 启动 Docker Desktop 后，在 MySQL 8.4 Local Sandbox 重跑 `verify integration`，补齐真实 MySQL migration/runtime 证据。
2. PR #37 合并后同步最新 main，重跑全量测试和 integration verify。
3. A-01 合同完成架构与安全审核后，才可进入 PR-A2 OAuth/callback 实现。
4. 前端生产依赖 PostCSS high advisory 需由前端依赖维护任务单独升级和回归；本 PR 不越界修改。
