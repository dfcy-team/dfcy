# PR-A2 OAuth / Callback 验收清单

## 1. 开工与合同

- [ ] A1 R2 为 PASS，规划与实现均保持 stacked Draft。
- [ ] 获批控制台 endpoint、scope、版本、区域、配额和 callback URL 已由非开发者复核。
- [ ] 密钥托管、网络出口、紧急停止和回退取得书面安全批准。
- [ ] 未确认平台值保持 pending，代码中没有猜测常量。

## 2. 模型与服务

- [ ] OAuth attempt 只存 state/session/idempotency hash，不存原值。
- [ ] state 至少 256-bit、5 分钟 TTL、一次性原子消费。
- [ ] tenant/user/session/platform/config/store/region/redirect target 全部绑定。
- [ ] direct save、QuerySet update/delete、bulk、admin 和跨 tenant 写入不能绕过服务层。
- [ ] 外部调用使用 operation ID、saga 和补偿；不存在“数据库事务可回滚平台副作用”的错误假设。
- [ ] 审计只追加且完全脱敏。

## 3. API、权限与 scope

- [ ] initiate/status/refresh/revoke/retry 分别使用冻结路径和 exact permission。
- [ ] permission-specific `platforms/store_ids` 的 ALL、缺失、空、未知、非法、跨 tenant 和超范围组合均测试。
- [ ] external、RPA、普通 internal 和跨 tenant 用户全部被后端拒绝。
- [ ] callback 只允许平台枚举和合同字段；redirect target 只用服务端 allowlist code。
- [ ] 统一响应与 302/400/401/403/404/409/422/429/502/503 均有稳定断言。

## 4. 安全负向矩阵

- [ ] state 缺失、猜测、篡改、过期、重复、并发重复和跨绑定重放全部拒绝。
- [ ] callback code 重复、错误签名、错误平台、错误门店、未知参数和开放重定向全部拒绝。
- [ ] SSRF：未登记 host、HTTP、用户信息、非标准端口、loopback、link-local 和私网解析拒绝。
- [ ] 托管成功/失败/超时、平台 429/5xx/超时、进程在各步骤崩溃均可恢复且不重复副作用。
- [ ] canary state/code/token/secret 在数据库、日志、异常、审计、APM、前端存储和测试快照中 0 命中。
- [ ] Production settings 即使错误配置网络开关也强制拒绝。

## 5. 正向与并发

- [ ] Shopee/TikTok synthetic 成功闭环分别通过。
- [ ] 同 Idempotency-Key 同请求返回原结果，不同请求 409。
- [ ] 同一 state 双 callback 只有一个成功交换。
- [ ] 同一 store 并发授权、刷新和撤销满足行锁、版本与最终状态合同。
- [ ] 旧引用撤销失败不使新授权错误生效；外部已撤销而本地失败进入 reconcile_required。

## 6. 前端与可访问性

- [ ] 授权确认、状态轮询、成功、失败、过期、重放、403、offline 页面状态完整。
- [ ] 前端不构造 URL/state/callback，不保存敏感 URL 或 query。
- [ ] action 按 exact permission 显示；后端负向测试证明隐藏不是授权边界。
- [ ] 键盘操作、焦点恢复、屏幕阅读器状态提示和移动端布局通过。

## 7. 自动化与环境

- [ ] Django check、迁移一致性、定向/全量 pytest 通过。
- [ ] MySQL 全新迁移、升级、失败重跑、并发和 metadata lock 通过。
- [ ] 前端 test/build 通过。
- [ ] `sandbox.ps1 verify integration` 通过。
- [ ] CI guard、依赖审计、凭据扫描、callback 路径扫描和 Git 制品检查通过。
- [ ] 固定远端 HEAD 全部 CI 成功，P0/P1 为零。

## 8. 环境结论

- [ ] synthetic 通过后仅标记 `mock`。
- [ ] Sandbox 只有在 A2-00 全部批准后执行并记录脱敏证据。
- [ ] PR-A2 不连接 Production，不标记 `connected`，不导入订单/库存/退款或启用 webhook。

