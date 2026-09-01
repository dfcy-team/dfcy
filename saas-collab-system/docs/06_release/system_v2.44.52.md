# System V2.44.52 - Shopee 正式授权链路整改

## 基线与范围

- 父基线：`v2.44.51-deployed` / `db8a4dabfaac40f0baef444ff0de26abe7d98091`
- 仅整改 API 数据接入、连接配置、店铺档案 Shopee OAuth 授权链路。
- 不新增数据库迁移，不改菜单、路由、权限目录、销售数据或其他平台的既有 live readiness 规则。
- 不把 Partner Key、Token 或其他密钥写入业务数据库、响应、日志和交接文件。

## 改动

1. Shopee 维护凭据界面增加非敏感的授权回调地址，后端强制校验 HTTPS、平台登记值和生产白名单。
2. Shopee 正式配置在网络、安全、独立凭据保管、出口域名、合同、状态、凭据引用、回调和关闭写同步全部通过后，允许发起 OAuth。
3. 修正“凭据保存后只读同步开启，但 OAuth readiness 要求只读同步关闭”的冲突；只读同步不再阻断 OAuth，写同步仍 fail closed。
4. 店铺 API 接入弹窗显示非敏感阻断原因；未就绪时禁用授权并且不发送空 `redirect_uri`。
5. 新增 `repair_shopee_callback` 受控命令，仅补齐一个精确配置的 callback；默认 dry-run，`--apply` 才写入并产生审计。
6. 修复基线 CI guard 对只读 volume `service.token:ro` 的误报，并统一测试凭据为明确 placeholder；不修改运行凭据。

## 正式环境执行顺序

1. 确认运行配置包含以下审批值，且值与 Shopee 开放平台登记完全一致：
   - `PLATFORM_NETWORK_MODE=approved-live-test`
   - `LIVE_PLATFORM_SECURITY_APPROVED=true`
   - `LIVE_CUSTODY_BACKEND=http`
   - `LIVE_PLATFORM_ALLOWED_HOSTS=partner.shopeemobile.com`
   - `LIVE_SHOPEE_CONTRACT_APPROVED=true`
   - `LIVE_SHOPEE_REDIRECT_URI=<正式 HTTPS Shopee callback>`
   - `LIVE_OAUTH_REDIRECT_ALLOWLIST=<同一正式 callback>`
2. 先执行只读预检（替换精确选择器，不得使用模糊条件）：

   ```bash
   python manage.py repair_shopee_callback \
     --tenant-code '<tenant-code>' \
     --config-id '<config-id>' \
     --actor-username '<architect-user>' \
     --callback-url '<approved-shopee-callback>' \
     --expected-current ''
   ```

3. 架构员核对 dry-run 只命中一个生产 Shopee 配置后，原命令增加 `--apply`。
4. 若凭据状态仍为“未配置”，由有权限的人员在页面维护 Partner ID、Partner Key 和同一回调地址；密钥仅提交至独立 custody。
5. 执行“检查凭据”，确认配置状态为已检查；再从店铺档案发起授权。
6. 授权页应打开 Shopee 官方域名；回调后核对授权关系、审计日志和只读检查，不执行生产写同步。

## 验证

- 后端全量：`564 passed, 3 skipped`（其中一次仅因本机缺少 requirements 中的 mysqlclient 失败，安装依赖后该测试单独通过）。
- Shopee 专项：`10 passed`（readiness、正式授权 URL、凭据维护、回调拒绝、dry-run/apply）。
- 前端全量：`258 passed`。
- 前端 production build：通过，2068 modules transformed。
- Django system check：通过。
- `makemigrations --check --dry-run`：No changes detected。
- `git diff --check`：通过。

## 回滚

- 应用回滚：恢复 V2.44.51 前后端镜像；本次没有 schema 迁移，无需数据库 DDL 回滚。
- callback 为非敏感、向后兼容配置；应用回滚时可保留已批准 callback，不影响 V2.44.51 读取。
- 若授权尚未成功，无授权业务数据需要清理；若授权已建立，必须通过现有“禁用授权/撤销”受控入口处理，不直接删除数据库记录。
