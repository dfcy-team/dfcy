# V2.44.68 档案外部身份与平台商品入档补全

## 版本与授权

- 日期：2026-09-05。
- 基线：V2.44.67 候选 `9542abc`，继承已合版的店铺、仓库 API 及映射归集功能。
- 当前批次授权：用户针对外部身份唯一性、平台商品同步入档、新旧 SKU 一致性检查的缺口明确要求“补全缺口”。
- 范围：店铺档案、仓库档案、平台商品明细及直接对应的 API 同步、权限验证、测试、迁移和版本材料；不新增或移动菜单。
- 状态：实现完成，本地候选验收通过；本文不是生产平台验收或虚拟机部署完成的证明。改动保存在候选工作树，尚未制作发布镜像。
- 生产限制：不操作虚拟机、生产数据库、生产凭据或第三方真实账户；发布仍由架构员按受控流程执行。

## 业务规则与验证简报

- 操作员：系统管理员、获授权的接入管理员及商品资料维护人员。
- 问题：重复外部身份造成档案歧义；新旧 SKU 同时填写却不一致时可能错配；平台商品未从店铺只读同步自动入档。
- 目标：平台店铺记录 → 按外部身份幂等入档 → 新旧 SKU 精确一致时自动关联 → 无匹配或冲突进入受控人工处理。
- `[U 通用]`：租户隔离、唯一身份、精确 SKU 解析、审计、重复同步不重复建档。
- `[P 部分通用]`：平台只读商品/变体接口、分页与更新时间、平台字段标准化。
- `[X 平台专属]`：各平台签名、商品和变体身份、认证范围及返回协议。
- 档案与各自外部记录一一对应，不将店铺、商品、仓库三类实体互相设置一对一；内部 SKU 可在多店铺复用。
- 商品系统记录来源：平台 ID、标题、变体、销售状态来自店铺；内部 SKU 及新旧编码对应关系来自内部商品明细。
- 权限边界：平台访问 L1 只读；不启用价格、库存、刊登写入。自动关联仅限唯一且一致的精确匹配，不扩大人工冲突替换权限。
- 冲突保护：不静默覆盖已确认关系，不删除或合并历史重复业务档案；迁移前只读报告，发现冲突给出阻断及处置指引。
- 成功标准：同一快照重复同步不新增重复档案；跨租户关联拒绝；双码不一致不误配；冲突仍可在现有商品页定位并处理。
- 数据新鲜度：平台更新时间与本地入档更新时间分开；分页失败、权限不足、连接器未支持均明确失败，不回退 Mock 冒充生产。
- 验证计划：本地接口/服务回归和页面交互验证；后续由架构员选定授权测试店铺进行两周只读试运行，比对至少两次全量商品导出与增量同步。错配或跨租户写入任一发生即停止该同步任务并保留证据。

## 角色权限登记

| 角色能力 | 权限边界 |
| --- | --- |
| 店铺/仓库档案维护 | 沿用 `masterdata.view/manage` 及已有数据范围；维护外部身份不等于获准维护凭据 |
| 店铺与仓库授权维护 | 分别使用 `integrations.store.view/authorize/revoke`、`integrations.warehouse.view/authorize/revoke`；不通过主档编辑绕过有效绑定唯一性 |
| 商品同步任务 | `integrations.view/manage` 查看和维护；`integrations.run` 控制既有运行操作、`integrations.run_live_readonly` 控制真实只读执行；平台/环境/区域/配置/店铺/`resource_types` 范围继续取交集；新增商品资源不隐式授予已有订单范围角色 |
| 平台商品明细 | 沿用 `listings.product_detail.view/manage/import`；来源信息和 SKU 状态不泄露凭据 |
| 人工 SKU 冲突处理 | 沿用 `integrations.product_mapping.view/manage/confirm`，确认旧值、事务保护及审计保持有效 |
| 系统管理员 | 生产配置需要 `config.system.manage` 加对应 `config.view/manage/approve/rollback`；继续禁止审批自己的配置版本。商品合同独立审批 `product_contract_approved` 默认关闭，配置提交不等于获准执行；`PRODUCT` 能力也须单独批准只读 |

本次没有新增权限码或放大既有角色数据范围；沿用 V2.44.67 已登记的权限目录。SKU 自动精确关联由获准的商品同步服务执行并审计，普通手工接口不能伪造 `api_exact_match` 来源。仅有平台商品查看权限的用户不显示同步操作，订单资源执行权限不能执行商品任务。

## 平台合同与生产验收边界

- 商品只读候选连接器限 Shopee、TikTok；其他平台不因新增资源枚举而宣称已适配。
- TikTok：检索合同参见 [Search Products 202502](https://partner.tiktokshop.com/docv2/page/search-products-202502)，详情合同参见 [Get Product](https://partner.tiktokshop.com/docv2/page/get-product)。检索与详情分别使用其公布版本，商品读取授权范围为 `seller.product.basic`。冻结、删除记录显式标记为状态快照，不调用不支持的详情接口；仅更新当前授权店铺已知商品/变体的状态及平台时间，未知身份审计跳过，正常继续分页，不覆盖 SKU、标题和映射。过期快照不覆盖较新状态。
- Shopee：[商品列表官方入口](https://open.shopee.com/documents/v2/v2.product.get_item_list?module=89&type=1) 和 [商品详情官方入口](https://open.shopee.com/documents/v2/v2.product.get_item_base_info?module=89&type=1) 本轮访问返回 403。现有候选字段/分批详情逻辑通过离线合同测试，不登记为真实账户验证完成。管理员必须取得适用站点的正式合同证据并完成试运行，才可审批商品接口。
- 未验证真实平台签名、额度、完整历史商品覆盖与大规模分页；Shopee 当前只开放 `NORMAL` 范围，其他状态明确拒绝。TikTok 超过官方单次检索规模限制的店铺需另行验收分段策略。不得以本地 fixture 通过宣称全部存量商品已经入档。
- 本轮不启用平台商品写入、改价、改库存或自动刊登；后续全球刊登仍由独立写入策略与审批控制，不受商品只读审批替代。

## 迁移与运维交接

- `masterdata.0013_store_external_identity_constraint`：店铺外部身份预检、可空唯一键回填及约束。
- `integrations.0023_warehouse_external_identity`：仓库外部编码/区域、历史配置回填及有效外部身份唯一键；发现重复先阻断，不自动合并。
- `integrations.0024_platform_product_readonly_sync`：登记商品同步资源和可信 API 精确关联来源。
- `configcenter.0003_product_readonly_endpoint_defaults`：前向补充商品端点默认值和独立审批默认关闭；不覆盖已有审批版本，不改旧迁移。
- 上线前由架构员在备份及隔离验收库运行只读 `python manage.py report_external_identity_preflight --tenant-id <租户ID>`，人工处理重复或缺失身份，再验证迁移与已有映射报告。不得为通过唯一约束删除历史业务记录。
- 本地为 SQLite 内存测试库；未具备 MySQL 实例，必须补生产同版本 MySQL 的旧数据迁移验收。失败时暂停发布，保留预检输出和备份；回退优先关闭新资源并切回应用版本，不直接逆向删除新身份数据或配置。

## 页面验收

- 隔离 Mock 预览 `http://127.0.0.1:4187`；原页面和真实平台配置未操作。
- Edge / Playwright：桌面 1600×1050、小屏 390×844。平台商品页按当前店铺、`platform_product` 资源进入同步任务；空任务状态有返回店铺配置的下一步指引。
- 仓库绑定显式区分本地档案编码与服务商外部仓库编码；同配置换外部编码必须确认，旧任务停用、旧授权保留历史，新绑定回显正确。
- 商品页面展示 API/导入/人工来源、平台更新时间、新旧 SKU 与自动精确关联状态；权限不足隐藏同步按钮。
- 按前端测试技能执行渲染、交互及截图检查，修正长外部仓库编码与授权历史表撑破弹窗的问题；最终演练无页面运行时错误及失败响应。
- 证据目录：`C:/Users/Administrator/AppData/Local/Temp/saas-v24468-qa`；`product-desktop.png`、`product-sync-context.png`、`warehouse-external-binding.png`、`product-view-only-role.png`、`product-mobile.png`。这些是 Mock 页面证据，不替代真实后端权限及平台联调测试。

## 验收登记

- 主代理后端全仓最终结果：`DB_NAME=:memory: python -m pytest -q`，1039 passed / 28 skipped，207.97 秒；跳过项不视为生产平台联调通过。
- 主代理前端全量：`VITE_USE_MOCK=true npm test -- --run --reporter=dot`，67 个文件 / 407 项通过。
- 主代理生产构建：`VITE_USE_MOCK=false npm run build` 通过，2112 modules；仅保留既有 `@vueuse` PURE 注释警告。
- 主代理 Django `manage.py check`：0 issues；`makemigrations --check --dry-run`：No changes detected。
- `git diff --check`：无代码空白错误（仅工作区既有 LF/CRLF 提示）；生产控制树、Compose 与发布工作流差异为空。
- 新增 SKU API 双码一致性及受控同码批量重传 6 项、商品入档/状态快照 12 项、只读合同 11 项分别通过；主代理实际 scheduler → adapter → canonical 入档 → checkpoint 的两页重复运行验证通过，网络端为 fixture，不使用真实凭据。
- 独立复核发现的同码批量重传误拦已修复并补测试，主代理复核修正；迁移前查询新字段的问题、平台类型编辑导致身份键失效的问题均补充守卫及回归。
- 批量维护延续既有逐行结果返回语义，允许部分成功并列出失败行；本轮未改为全有或全无。SKU 双码本身矛盾的批次在写入前拒绝，不静默选择其中一个编码。
- 尚未提交为发布镜像或部署虚拟机。上述结论仅表示本地候选实现及测试，不代表生产同库迁移、真实平台试运行或架构员发布批准。

## 完整文件清单

本轮候选增量涉及以下 57 个文件。生产控制树、Compose、镜像定义与发布工作流不在修改范围内；`backend/config/settings/base.py` 仅登记默认关闭的商品审批和商品只读端点。

- `backend/apps/configcenter/migrations/0003_product_readonly_endpoint_defaults.py`
- `backend/apps/integrations/adapters.py`
- `backend/apps/integrations/capability_gate.py`
- `backend/apps/integrations/management/commands/report_external_identity_preflight.py`
- `backend/apps/integrations/migrations/0023_warehouse_external_identity.py`
- `backend/apps/integrations/migrations/0024_platform_product_readonly_sync.py`
- `backend/apps/integrations/models.py`
- `backend/apps/integrations/platform_capabilities.py`
- `backend/apps/integrations/platform_product_ingestion.py`
- `backend/apps/integrations/product_mapping_service.py`
- `backend/apps/integrations/production_settings.py`
- `backend/apps/integrations/readiness_service.py`
- `backend/apps/integrations/readonly_clients.py`
- `backend/apps/integrations/serializers.py`
- `backend/apps/integrations/subject_access_service.py`
- `backend/apps/integrations/views.py`
- `backend/apps/integrations/warehouse_authorization_service.py`
- `backend/apps/integrations/workspace_service.py`
- `backend/apps/listings/platform_product_details.py`
- `backend/apps/listings/serializers.py`
- `backend/apps/listings/views.py`
- `backend/apps/masterdata/migrations/0013_store_external_identity_constraint.py`
- `backend/apps/masterdata/models.py`
- `backend/apps/masterdata/serializers.py`
- `backend/apps/masterdata/views.py`
- `backend/config/settings/base.py`
- `backend/tests/test_connection_capability_matrix.py`
- `backend/tests/test_external_identity_preflight.py`
- `backend/tests/test_external_identity_uniqueness.py`
- `backend/tests/test_platform_product_details.py`
- `backend/tests/test_platform_product_ingestion.py`
- `backend/tests/test_platform_product_readonly_contract.py`
- `backend/tests/test_platform_product_sku_api_consistency.py`
- `backend/tests/test_product_ingestion_permission_review.py`
- `backend/tests/test_product_sync_end_to_end_review.py`
- `docs/06_release/system_v2.44.68_archive_identity_product_ingestion_20260905.md`
- `frontend/src/api/integrations.js`
- `frontend/src/components/Phase2DataPage.vue`
- `frontend/src/components/ProductMappingPanel.vue`
- `frontend/src/components/SubjectApiAccessDialog.vue`
- `frontend/src/mock/integrations.js`
- `frontend/src/mock/productionSettings.js`
- `frontend/src/views/integrations/IntegrationWorkspace.vue`
- `frontend/src/views/integrations/PlatformDrillWorkbench.vue`
- `frontend/src/views/integrations/SyncIncidentList.vue`
- `frontend/src/views/integrations/SyncJobList.vue`
- `frontend/src/views/integrations/SyncRunList.vue`
- `frontend/src/views/masterdata/PlatformProductDetailList.vue`
- `frontend/src/views/masterdata/StoreMasterList.vue`
- `frontend/src/views/settings/PlatformIntegrationReadiness.vue`
- `frontend/src/views/settings/ProductionIntegrationSettings.vue`
- `frontend/tests/mock-integration-resource-filter-runtime.spec.js`
- `frontend/tests/platform-product-detail-runtime.spec.js`
- `frontend/tests/production-integration-settings.spec.js`
- `frontend/tests/subject-api-access-dialog-runtime.spec.js`
- `frontend/tests/sync-job-product-context-runtime.spec.js`
- `frontend/tests/warehouse-api-binding-closure.spec.js`
