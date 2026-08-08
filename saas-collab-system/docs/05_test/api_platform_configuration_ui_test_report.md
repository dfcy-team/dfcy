# API 平台连接配置开发测试报告

日期：2026-08-08
分支：`feature/module-a-api-configuration-ui`
基线：`a276fa647081ccdec1484473450d2b0828479480`

## 已通过

| 验证项 | 结果 |
|---|---|
| Django `check` | PASS |
| `makemigrations --check --dry-run` | PASS |
| 全新 SQLite migration | PASS |
| 从 integrations 0013 / permissions 0015 升级 migration | PASS |
| 配置、权限、幂等、write-only focused pytest | 20 PASS |
| 后端全量 pytest | 530 PASS / 3 SKIP |
| 前端全量 Vitest | 165 PASS |
| 前端 production build | PASS，1963 modules transformed |
| CI guard / forbidden artifact / high-confidence credential scan | PASS |
| `git diff --check` | PASS |

安全测试覆盖：普通接口拒绝原始凭据、固定掩码、托管返回值不可信、响应/审计不含请求原文、Idempotency-Key 重放、相同 key 不同 payload 冲突、陈旧版本在调用托管前拒绝、独立清除 action、tenant 404、exact permission 和 data scope。

## 尚未作为 PASS 证据

- MySQL 8.4 migration 与双 worker 并发：尚未在数据库 VM 执行。
- 应用 VM HTTPS 页面、浏览器 storage/network/console 扫描：尚未部署固定制品。
- Shopee/TikTok 真实 OAuth、authorized shop、refresh、revoke、reauthorization 与最小只读 API：尚未使用固定部署制品验证。
- Credential Custody：默认后端保持 fail closed；在批准的 custody endpoint 配置前，真实凭据写入返回受控失败。
- 远端 CI、artifact SHA/image digest：尚未推送并构建。

因此当前结论只能是：

```text
Shopee = pending/live-validation
TikTok Shop = pending/live-validation
Production synchronization = OFF
```
