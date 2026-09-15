# V2.44.110 已有 SPU 新增 SKU 导入发布登记

日期：2026-09-15  
状态：`REGISTERED_FOR_CONTROLLED_RELEASE`。本版本已完成隔离候选登记与定向门禁，等待虚拟机功能发布通道执行受控合并、完整 CI、不可变镜像构建和部署。

## 版本登记

- 候选版本：`V2.44.110`
- 正式父版本：`V2.44.109`
- 正式父 SHA：`efeb04ed515f3d3fec97cc460903c276df1891d2`
- 候选分支：`release/v244110-product-import-existing-spu`
- 发布通道：虚拟机功能发布通道
- 数据库迁移：新增 `products.0018_productlegacyitem_target_spu`
- 菜单、路由、权限目录：无变化

## 功能范围

1. “商品新增导入”模板在旧 SPU、旧 SKU 后增加非必填列“新SPU编码”。
2. 新 SPU 编码留空时，继续按现有商品编码规则生成新的 SPU 和 SKU。
3. 填写新 SPU 编码时，将其作为当前租户已有 SPU 的目标编码，仅在该 SPU 下生成新的颜色或规格 SKU；SKU 编码仍由现有 `build_sku_code` 规则生成。
4. 导入和生成阶段均复核当前租户、数据权限、SPU 状态、完整类目编码和属性编码；不存在、跨租户、已终止或属性不一致的目标 SPU 按行拒绝。
5. 暂存记录保存受保护的目标 SPU 关系，并在商品明细和旧商品档案接口中显示目标 SPU 编码及名称；商品明细支持按目标 SPU 搜索。
6. 重复点击生成保持幂等，不重复创建 SKU。

## 变更清单

- `backend/apps/products/models.py`：为 `ProductLegacyItem` 增加可空、受保护的 `target_spu` 关系。
- `backend/apps/products/migrations/0018_productlegacyitem_target_spu.py`：增加目标 SPU 外键。
- `backend/apps/products/import_service.py`：解析“新SPU编码”，执行租户、权限、类目、属性和生命周期校验。
- `backend/apps/products/views.py`：生成 SKU 时锁定并复核目标 SPU，继续通过现有 SKU 序列化器生成标准编码。
- `backend/apps/products/serializers.py`：返回目标 SPU 编码和名称。
- `frontend/src/views/products/ProductDetailData.vue`：更新导入提示和下载模板列。
- 后端、前端测试：覆盖已有 SPU 复用、编码规则、幂等和异常目标拒绝。

## 已完成门禁

- 商品导入模块回归：17 项通过（含目标 SPU 自定义数据范围隔离回归）。
- 已有 SPU 新增 SKU 专项回归：通过，确认 SPU 数量不增加、SKU 编码按规则生成且重复生成不新增记录。
- 商品明细前端契约测试：12 项通过。
- Python 语法检查：通过。
- `python manage.py makemigrations --check --dry-run`：无模型漂移。
- `git diff --check`：通过。

## 受控部署要求

1. 候选必须通过受保护 PR 合入 `main`，生产 workflow 只接受属于 `main` 历史的完整 SHA。
2. 发布通道在候选合入后执行完整后端测试、前端锁定依赖构建、生产基线检查和不可变镜像构建。
3. 发布前执行数据库备份，再运行 `migrate --noinput` 应用 `products.0018_productlegacyitem_target_spu`。
4. 部署后核验商品新增导入模板包含“新SPU编码”，并用现有 SPU 导入一个新颜色或规格 SKU，确认 SPU 未重复创建且 SKU 编码符合规则。
5. 发布结果必须登记正式主干 SHA、后端/前端镜像摘要、迁移摘要、备份结果和健康检查结果。

## 回退边界

若导入、生成或商品明细出现回归，恢复到 V2.44.109 的已登记不可变应用镜像。`products.0018` 只增加可空外键，应用回退时保留该兼容迁移和已写入关系，不执行破坏性的反向迁移；如需重新发布，采用向前修复。
