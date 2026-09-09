# System V2.44.87 商品导入导出审核候选

## 候选结论

V2.44.87 已从实际登记并部署的 V2.44.86 提交 `87def33bb7f17785a41be023f55260c353451f67` 建立干净候选，状态为 **REVIEW_PENDING / 未合并 / 未部署 / 未登记生产账本**。候选只进入远端代码审查和 CI 通道；生产 `main`、部署标签、虚拟机运行镜像、数据库和双版本账本均不得在审核通过前改变。

## 实际增量

- 商品明细页把商品新增、旧档案、图片批量导入和 BigSeller 商品 SKU 表导出收纳到“导入与导出”菜单；商品新增与旧档案导入使用独立上传弹窗、模板和处理说明。
- 商品新增 CSV 导入沿用现有旧档案创建接口，随后生成 SPU/SKU，并为成功生成的 SKU 下载 BigSeller `.xlsx`；手工导出只处理已勾选且已有 SKU 编码的记录。
- 组合商品页保留“新建组合 SKU”，新增导入/导出菜单、CSV 模板与上传弹窗；批量创建继续调用既有 SPU、SKU、组合明细 API，并可生成 BigSeller 组合商品表。
- BigSeller 工作簿在浏览器端生成最小 OOXML/ZIP 文件，不新增第三方依赖、不上传文件到外部站点。
- 商品删除修复：通用反向引用扫描跳过 unmanaged 只读投影，避免先删 SKU 再删无业务引用 SPU 时访问缺失数据库视图并返回 500；并发外键竞态统一转换为稳定的 `STATE_CONFLICT` / HTTP 409。

## 变更边界

代码和测试限于以下 9 个路径：

1. `backend/apps/products/views.py`
2. `backend/tests/test_product_actions.py`
3. `frontend/src/api/products.js`
4. `frontend/src/utils/bigsellerWorkbook.js`
5. `frontend/src/views/products/ProductBundleManager.vue`
6. `frontend/src/views/products/ProductDetailData.vue`
7. `frontend/tests/bigseller-workbook.spec.js`
8. `frontend/tests/product-bundle-buttons.spec.js`
9. `frontend/tests/product-detail-data.spec.js`

本批无模型或迁移改动，无菜单注册、路由、权限目录、角色权限、生产部署控制或环境文件改动。来源开发工作区基于旧分支且包含大量其他未提交变化，因此候选没有整体复制或合并来源工作树，而是逐 hunk 移植到 V2.44.86 基线。

## 验证证据

- 后端删除专项：`9 passed`。
- 后端全量：`1234 passed, 28 skipped`。
- Django `check`：通过；`makemigrations --check --dry-run`：`No changes detected`。
- 前端候选专项：3 个文件、`19 passed`。
- 前端全量（`VITE_USE_MOCK=true`）：86 个文件、`513 passed`。
- 前端生产构建（`VITE_USE_MOCK=false`）：通过，2132 个模块。
- `ci_guard.py --root .`：通过。
- `production-baseline-check --ci`：通过。
- `git diff --check`：通过。

## 审核关注点

- 组合商品导入当前按 UTF-8 CSV 读取；来自非 UTF-8 系统的文件应先另存为 UTF-8。本候选不宣称新增 GB18030 兼容。
- 组合成本分摊比用于当次生成的 BigSeller 表；现有后端组合明细模型没有独立持久化该字段，重新加载后不能把它作为权威业务数据。本候选不扩展数据库模型或迁移。
- 浏览器生成的工作簿只用于导入 BigSeller；审核部署前仍应以一份脱敏的真实模板做人工列顺序和导入预检，不执行真实库存或价格写入。

## 审核、发布与回退门禁

1. 远端 PR CI 全绿并完成代码审查后，才允许合并到 `main`。
2. 合并后以该合并提交执行生产发布工作流的只读/构建门禁；没有审核批准和不可变镜像摘要时不得选择 `deploy`。
3. 本批无数据库迁移。部署前仍必须确认当前生产双账本严格为 V2.44.86，且其提交、运行镜像、备份证据与账本哈希一致。
4. 部署成功并完成商品导入弹窗、BigSeller 文件生成、SKU→SPU 删除链路验收后，才允许按严格父版本 `2.44.86` 登记 `2.44.87`。
5. 代码回退点为 `87def33bb7f17785a41be023f55260c353451f67`，部署回退标签为 `v2.44.86-deployed`；禁止预先创建 `v2.44.87-deployed`。

## 当前生产基线只读核验

- `origin/main` 与远端 `v2.44.86-deployed` 均指向 `87def33bb7f17785a41be023f55260c353451f67`；远端没有 V2.44.87 标签。
- 双版本账本当前版本均为 `2.44.86`、父版本均为 `2.44.85`，账本哈希和运行镜像核验通过。
- 已登记的 V2.44.86 备份证据为 `/home/dfcy01/backups/production-control/20260908T224809Z-87def33bb7f17785a41be023f55260c353451f67.sql.gz`，SHA-256 为 `4476d74fb709ca1aba0fdac5a0466ed127be283ebead2b651ca1a03a89980ef6`。
- 复跑严格审计时发现相同 V2.44.86 提交 SHA 匹配到 2 份备份而非脚本期望的唯一 1 份，因此审计以退出码 2 停止。该异常不影响上述已登记备份的既有证明，但在 V2.44.87 部署审核前必须只读确认两份备份的来源、时间、哈希和保留策略；不得为满足脚本而删除证据。
