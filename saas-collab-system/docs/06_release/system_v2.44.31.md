# SaaS 协同系统 V2.44.31 发布登记

- 登记日期：2026-08-15
- 父版本：V2.44.30
- 当前部署基线：V2.44.30
- 发布状态：`deployed`
- 数据库迁移：需要（仅执行本登记白名单中的 0004/0005/0006/0028/0029）
- 部署：已完成（2026-08-15 20:54，目标 `192.168.174.131:8443`）
- 回退版本：V2.44.30

## 本次授权范围

本版本只扩展“产品开发 → 开发产品档案”流程：

1. 平台、国家站点、店铺使用当前租户启用的主数据选择；后端校验租户、启用状态、平台/店铺归属和站点国家一致性，并同步兼容字符串快照。
2. 测品生成要求人工开发 SPU 编码（NFKC、统一大写、至少一个英文字母、仅 A-Z/0-9、租户内唯一）。开发 SKU 固定为三段：`开发SPU-颜色-规格`；无规格时第三段为 `STD`，源值含分隔符时仍保持恰好两个连字符。
3. 生成可重试且幂等地创建草稿/未刊登试用 ProductSPU/ProductSKU；确认后转正式按正式编码规则新建另一套 ProductSPU/ProductSKU，同时保留试用与正式映射。
4. 仅使用 `development.product_archive.view`、`development.product_archive.manage`、`development.product_archive.confirm` 权限边界。

不修改 `frontend/src/router/menu.js`、`frontend/src/router/index.js`、`frontend/src/layouts/MainLayout.vue`，不包含商品明细、平台商品明细、角色权限页面或部署配置等无关脏改。

## 菜单、路由与导航复核

| 文件 | V2.44.30 SHA256 | V2.44.31 源 SHA256 | 结论 |
| --- | --- | --- | --- |
| `frontend/src/router/menu.js` | `0dd6ecd67bd874bc97322f5e7d3d4cdbbbb3f71e4897724d69ad07d09f0b611a` | `0dd6ecd67bd874bc97322f5e7d3d4cdbbbb3f71e4897724d69ad07d09f0b611a` | 未变更 |
| `frontend/src/router/index.js` | `96edff0b40945180d2e4f3fda19ca47a7aa12de61512c497fb45ea24cbf9a98d` | `96edff0b40945180d2e4f3fda19ca47a7aa12de61512c497fb45ea24cbf9a98d` | 未变更 |
| `frontend/src/layouts/MainLayout.vue` | `63c2092d2fa1265608cc29ba4ae0fa28245bedc822c081bcc982cad56b135619` | `63c2092d2fa1265608cc29ba4ae0fa28245bedc822c081bcc982cad56b135619` | 未变更 |

菜单仍为 15 个一级节点、105 个菜单节点，路由权限声明为 103 项。

## 数据库迁移白名单

以下迁移必须逐项核对 SHA256 后再执行：

| App / migration | SHA256 | 依赖 |
| --- | --- | --- |
| `development.0004_development_product_archives` | `f8001f9982b2dd7a495d5b540f4203f3a2e79fcd356c2f250acb348aecf0ff42` | `development.0002_product_sales_summary_view` 已由 V2.44.30 登记 |
| `development.0005_product_archive_trial_products_and_master_data` | `1e0b012a72714157a0a8165ea23b9ffa040b99345d67504158e8e8f50e13e97f` | 0004、`masterdata.0001_initial`、`products.0013_productsku_product_name` |
| `development.0006_development_product_archive_codes` | `ca687b63ceec9736b0f4bd85fdcf8b2334a7eeb3aabc3af69d588d629f221d4b` | 0005、`products.0013_productsku_product_name` |
| `permissions.0028_seed_development_product_archive_permissions` | `fbaf2e0d688f8bca4e3d081d109e983907173c171ebfacf79ad76aa586cc7d99` | `permissions.0027_sync_tenant_administrator_permissions` |
| `permissions.0029_sync_development_product_archive_permission_metadata` | `ffba55cbb48fcfc5a70b608456d8b938e4c5c1026c8cf94c355c273e798b69bd` | `permissions.0028_seed_development_product_archive_permissions` |

父版本依赖 `development.0002_product_sales_summary_view` SHA256 为 `37c8e29513549816293652f2f659f8cda3eb3ea49156e6cfeea793a402bc4182`，不属于本版本白名单，不能重复改写或替换。

## 镜像源文件白名单与 SHA256

部署构建只允许 manifest 中 `image_source_whitelist` 的 backend/frontend 路径进入本版本镜像；测试文件仅用于验收，不进入运行镜像。

### Backend

| 文件 | SHA256 |
| --- | --- |
| `backend/apps/development/models.py` | `8217c6ba69d81d371c191d53fd240e4e43e0415cd629566659ae726029ecea0f` |
| `backend/apps/development/permissions.py` | `0b78dc9e68202f0a53071dd1e04fb8dc21eabdb0c25ffad99d843e0635866237` |
| `backend/apps/development/serializers.py` | `ce40d95bf08eaa5a9e2e64b0464fc4a69dff5756e1b3b1359ed2a1792ba40fb4` |
| `backend/apps/development/services.py` | `c6df996c32d671a516a2f7f06bcb6b609e954cd3c05be480a1d9f545099cea5a` |
| `backend/apps/development/views.py` | `4b3fc12b1000c37f3c2c34fb54fa67eff9ca38f8073b59e3b6bd211156f2d9b8` |
| `backend/apps/development/urls.py` | `226d01ec29f8bc49d1150d6ff4da384ef33e41b35f8459ba84af9e65cad46a92` |
| `backend/apps/development/migrations/0004_development_product_archives.py` | `f8001f9982b2dd7a495d5b540f4203f3a2e79fcd356c2f250acb348aecf0ff42` |
| `backend/apps/development/migrations/0005_product_archive_trial_products_and_master_data.py` | `1e0b012a72714157a0a8165ea23b9ffa040b99345d67504158e8e8f50e13e97f` |
| `backend/apps/development/migrations/0006_development_product_archive_codes.py` | `ca687b63ceec9736b0f4bd85fdcf8b2334a7eeb3aabc3af69d588d629f221d4b` |
| `backend/apps/permissions/catalog.py` | `c555b4ce0390f3ce7629ae58535bdceb9d8751e4965adc135a11bb54fb4e3b1d` |
| `backend/apps/permissions/migrations/0028_seed_development_product_archive_permissions.py` | `fbaf2e0d688f8bca4e3d081d109e983907173c171ebfacf79ad76aa586cc7d99` |
| `backend/apps/permissions/migrations/0029_sync_development_product_archive_permission_metadata.py` | `ffba55cbb48fcfc5a70b608456d8b938e4c5c1026c8cf94c355c273e798b69bd` |

### Frontend

| 文件 | SHA256 |
| --- | --- |
| `frontend/src/api/development.js` | `4758740568b7fc8b0440bd701af02f8eb1f82394d4372e371107f4d66d535f68` |
| `frontend/src/api/masterData.js` | `037ef96a701a568f06cf9c116bca3c0fa13b8d96d140341219876755ebe54fe8` |
| `frontend/src/views/development/DevelopmentProductArchiveList.vue` | `790bfc254e640c0135b1b28f2c913a0d45c3492990aa9edf425cbeb86eea3da6` |

## 构建产物

构建参数固定为 `VITE_USE_MOCK=false`、`VITE_API_BASE_URL=''`：

- `frontend/dist/index.html`：`611fa92cd6feef63831ef566bc6f8778e5e19df6997309248aec271322bd7296`
- 入口 `index-DiYp8saB.js`：`b59be530e8275c2ff39d0579abeeb05b78f61c72d430c1c36559679b04f8f171`
- 开发产品档案 JS `DevelopmentProductArchiveList-C2NbQw51.js`：`85c2f131a1a6e92ce12b235f7c436e7058c84898988de5b66a590cc56a2f7ebf`
- 开发产品档案 CSS `DevelopmentProductArchiveList-CsPJZ8yd.css`：`ada3fcb0cb54429fbf1ebe0d181925ffd591f1b8cbe1a2c60507953c13d1d64b`

## 验证结果

- 后端定向测试：16 项通过（开发产品档案三组测试及 `test_permission_catalog.py`，含 0029 权限元数据一致性审计）。
- 前端定向 Vitest：6 项通过（开发产品档案主流程及类目契约）。
- `python manage.py check`：通过。
- `python manage.py makemigrations --check --dry-run`：`No changes detected`。
- 显式非 Mock Vite 构建：通过；构建日志仅有第三方 Rollup `/* #__PURE__ */` 注释提示，不影响产物。
- `DevelopmentProductArchiveList.vue` UTF-8 检查：通过，无 U+FFFD 或混合编码标记。
- 菜单、路由、MainLayout 哈希与 V2.44.30 一致。
- 部署前门禁与部署后运行时检查均已通过。

## 部署结果

- 数据库备份：`pre-migration-v2.44.31.sql.gz`，SHA256 `368062895d5513be285e6742c777dddaae49d8bf18a49ba7e529920207438dcd`；gzip 完整性和 dump 完成标记均通过。
- 已执行 `development.0005`、`development.0006`、`permissions.0029`；既有 `development.0004`、`permissions.0028` 保持已应用。
- 后端镜像：`saas-collab-backend:v2.44.31`，ID `sha256:852d329f4729779042c081cf60d5360ce61d3e1d82d0d1d79f12970047a5087a`。
- 前端镜像：`saas-collab-frontend:v2.44.31`，ID `sha256:dcada5a0ae805bb43bdbf06aa85448193399264092bb594dd4f699c8c4e9ae64`。
- 只通过 `up -d --no-deps backend frontend` 切换后端和前端；Celery、Beat、Redis 容器 ID 未变化。
- 运行时 `manage.py check`、`nginx -t` 通过；根页面、开发产品档案、角色权限页面及健康接口均返回 200。
- 运行时前端入口、开发产品档案 JS/CSS 哈希与登记完全一致。
- 运行中后端的档案映射字段与三段编码契约已验证，示例 `DEV001-BLUE-STD` 通过。

## 菜单与权限复核结果

- 菜单仍为 15 个一级分组、105 个总节点、103 条路由能力声明；`menu.js`、`router/index.js`、`MainLayout.vue` 哈希与 V2.44.30 完全一致。
- V2.44.30 与 V2.44.31 编译产物提取出的 327 条路由路径序列完全一致。
- “开发产品档案”仍仅位于“产品开发”下，路径 `/development/projects/archives`，未改变其他菜单节点。
- 三条 `development.product_archive.*` 权限的名称、模块、动作和描述已由 0029 与权限目录同步，运行时查询一致。
- 角色权限页继续全量分页加载权限，并按最新菜单与路由能力生成权限树；拥有 `development.product_archive.view` 的角色可选择“开发产品档案”，管理/确认权限作为同模块操作权限保留。

## 发布前门禁

1. 使用 `deploy/pilot/releases/system-v2.44.31/manifest.json` 的白名单和 SHA256，拒绝任何未列出的业务源码、产品明细、平台商品明细、导航或部署文件进入镜像。
2. 线上确认当前版本为 V2.44.30，先核对五项迁移状态，再按顺序执行 0004、0005、0006、permissions 0028 和 0029。
3. 发布只允许切换 backend/frontend；celery、beat、redis 不得重启。
4. 发布后复核开发档案权限、租户隔离、三段开发 SKU（含 `STD`）、正式独立 SPU/SKU 映射以及入口/档案资源哈希。
