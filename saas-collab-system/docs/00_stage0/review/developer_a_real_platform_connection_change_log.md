# 开发A 正式平台受控接入变更日志

## 1. 任务与当前结论

- 任务编号：`A-REAL-PLATFORM-CONNECTION`
- 目标分支：`feature/module-a-real-platform-connection`
- stacked base：`feature/module-a-marketplace-oauth`
- 固定基线：`5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0`
- 当前状态：实现、回归、提交、推送和 Draft stacked PR #42 创建完成；未执行真实平台请求。
- Capability：Shopee 与 TikTok Shop 均保持 `pending/mock`；`production-enabled` 未设置。

阻断原因：GitHub CLI 认证失效；Shopee 当前官方合同尚未从获批应用控制台冻结；TikTok revoke 合同未冻结；固定部署制品、批准的 Credential Custody、MySQL 8.4、Local Sandbox 和真实试点环境均未提供。完整 43 节复审任务书已于本轮补齐。

## 2. 编码前现场记录

执行目录：仓库根目录 `C:\Users\Administrator\Desktop\开发\dfcy`。

```text
git status --short
 M saas-collab-system/backend/apps/integrations/marketplace_oauth_service.py
 M saas-collab-system/backend/apps/integrations/oauth_errors.py
 M saas-collab-system/backend/config/settings/base.py
?? saas-collab-system/PR-A2-REVIEW.md
?? saas-collab-system/backend/.venv311/
?? saas-collab-system/backend/apps/integrations/capability.py
?? saas-collab-system/backend/apps/integrations/custody.py
?? saas-collab-system/backend/apps/integrations/live_providers.py
?? saas-collab-system/backend/apps/integrations/net_guard.py
?? saas-collab-system/backend/apps/integrations/provider_helpers.py
?? saas-collab-system/backend/db.sqlite3.pre-a2-sandbox-v1.bak
?? saas-collab-system/backend/db.sqlite3.pre-real-marketplace-access.bak
?? saas-collab-system/backend/db.sqlite3.stale-backup
?? saas-collab-system/backend/tests/test_pr_a_real_platform_connection.py
?? saas-collab-system/docs/00_operations/
?? saas-collab-system/docs/03_api/shopee_live_platform_alignment.md
?? saas-collab-system/docs/03_api/tiktok_live_platform_alignment.md
?? saas-collab-system/docs/05_test/capability_status.md
?? saas-collab-system/docs/05_test/real_platform_connection_review.md
?? saas-collab-system/docs/05_test/shopee_tiktok_live_connection_test_report.md

git log -1 --oneline
5c3d285 A2-10 docs: add PR-A2 test report, release notes and rollback guide

git rev-parse HEAD
5c3d285e2bf89baa13f669c71e6ef6cbfb9263e0

git diff --stat
 .../apps/integrations/marketplace_oauth_service.py | 20 ++++++--
 .../backend/apps/integrations/oauth_errors.py      |  6 +++
 saas-collab-system/backend/config/settings/base.py | 60 ++++++++++++++++++++++
 3 files changed, 82 insertions(+), 4 deletions(-)
```

现场记录后，从固定 SHA 创建并切换到 `feature/module-a-real-platform-connection`。切换发生在相同 commit，已有未提交文件全部保留。

## 3. 未提交文件归属

### 3.1 候选正式接入实现（待修正后才可提交）

- `backend/apps/integrations/marketplace_oauth_service.py`
- `backend/apps/integrations/oauth_errors.py`
- `backend/config/settings/base.py`
- `backend/apps/integrations/capability.py`
- `backend/apps/integrations/custody.py`
- `backend/apps/integrations/live_providers.py`
- `backend/apps/integrations/net_guard.py`
- `backend/apps/integrations/provider_helpers.py`
- `backend/tests/test_pr_a_real_platform_connection.py`
- `docs/00_operations/live_platform_enablement.md`
- `docs/03_api/shopee_live_platform_alignment.md`
- `docs/03_api/tiktok_live_platform_alignment.md`
- `docs/05_test/capability_status.md`
- `docs/05_test/real_platform_connection_review.md`
- `docs/05_test/shopee_tiktok_live_connection_test_report.md`

### 3.2 复审输入候选（未纳入本任务提交范围）

- `PR-A2-REVIEW.md`

### 3.3 明确禁止提交的本机产物

- `backend/.venv311/`
- `backend/db.sqlite3.pre-a2-sandbox-v1.bak`
- `backend/db.sqlite3.pre-real-marketplace-access.bak`
- `backend/db.sqlite3.stale-backup`

未删除、移动或修改上述本机文件。

## 4. 已实施变更

1. synthetic/live provider 明确分离；live 模式缺任一审批、custody、allowlist、redirect 或合同即在网络前失败。
2. 移除本地 vault 与 capability 环境提升；正式凭据只允许进入 HTTP custody，业务层只接收 opaque reference/mask/version。
3. 网络层强制 HTTPS、系统 CA、host allowlist，分别限制 connect/read timeout，并限制 retry、单次等待和总等待。
4. TikTok 按当前官方合同实现 initiate、callback code exchange、authorized shops、shop cipher、最小 permissions metadata、refresh 与签名；revoke 合同未确认时拒绝调用。
5. Shopee provider 保持合同门禁；未获批准控制台合同前不允许以历史 endpoint/签名猜测执行。
6. callback 拒绝 token、tenant、user 与内部 store 替换字段；state 继续验证一次性消费、TTL、平台、用户与 session context。
7. 平台店铺用全局 active identity key 阻止跨 tenant 重绑；revoke 清除 active key，reauthorization 创建新记录与新引用并保留历史。
8. refresh 使用 DB 锁和单调版本；竞争失败时清理新引用，旧引用撤销失败时进入受控 error，不报告完整成功。
9. Nginx callback location 关闭 access log；Django 审计仅记录平台、内部 store、引用、掩码、版本、状态和受控错误码。
10. 新增 migration `integrations.0013_authorization_reauthorization_bindings` 及负向、并发、故障和网络边界测试。
11. Local Sandbox 首轮发现 Nginx 证据测试未挂载 deploy 配置；改为只读挂载两份 Nginx 配置，并增加 MySQL live custody reference 双 worker 并发测试。

## 5. 验证与发布状态

- `git diff --check`：PASS。
- Django check / migration drift：PASS。
- SQLite fresh migration 与 `0012 -> 0013` upgrade：PASS。
- focused live/provider：21 passed；MySQL live refresh 双 worker：1 passed。
- backend local full：527 passed / 3 MySQL-only skipped。
- frontend full：160 passed；production build：PASS（1955 modules）。
- MySQL 8.4.10 / Local Sandbox integration：PASS，backend 530 passed、frontend 160 passed、build 1955 modules；真实平台开关关闭。
- Sandbox DB scan：0 findings / 0 authorization rows；container log scan：0 findings。空表扫描不替代真实试点后的扫描。
- 固定代码 Review SHA：`45b130c586d9de2d15d420ec237773174aa19c3c`。
- 真实 OAuth、固定部署制品扫描与浏览器扫描：NOT RUN。
- 部署制品 SHA / image digest：未提供。
- 数据库版本 / migration head：待固定环境验证。
- GitHub Draft PR：#42，Base 为 `feature/module-a-marketplace-oauth`；PR #41 与 #42 均须保持 Draft。
- PR #41：未修改、未合并，应继续保持 Draft。

## 6. 恢复条件

1. 提供获批应用控制台导出的当前 Shopee 合同与 TikTok revoke 合同；只提供掩码标识。
2. 提供批准的 custody 接口合同和固定部署环境/制品生成方式。
3. 从固定 Review SHA 生成不可变制品，完成两平台真实试点与真实流量后的 DB/log/browser 扫描，再启动独立复审。

## 7. SaaS 部署配置补充（2026-08-07）

- 代码 Review SHA：`24ed0f9f9e30cb382dfa4b04db403edc501ae491`。
- Shopee 与 TikTok callback 改为独立配置，使用 `dingfengchuangyu.com` 下各自的精确公开路径。
- `deploy/pilot/application/env.pilot.example` 增加 Shopee `PH/TH/MY` 与 TikTok `ROW` 的 fail-closed 配置；模板不保存 App Secret、Token、authorization code、Cookie 或 Session。
- 新增 `docs/00_operations/local_vm_real_platform_deployment.md`，记录本地双 VM 放置方式与 custody 边界。
- 安装门禁同时拒绝 `change-me` 与 `REPLACE_ME` 占位符。
- 验证：Django check PASS；migration drift PASS；focused live tests 22 passed；后端全量 528 passed / 3 MySQL-only skipped；CI guard PASS；`git diff --check` PASS。
- 只读连通性确认操作员提供的私网应用主机 pilot HTTP/HTTPS 端口可达，数据库端口从操作员工作站不可达。尚未证明 TLS/应用健康、SSH 主机身份、不可变镜像 digest 和 custody；未部署、未执行真实 OAuth，两个 capability 继续为 `pending/mock`。

## 8. 连接配置页面接线（2026-08-08）

- 代码 Review SHA：`bcb3281774f5166cf14e0d7346f43095ffa46b21`。
- 将 Shopee/TikTok OAuth start、授权列表、refresh 和 revoke 前端入口放入 `API数据接入 -> 连接配置`（`/integrations/configs`）。
- 页面按当前 HTTPS origin 生成两个独立 callback URL，只提交内部 config/store、platform、region、redirect 和空 scope 请求，不提供原始 App Secret/Token 输入或展示。
- 操作按钮继续执行 `integrations.store.authorize`、`integrations.credential.rotate`、`integrations.store.revoke` 精确权限；Mock 不生成真实授权地址。
- 验证：新增前端契约测试 3 passed；前端全量 163 passed；production build PASS（1957 modules）；CI guard 和 `git diff --check` PASS。
- 未执行真实 OAuth，未改变 `pending/mock` capability，也未启用同步任务。
