# System V2.44.88 商品新增导入空旧编码审核候选

## 候选结论

V2.44.88 从已登记并部署的 V2.44.87 提交 `a565c3f0aab80629335075e12149f9609f5cbeca` 建立干净候选。本次只放宽“商品新增”导入：旧 SPU 编码和旧 SKU 编码均可留空，并在导入成功后继续自动生成 SPU/SKU；自动更新和仅更新模式仍要求至少提供一个可匹配的 SKU 编码。候选在远端 PR、CI 和部署验收完成前不得登记生产账本或创建部署标签。

## 实际增量

- `ProductLegacyItem.legacy_sku_code` 改为允许数据库 `NULL` 和表单空值，并增加迁移 `products.0017_productlegacyitem_legacy_sku_nullable`。
- 新增模式允许旧、新 SKU 编码同时为空；每条匿名记录都独立创建，不把空编码当作重复键。服务端只为匿名新增记录返回 `created_ids`，不改变已有带编码记录的导入响应语义。
- 前端优先按 `created_ids` 逐条生成匿名记录，再按 CSV 中的旧/新 SKU 编码生成带编码记录，最终继续生成 BigSeller 商品 SKU 表。
- 商品详情集合、旧档案序列化、生成及重试同步链路把数据库 `NULL` 兼容输出/写入为空字符串，避免把空值传给现有非空的正式 SKU 字段。
- 商品新增模板取消旧 SPU/SKU 两列的必填星号和示例编码，上传弹窗明确提示两列可留空。

## 变更边界

代码、迁移和测试限于以下 10 个路径：

1. `backend/apps/products/models.py`
2. `backend/apps/products/migrations/0017_productlegacyitem_legacy_sku_nullable.py`
3. `backend/apps/products/import_service.py`
4. `backend/apps/products/views.py`
5. `backend/apps/products/detail_views.py`
6. `backend/apps/products/serializers.py`
7. `backend/tests/test_product_legacy_import_v2.py`
8. `frontend/src/views/products/ProductDetailData.vue`
9. `frontend/tests/product-detail-data.spec.js`
10. `docs/06_release/system_v2.44.88_product_import_null_codes_review_20260910.md`

本批不修改菜单、路由、权限目录、角色权限、组合商品逻辑、生产部署控制或环境文件。来源工作区位于旧分支并包含大量无关变化，候选只把需求相关 hunk 移植到 V2.44.87 基线。

## 本地验证证据

- 商品旧档案导入、生成与明细集合专项：`22 passed`。
- 后端全量：`1242 passed, 28 skipped`。
- Django `check`：通过；`makemigrations --check --dry-run`：`No changes detected`。
- 前端契约专项：`12 passed`。
- 前端生产构建：通过。
- 前端全量：`512 passed, 1 failed`；唯一失败为 Windows CRLF 工作树下既有的源码精确 LF 子串断言，实际相邻调用仍存在，本批未触碰该图片批处理逻辑，Linux CI 作为权威门禁。
- `ci_guard.py --root ..`：通过。
- `git diff --check`：通过。

## 审核关注点

- 匿名新增记录没有业务编码可供前端重新查询，因此 `created_ids` 只返回当前请求成功创建且两个 SKU 编码均为空的记录 ID；前端必须直接按这些 ID 生成。
- 迁移仅放宽暂存旧档案字段；正式 `ProductSKU.legacy_sku_code` 仍保持非空，生成和重试同步时统一落为空字符串。
- 单行导入和单条生成仍各自使用既有事务边界。若后续某条生成失败，该行保留为可重试的旧档案，不回滚其他成功行，并在导入结果中显示失败信息。
- 导入按缓存解析分类编码后，会在每行事务内锁定并复核分类及完整父级的启用状态和当前编码；生成接口也会锁定旧档案与完整分类路径，阻断分类停用/移动和重复生成竞态。

## 审核、发布与回退门禁

1. 远端 PR CI 全绿且代码审查无阻断项后，才允许合并到 `main`。
2. 合并提交必须通过生产工作流的静态基线、迁移、全量测试、不可变镜像构建和远端部署门禁；部署前确认双账本严格为 V2.44.87。
3. 部署必须生成并核验数据库备份，再应用 `products.0017_productlegacyitem_legacy_sku_nullable`；运行态需验证后端、前端、Celery、Celery Beat、Redis 和 custody sidecar 镜像及健康状态。
4. HTTP、迁移、匿名新增导入/生成兼容性和运行镜像验收通过后，才允许以严格父版本 `2.44.87` 双账本登记 `2.44.88`，最后创建轻量标签 `v2.44.88-deployed`。
5. 代码回退点与部署回退标签均为 `v2.44.87-deployed`。若已执行迁移，字段放宽本身可向后兼容旧代码；紧急回退应用镜像时不应先收紧数据库列或删除匿名暂存数据。
