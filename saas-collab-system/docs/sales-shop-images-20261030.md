# 销售平台商品图片验收记录（2026-10-30）

基线：实时生产提交 `435c29841191de7b2dd5351c30389281856d2141`。

范围：销售订单详情与退款商品行、SKU 销量报表、实时销售大屏商品排行、销售运营商品列表及原因详情。图片仅从平台商品明细按租户、平台、店铺、平台规格 ID 精确关联；缺规格或聚合存在多店/多规格歧义时显示占位，不回退内部商品图片。运营订货单是国家级需求且没有店铺维度，图片列显示“无店铺信息”。缺图和加载失败均有占位；支持商品图预览。

验收结果：

- `python -m compileall -q apps/sales_management`：通过。
- `git diff --check`：通过。
- 后端定向测试（`--nomigrations`，图片改动未涉及 schema）：45 passed，包含 sales reports、realtime board、board declines、sales operations、订单/退款商品明细。
- 新增 `frontend/tests/salesReportImages.test.js`：1 passed，覆盖商品图渲染、歧义占位和缺图占位。
- `npm run build`：通过。

未上线：本次只修改源码并本地验收，没有部署、数据库迁移或提交。
