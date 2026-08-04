# A-PR1-P1-FIX 整改变更日志

## 1. 整改范围

本次仅关闭 `a_pr1_arch_security_r1_review.md` 中四项 P1，不进入 PR-A2，不实现 OAuth/callback，不连接 Shopee、TikTok Shop 或其他真实平台。

| P1 编号 | 整改结果 | 主要证据 |
|---|---|---|
| A-PR1-R1-P1-001 | 关闭 | 授权记录只能由服务创建；tenant/config/store、平台身份、scope、状态、引用和 actor 均受保护；QuerySet delete/bulk/update、实例 delete、配置引用直写与 Admin 绕过均有负向测试 |
| A-PR1-R1-P1-002 | 关闭 | 移除内容关键字猜测；采用显式 Mock provenance；`0007/0008/0009` 分离结构、全量预检转换和旧列删除；未知混合批次零写入失败并可重跑 |
| A-PR1-R1-P1-003 | 关闭 | 门店授权列表和详情响应移除 `merchant_subject_id`、`shop_cipher` 原值，并覆盖响应文本与审计文本测试 |
| A-PR1-R1-P1-004 | 关闭 | 配置和门店引用轮换记录 old/new 引用版本、撤销状态与稳定错误码；撤销失败保持旧引用并追加失败审计；MySQL 双线程同版本轮换一个成功、一个冲突 |

同时关闭 R1 的 P2 观察项：进入 `error` 状态必须提供符合 `[A-Z][A-Z0-9_]{2,79}` 的稳定错误码。

## 2. 实现说明

- `MarketplaceStoreAuthorization` 服务上下文外禁止创建，身份键必须由 platform、region、platform store ID 确定性计算。
- `PlatformIntegrationConfig` 引用字段只能由 `rotate_config_references()` 更新；配置创建 API 不再接受引用字段。
- 默认 revoker 仅处理 `synthetic-*` 测试引用，不包含真实密钥托管或平台调用。
- 轮换审计只保存引用 ID、掩码、版本、撤销状态和错误码，不保存凭据内容、平台响应或身份原值。
- 迁移兼容两类数据库：全新库保留旧列至预检完成；已执行旧版 `0007` 且旧列已删除的库安全跳过兼容步骤。部分旧 schema 会阻断并要求人工复核。

## 3. 验证结果

| 检查 | 结果 |
|---|---|
| Django `check` | PASS，0 issue |
| `makemigrations --check --dry-run` | PASS，无漂移 |
| A1 定向回归 | PASS，78 passed；SQLite 跳过 1 条 MySQL 锁测试 |
| MySQL 并发轮换 | PASS，1 passed |
| 后端全量 | PASS，本地 SQLite 439 passed / 1 MySQL-only skipped |
| `npm ci` | PASS；250 packages |
| 前端测试 | PASS，12 files / 160 tests；本机默认并发两次因内存不足失败，限制为 1 worker 后通过；Sandbox 默认并发通过 |
| 前端生产构建 | PASS，1955 modules；无 chunk size warning；存在上游 PURE 注释移除提示 |
| MySQL 8.4.10 全新迁移 | PASS |
| 安全 Mock 迁移 | PASS，Platform/API 各 1 条 |
| 未知混合批次 | 预期失败；Platform/API 引用写入均为 0，`0008` 未登记 |
| 失败修正后重跑 | PASS，2 条 Platform 引用完成转换，旧列为 0 |
| metadata lock | PASS，待处理锁为 0 |
| `sandbox.ps1 verify integration` | PASS；最终代码容器内 MySQL backend 440、frontend 160、build 成功 |
| CI guard | PASS |
| 高置信凭据模式扫描 | PASS，0 文件 |
| Git 构建/缓存制品 | PASS，未跟踪 dist、node_modules、pytest/vite cache、pyc 或 `.env.local` |

## 4. 已知观察项

- `npm audit --omit=dev` 仍报告既有 PostCSS high advisory 1 项。本整改未修改前端依赖，需独立依赖升级与前端回归。
- 最终全新 MySQL 全量迁移耗时 36.24 秒，三项授权迁移均已登记，旧敏感列余数为 0。
- MySQL 对 `finance.ReconciliationMatch` 条件唯一约束的既有 warning 与本次 integrations 整改无关。
- 本次所有数据库和 Sandbox 数据均为本机合成 fixture；没有执行真实平台授权、请求、Token 刷新或高风险自动化。

## 5. 安全确认

- 未提交真实账号、密码、Token、Cookie、Session、API Key、API Secret 或私钥。
- 未提交真实店铺、商家主体、订单、库存、供应商、财务或银行数据。
- 未接入真实 Shopee、TikTok Shop、BigSeller、银行或支付平台。
- 未进入 PR-A2；所有能力继续标记为 `pending/mock`，没有标记 `connected`。
