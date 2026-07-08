# RPA Payload样例索引

本目录存放阶段0 RPA payload 与 result 示例。所有数据均为 demo / placeholder 示例，不包含真实商品、真实店铺、真实账号、真实 URL 或真实 Token。

## JSON用途

- `bigseller_create_product_payload.json`：BigSeller 商品建档任务 payload 示例。
- `bigseller_upload_images_payload.json`：BigSeller 图片上传任务 payload 示例。
- `bigseller_multi_site_listing_payload.json`：BigSeller 多国家复制/刊登任务 payload 示例。
- `bigseller_update_price_payload.json`：BigSeller 页面价格更新任务 payload 示例，必须带审批凭证字段。
- `bigseller_read_page_price_payload.json`：BigSeller 页面价格回读任务 payload 示例，只读采集页面价格。
- `bigseller_collect_listing_status_payload.json`：BigSeller 刊登状态采集任务 payload 示例。
- `rpa_task_success_result.json`：RPA 成功结果回写示例。
- `rpa_task_failed_result.json`：RPA 失败结果回写示例，包含人工接管占位字段。

## 高风险任务规则

- `BIGSELLER_UPDATE_PRICE` 必须带审批凭证字段。
- `approval_status=approved` 才允许 RPA 执行改价。
- RPA 只执行后端已审批任务，不自行决定改价。

## Result回写规则

- RPA result 必须带 `task_id`，用于后端回写和审计追踪。
- success result 必须包含截图或页面快照占位。
- failed result 应包含人工接管所需信息。

## 只读任务规则

- `BIGSELLER_READ_PAGE_PRICE` 是只读任务。
- RPA 不允许保存、提交或修改页面价格。
- RPA 不允许触发平台刊登、价格更新、清仓或促销动作。

## 安全说明

- 所有示例均为 demo / placeholder，不得用于生产。
- 不得在样例中写入真实账号、密码、Token、Cookie、Session、店铺、商品、订单、财务数据或真实平台 URL。
