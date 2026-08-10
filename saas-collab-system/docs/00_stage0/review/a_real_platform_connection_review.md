# A-REAL-PLATFORM-CONNECTION 独立复审入口

任务编号：`A-REAL-PLATFORM-CONNECTION-REVIEW`。

当前开发预审结论：**FAIL / REQUEST CHANGES**。无需真实平台的 P1 已完成整改；真实平台、固定镜像和独立签字 P1 仍未关闭。完整证据矩阵见 `docs/05_test/real_platform_connection_review.md`，平台测试明细见 `docs/05_test/shopee_tiktok_live_connection_test_report.md`。

## 复审冻结字段

```text
Repository: dfcy-team/dfcy
Branch: feature/module-a-real-platform-connection
PR Number: 42
PR URL: https://github.com/dfcy-team/dfcy/pull/42
Base Branch: feature/module-a-marketplace-oauth
Base SHA: 5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0
Head SHA: freeze from PR #42 after this evidence-only commit
Review SHA: c3307626affdae78c14db66dc19ad7c65744ae39 (code review source; final evidence head pending)
Commit Count: freeze from final PR #42 head
Changed Files: freeze from final PR #42 head
Deployment Environment: Local Sandbox only; real-platform switches OFF
Source Artifact SHA-256: 962cfe48451856d09b3a633fb195057037137d7eafb60e67a23b44a7b088f2f0
Deployment Artifact SHA: NOT AVAILABLE
Container Image Digest: NOT AVAILABLE
Database Version: MySQL 8.4.10 Local Sandbox PASS
Migration Head: integrations.0013_authorization_reauthorization_bindings
Review Date: 2026-08-10
Developer: 开发A
Architecture Reviewer:
Security Reviewer:
Test Reviewer:
Release Reviewer:
```

## 强制结论

- Shopee：`pending/mock`。
- TikTok Shop：`pending/mock`。
- Production synchronization：OFF。
- PR-A3：不满足进入门禁。

## 本轮离线 P1 整改

- Shopee initiate 更新为当前官方 `open.shopee.com/auth` seller 合同，state 为顶层参数。
- 增加业务数据库外的本地文件 custody，目录/文件权限、原子替换、跨进程锁、单调版本与幂等 revoke 已测试。
- callback 在 live 模式完成后 303 到精确 allowlist 的无 query 结果页；Nginx 关闭 callback access log，Gunicorn 仅记录 path。
- focused 34 PASS；backend 539 PASS / 3 skipped；frontend 163 PASS；production build PASS；fresh/upgrade SQLite PASS；CI guard PASS。
- 未执行真实 OAuth 或平台 API。Docker daemon 超时，因此当前 SHA 的 MySQL 8.4、镜像 digest 和容器日志扫描未重建。

复审人必须从固定远程 SHA 构建固定制品，完成 MySQL 8.4、Sandbox、CI、批准 custody、两平台真实 OAuth/authorized shop/minimal read/refresh/revoke/reauthorization、并发、隔离和 DB/log/browser/Git 扫描后重新填写。不得以本地未提交代码或临时 SQLite 作为证据。
