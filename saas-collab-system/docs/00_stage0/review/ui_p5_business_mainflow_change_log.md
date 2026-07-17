# UI-P5 业务主链路接入变更记录

## 1. 变更目标

将商品、采购和供应商协同从基础占位提升为具备真实 API、权限、data_scope、分页、错误和空态的受控主链路，并明确未实现模块的 pending/mock 边界。

## 2. 后端变更

- 新增商品市调、商品主数据、编码冻结和采购订单动作权限。
- 新增权限级 data_scope 过滤，覆盖 ALL、OWN 和自定义资源范围。
- 商品、采购、供应商集合统一分页。
- 供应商继续强制按当前会话的 `tenant_id + supplier_id` 过滤。
- 新增 UI-P5 权限、租户、范围、分页、幂等和越权测试。

## 3. 前端变更

- 商品、采购、供应商页面增加可用查询、分页、loading/error/empty 状态。
- 编码冻结仅对 `products.master.freeze` 用户显示。
- 供应商反馈使用真实 `PATCH` 合同，不允许页面传入其他 `supplier_id`。
- 刊登和价格改为受控待接入页；API 模式不请求不存在的接口。

## 4. 安全边界

- 未接入真实平台或真实 RPA。
- 未启用自动采购、刊登、改价、清仓或库存修改。
- 未提交真实账号、Token、API Key、财务、订单或供应商数据。
- 前端权限仅控制展示，可信权限和 data_scope 均由后端执行。

## 5. 待复审

需由独立架构复审确认权限码、data_scope、分页兼容、供应商越权、pending/mock 状态和高风险动作边界。

## 6. UI-P5-ARCH-R1 P1 整改

| P1 | 整改内容 | 回归证据 |
|---|---|---|
| 通用 PATCH 绕过工作流 | 商品市调 `approval_status`、SPU `lifecycle_status/sales_status`、采购订单 `status/approval_status` 已设为只读；POST 使用安全默认值，PATCH 显式提交受控状态返回 400。 | `test_product_generic_patch_rejects_workflow_controlled_status_fields`、`test_internal_user_can_manage_purchase_orders_with_unified_response` |
| 供应商完成状态合同不一致 | 后端允许 `completed`，但仅在完成数量等于生产数量时接受；数量不一致返回 400。 | `test_supplier_can_complete_task_only_when_completed_quantity_matches_production_quantity` |
| 页码最大 100 | 页码改为任意有效正整数，只有 `page_size` 保留最大 100 限制。 | `test_ui_p5_pagination_allows_page_numbers_above_100_and_caps_page_size` |

整改后仍需独立 `UI-P5-ARCH-R2` 复审确认关闭情况，本变更记录不替代架构复审结论。
