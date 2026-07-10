# P1-B-FIX-002 商品页面联调整改记录

## 整改内容

- 替换商品页面的 `Stage0Placeholder` 展示。
- `ResearchList.vue`：列表、loading、error、empty、table。
- `ResearchDetail.vue`：只读详情、基础表单占位、附件占位。
- `ProductMasterList.vue`：SPU/SKU 列表展示。
- `ProductMasterDetail.vue`：SPU 详情、SKU 表格、附件占位、编码冻结按钮。
- `ProductStatusList.vue`：商品状态列表和状态汇总。
- 更新 `frontend/src/api/products.js` 和 `frontend/src/mock/products.js`。

## 接口

- `/api/internal/products/research/`
- `/api/internal/products/spus/`
- `/api/internal/products/skus/`
- `/api/internal/products/spus/{id}/freeze-code/`

## 安全确认

- 商品页面未访问 `/api/external/*`。
- 商品页面未访问 `/api/finance/*`。
- 商品页面未调用 `/admin/`。
- 未上传真实附件。
- 未保存真实商品资料。
