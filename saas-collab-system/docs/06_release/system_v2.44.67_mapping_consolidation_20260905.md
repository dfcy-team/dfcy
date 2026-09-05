# V2.44.67 店铺与商品映射页面归集

## 版本登记

- 登记日期：2026-09-05。
- 本地候选版本：V2.44.67。
- 父候选：V2.44.66，提交 `7150631`，包含已合版的店铺与仓库 API 接入闭环。
- 实施分支：`codex/v24467-mapping-consolidation`。
- 业务实现提交：`aa7bae0ae4e84303c63f80bdd0714fea6f1224e7`；本文件后续登记提交仅补充审查记录。
- 用户授权：按最终建议页面结构落地店铺映射、商品映射归集，并延续角色权限登记要求。
- 当前状态：实现完成，候选验收通过；本登记不代表虚拟机已经部署。

## 页面和路由清单

| 页面 | 新入口与操作 | 兼容路径 |
| --- | --- | --- |
| 店铺档案 | 基本资料、平台身份与授权、API 连接状态、映射及验证历史、同步能力与异常；按店铺上下文选择授权、创建/维护/停用平台关联 | `/integrations/store-mappings` 保留隐藏兼容页面，共用关联面板 |
| 平台商品明细数据 | 全部明细、待映射、待确认、冲突、已映射、已停用；按商品上下文选择内部 SKU、登记建议、人工确认、停用与刷新；独立“未归集历史”入口 | `/integrations/product-mappings` 保留隐藏兼容页面，共用 SKU 映射面板 |

菜单只在“基础档案”保留一个店铺档案入口。“API数据接入”中的两个独立映射菜单与重复店铺档案菜单撤下。既有平台档案、平台站点、生产环境配置、同步任务及授权流程保持原入口能力；全局刊登的类目/属性映射不属于本次 SKU 归集范围。

旧 URL 首版保留兼容页面，不强制重定向到权限不同的宿主页。宿主页允许具备主档查看或对应映射查看权限的角色进入，并分别加载该角色有权访问的区域；无主档查看权限时不调用主档接口。API 模块关闭时映射功能不可操作。

## 数据一致性

`StoreMaster` 保存业务主档；店铺映射保存经过授权验证的外部身份及来源、验证信息。`PlatformProductDetail` 保存平台商品事实；商品映射保存 SKU 匹配决策及人工确认历史。

商品映射通过可空关系关联平台明细。映射确认由事务同时更新决策记录和平台明细中的内部 SKU。建议只进入待确认状态，冲突与停用保留历史。身份或 SKU 对齐存在歧义时不自动覆盖；已纳入受控映射的记录经直接编辑、批量修改和导入更新 SKU 时也执行一致性守卫。

冲突替换必须由具备人工确认权限的操作员明确确认旧 SKU，提交预期旧值后在事务内校验；其他操作已更改旧值时拒绝陈旧请求。停用不会删除已确认事实或历史审计，也不宣称会关闭店铺的全部下游同步。

历史回填只关联身份唯一、SKU 一致的记录；多个旧映射争用同一明细、商品身份不匹配、SKU 冲突或已确认映射缺少明细 SKU 时，保留未归集状态，不自动选择胜者。

未实现受控映射的平台保留已有平台商品明细维护能力，页面明确提示适配情况，不把授权连接器已实现等同于商品映射已实现。

## 角色权限登记

| 权限 | 操作边界 |
| --- | --- |
| `masterdata.view/manage` | 店铺业务档案查看/维护 |
| `integrations.store_mapping.view` | 查看店铺平台关联及验证历史 |
| `integrations.store_mapping.manage` | 创建、维护、启用或停用店铺平台关联 |
| `integrations.product_mapping.view` | 查看商品映射、建议、冲突及候选摘要 |
| `integrations.product_mapping.manage` | 创建商品映射、维护建议、停用映射 |
| `integrations.product_mapping.confirm` | 人工确认 SKU 映射 |
| `listings.product_detail.view/manage/import` | 分别控制平台商品明细查看、维护与导入 |
| `integrations.store.view/authorize/revoke` | 继续控制店铺 OAuth 授权生命周期，不作为新映射接口的隐含授权 |

权限迁移等价继承历史有效角色的映射访问：旧 `integrations.store.view` 对应两个映射查看权限；旧 `integrations.store.authorize` 对应映射维护和确认权限。保留旧授权码及数据范围，不将 CUSTOM 范围升级为 ALL。管理员登记完整映射操作；新建角色独立分配建议维护与确认权限。

平台明细接口对齐平台/店铺数据范围，映射候选接口只提供选择所需身份与 SKU 摘要，不要求额外授予全部主档访问。页面权限、按钮权限、后端权限和 Mock 权限目录同步登记。

## 迁移与验证

- `integrations.0022_product_mapping_platform_detail`：新增商品映射到平台明细的关系。
- `permissions.0041_register_mapping_permissions`：登记独立映射权限并等价迁移历史角色。
- 主代理后端全仓复验：998 passed、28 skipped（SQLite 内存测试数据库，232.49 秒）。跳过项按既有测试条件执行，不等同于真实生产平台联调已通过。
- Django `manage.py check`：0 issues；`makemigrations --check --dry-run`：No changes detected。
- 权限专项 5 项、历史只读报告 4 项通过；变更期间的首次全量失败已定位并修正，最终全量无失败。
- 全量后补入的映射范围明细过滤已定向复验：映射归集、平台商品明细与平台商品 ID 导入合计 30 项通过；跨权限范围“待映射”筛选 API 用例也单独通过。主代理复核确认未修改生产控制树。

### 历史数据核对

在隔离验收库应用两项候选迁移后，可运行只读命令 `python manage.py report_mapping_consolidation --tenant-id <租户ID> --batch-size 500`。输出为 JSON，列出缺失明细、多候选、身份冲突、SKU 冲突、重复映射、已确认记录缺失 SKU，以及可归集记录的业务标识。

命令不修改数据库、不输出凭据。`ready` 只代表精确身份和 SKU 一致，不能将冲突项自动覆盖；生产数据核对及生产迁移必须交由架构员受控执行。

### 已完成前端与页面验证

- 主代理全量前端回归：65 个文件、399 项测试通过，明确使用 `VITE_USE_MOCK=true` 演练模式。
- 主代理生产前端构建：`VITE_USE_MOCK=false npm run build` 通过。仅有依赖 `@vueuse/core` 的既有 PURE 注释警告。
- 生产发布基线静态检查：`PRODUCTION_BASELINE_CI=PASS`；此检查没有调用生产发布。
- 隔离预览：`http://127.0.0.1:4187`，本地共享 Mock 数据，未连接第三方平台或生产数据库。
- 浏览器检查：Edge / Playwright，桌面 1600×1050、小屏 390×844。
- 主要流程：新建映射、建议、人工确认、明细 SKU 写回、冲突明确替换、停用留痕；店铺五页签与真实授权快照语义；两个旧 URL；未归集历史可发现；confirm-only 与 mapping-only 角色。
- 确认后不存在框架错误遮罩或应用运行时异常；控制台唯一资源错误为本地已有 `favicon.ico` 404，不影响操作。
- 截图目录：`C:/Users/Administrator/AppData/Local/Temp/saas-v24467-mapping-qa`。主要证据：`product-workspace.png`、`store-api-status.png`、`product-mobile.png`、`unlinked-history.png`、`confirm-only-role.png`、`store-mapping-only-role.png`。

本轮按前端测试技能执行了真实渲染、按钮操作、角色验证及截图检查，并据此修正小屏操作按钮溢出；后端真实权限和事务行为由 Django API / 服务回归另行验证，Mock 演练不替代生产联调。

## 完整文件清单

以下 45 个文件均属于本次获准的映射归集、宿主能力、权限、测试或版本材料。生产控制树、Compose、环境配置与镜像定义无改动。

- `backend/apps/integrations/management/commands/report_mapping_consolidation.py`
- `backend/apps/integrations/migrations/0022_product_mapping_platform_detail.py`
- `backend/apps/integrations/models.py`
- `backend/apps/integrations/product_mapping_service.py`
- `backend/apps/integrations/serializers.py`
- `backend/apps/integrations/urls_internal.py`
- `backend/apps/integrations/views.py`
- `backend/apps/listings/platform_product_details.py`
- `backend/apps/listings/serializers.py`
- `backend/apps/listings/urls.py`
- `backend/apps/listings/views.py`
- `backend/apps/permissions/api_permissions.py`
- `backend/apps/permissions/catalog.py`
- `backend/apps/permissions/migrations/0041_register_mapping_permissions.py`
- `backend/apps/permissions/services.py`
- `backend/apps/permissions/ui_p6_scopes.py`
- `backend/tests/test_mapping_consolidation.py`
- `backend/tests/test_mapping_consolidation_report.py`
- `backend/tests/test_mapping_permissions.py`
- `docs/06_release/system_v2.44.67_mapping_consolidation_20260905.md`
- `frontend/src/api/integrations.js`
- `frontend/src/api/masterData.js`
- `frontend/src/api/platformProductDetails.js`
- `frontend/src/components/ProductMappingPanel.vue`
- `frontend/src/components/StoreMappingPanel.vue`
- `frontend/src/mock/auth.js`
- `frontend/src/mock/integrations.js`
- `frontend/src/mock/mappings.js`
- `frontend/src/mock/systemAdmin.js`
- `frontend/src/router/menu.js`
- `frontend/src/utils/permissionLabels.js`
- `frontend/src/views/integrations/ProductMappingList.vue`
- `frontend/src/views/integrations/StoreMappingList.vue`
- `frontend/src/views/integrations/SyncIncidentList.vue`
- `frontend/src/views/masterdata/PlatformProductDetailList.vue`
- `frontend/src/views/masterdata/StoreMasterList.vue`
- `frontend/tests/foundation-settings.spec.js`
- `frontend/tests/integration-api-access-closure.spec.js`
- `frontend/tests/mapping-mock-workflow.spec.js`
- `frontend/tests/platform-product-detail-runtime.spec.js`
- `frontend/tests/platform-product-detail.spec.js`
- `frontend/tests/product-mapping-consolidation.spec.js`
- `frontend/tests/request-layer-mutation-fail-closed.spec.js`
- `frontend/tests/store-mapping-consolidation.spec.js`
- `frontend/tests/v24433-menu-baseline.spec.js`

## 发布边界

本次在隔离分支实现，基于 V2.44.66 候选继承店铺与仓库 API 增量。生产 Compose、环境配置和数据库尚未切换。候选需按现有受控发布流程核对提交、权限迁移、镜像与虚拟机实际版本。

保存业务提交时，Git 自动 geometric repack 报告历史 tree 对象 `afb0a68e7ddd57c35db5f9e6454a3941a05ae5e9` 异常。提交本身成功；只读 `rev-list --objects --missing=print HEAD` 检查返回 0，当前提交可达历史缺失对象数为 0，工作区与提交一致。没有删除、清理或重写仓库历史。该仓库维护告警保留待独立核查，不能据此宣称整个共享仓库的维护问题已修复。

应用回退应回到父候选或已部署受控版本。新增权限与可空关系均保留业务历史，不通过删表或覆盖冲突记录实现回退。
