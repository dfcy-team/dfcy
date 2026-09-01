# System V2.44.52 - Shopee OAuth 与仓储平台绑定组合增量

## 基线与范围

- 父基线：`v2.44.51-deployed` / `db8a4dabfaac40f0baef444ff0de26abe7d98091`。
- 统一应用版本：后端、Celery、前端均为 `V2.44.52`；credential custody 无代码变更，保持 `V2.44.50` healthy。
- 本版本包含两组受控增量：API 数据接入/连接配置/店铺档案的 Shopee 正式 OAuth 整改，以及平台档案/仓库档案的仓储服务平台绑定改造。
- 不带入未发布的其他开发节点、历史累计差异、菜单路由变更或生产写同步能力；不写入真实凭据，不创建部署 tag，未授权不得直接发布。

## Shopee 正式 OAuth 整改

1. Shopee 凭据维护界面增加非敏感授权回调地址，后端强制校验 HTTPS、平台登记值和生产白名单。
2. Shopee 正式配置在网络、安全、独立凭据保管、出口域名、合同、状态、凭据引用、回调及关闭写同步全部通过后，才允许发起 OAuth。
3. 修正“凭据保存后只读同步开启，但 OAuth readiness 要求只读同步关闭”的冲突；只读同步不再阻断 OAuth，写同步仍 fail closed。
4. 店铺 API 接入弹窗显示非敏感阻断原因；未就绪时禁用授权，不发送空 `redirect_uri`。
5. 新增 `repair_shopee_callback` 受控命令，仅补齐精确配置的 callback；默认 dry-run，只有 `--apply` 才写入并产生审计。
6. 修复 CI guard 对只读 volume `service.token:ro` 的误报，测试凭据统一为明确 placeholder；不修改运行凭据。

## 仓储平台类型与仓库 API 接入

1. `PlatformMaster.PlatformType` 新增三类平台类型：
   - `warehouse_owned`：自营仓服务；
   - `warehouse_third_party`：三方仓服务；
   - `warehouse_platform`：平台仓服务。
2. `WarehouseMaster` 新增 nullable `PROTECT` 外键 `service_platform`，序列化输出 `service_platform_id`、`service_platform_name`、`service_platform_type`、`service_platform_integration_key` 和 `api_access_available`，写入时只接受当前租户的启用仓储服务平台。
3. 仓库类型与服务平台类型强制映射：`owned -> warehouse_owned`、`third_party -> warehouse_third_party`、`platform -> warehouse_platform`；自营仓可不绑定，三方仓和平台仓必须绑定。PATCH 校验会合并并复核实例已有字段。
4. `WarehouseMasterList.vue` 加载启用的平台档案，按仓库类型动态筛选服务平台；切换仓库类型会清理不匹配选择。仅已绑定且能力可识别的平台显示 API 接入入口，未绑定或未知服务商显示阻断提示。
5. `StoreMasterSerializer` 和店铺档案前端均禁止将 `warehouse_*` 平台绑定到店铺；店铺导入接口同步执行同一校验。
6. `subject_access_service.py` 根据 `service_platform` 的 `platform_type/code/name` 解析 provider；未知能力、停用平台或未绑定仓库均 fail-closed，不再回退到硬编码极风 WMS。
7. `platform_schema_service.py` 为平台编码 `myjf` 增加精确 alias 到 `jifeng_wms`，并保留 `jifengwms`、`极风wms` alias，使马来极风复用现有库存 API 能力。
8. 平台停用门禁同时检查启用店铺和启用仓库的 `service_platform` 引用。

## 数据库迁移与数据动作

- 迁移文件：`backend/apps/masterdata/migrations/0009_warehouse_service_platform.py`。
- 迁移内容：扩展平台类型 choices、增加 nullable `PROTECT` 外键、精确修订平台编码 `code__iexact='myjf'` 且当前 `platform_type='other'` 的记录为 `warehouse_third_party`。
- 迁移不按名称模糊匹配，不修改其他平台，不自动绑定任何仓库，不写入凭据或授权数据。
- 正式执行前必须先备份数据库，并由架构员执行 `showmigrations`、`migrate --plan` 和迁移；迁移完成后复查 `myjf` 命中范围、仓库绑定关系及应用读写结果。

## 正式环境执行顺序

1. 确认运行配置包含以下审批值，且值与 Shopee 开放平台登记完全一致：
   - `PLATFORM_NETWORK_MODE=approved-live-test`
   - `LIVE_PLATFORM_SECURITY_APPROVED=true`
   - `LIVE_CUSTODY_BACKEND=http`
   - `LIVE_PLATFORM_ALLOWED_HOSTS=partner.shopeemobile.com`
   - `LIVE_SHOPEE_CONTRACT_APPROVED=true`
   - `LIVE_SHOPEE_REDIRECT_URI=<正式 HTTPS Shopee callback>`
   - `LIVE_OAUTH_REDIRECT_ALLOWLIST=<同一正式 callback>`
2. 备份数据库，执行 `showmigrations` 与 `migrate --plan`，确认仅包含 `masterdata.0009_warehouse_service_platform`，再由架构员执行迁移。
3. 先运行 Shopee callback 受控命令的只读 dry-run；确认精确命中一个目标租户、一个配置和一个 callback 后，才可由架构员批准 `--apply`。
4. 在平台档案维护仓储服务平台：`myjf` 应为三方仓服务；不得为任何仓库自动绑定，仓库绑定由业务人员在仓库档案逐条选择。
5. 对三方仓/平台仓绑定启用且类型匹配的服务平台；未知 provider 必须保持 API 接入阻断。自营仓可保持空绑定。
6. 执行应用、Celery 和前端镜像构建/发布，检查运行版本、服务健康、迁移状态、仓储平台列表、仓库 API 接入口和店铺平台过滤。
7. Shopee 执行“检查凭据”并从店铺档案发起授权；授权页必须为 Shopee 官方域名，回调后核对授权关系、审计日志和只读检查，不执行生产写同步。

## 验证

- 后端全量：`571 passed, 3 skipped`。
- 前端全量：`259 passed`。
- 前端 production build：通过。
- Django system check：通过。
- `makemigrations --check --dry-run`：`No changes detected`。
- `git diff --check`：通过。
- CI guard：通过；未发现真实凭据写入或跨模块越权路径。
- 重点复核：Shopee readiness/OAuth/callback、仓储平台类型与 `myjf` alias、仓库绑定 tenant/active/type 映射、店铺禁止仓储平台、平台停用引用门禁、未知 provider fail-closed。

## 回滚与风险控制

- 优先通过应用前向修复、禁用错误配置或恢复已验证镜像处理问题；不得在未确认依赖前盲目 reverse migration。
- 本迁移的外键为 nullable，且使用 `PROTECT`；如确需回滚，必须先确认没有仓库依赖、完成数据库备份并由架构员评估后执行恢复方案。
- 不建议直接 reverse `0009` 覆盖已产生的业务数据；对于 `myjf` 分类修订，先记录迁移前后精确命中清单，再按备份或经审核的前向数据修复恢复。
- 应用回滚可恢复 V2.44.51 前后端镜像；credential custody 无代码变更，可继续保持 `V2.44.50` healthy。
- 已建立的授权关系必须通过现有“禁用授权/撤销”受控入口处理，不直接删除数据库记录；不得执行生产写同步、未经审批的 Docker 操作或虚拟机发布。
