# P1-B-002 Change Log

## Task

商品市调与商品主数据页面阶段1接口联调。

## Preconditions

- 当前分支：`feature/phase1-b-frontend-api-integration`
- 当前 HEAD 未在 `feature/ar0-001-stage0-file-scope` 分支上开发。
- 本次变更未修改 `backend/`、`rpa-agent/`、`docs/04_rpa/`。
- 未连接真实平台，未写入真实商品资料、真实附件、真实账号或 Token。

## Input Documents

- 已读取：`docs/00_stage0/frontend_api_mapping.md`
- 缺失：`docs/03_api/phase1_api_priority.md`

## Changes

- `frontend/src/api/products.js`
  - 保留 `VITE_USE_MOCK` 下的 Mock fallback。
  - 商品市调使用 `/api/internal/products/research/` 和 `/api/internal/products/research/{id}/`。
  - 商品主数据使用 `/api/internal/products/spus/`、`/api/internal/products/spus/{id}/` 与 `/api/internal/products/skus/`。
  - 编码冻结使用 `/api/internal/products/spus/{id}/freeze-code/`。

- `frontend/src/mock/products.js`
  - 补充市调详情、SPU详情、SKU列表、状态列表、编码冻结 Mock 返回。
  - Mock 数据均为示例数据，不包含真实商品资料。

- `frontend/src/views/products/`
  - `ResearchList.vue`：展示市调列表、搜索条件占位、loading、error、empty、fallback提示。
  - `ResearchDetail.vue`：展示市调基础信息表单、竞品资料区、附件上传占位、审批按钮占位。
  - `ProductMasterList.vue`：展示 SPU/SKU 主数据列表、搜索条件占位、loading、error、empty、fallback提示。
  - `ProductMasterDetail.vue`：展示基础属性、图片占位、SKU资料、箱规重量、编码冻结按钮。
  - `ProductStatusList.vue`：展示商品生命周期状态与销售状态汇总和列表。

- `frontend/README.md`
  - 增加阶段1商品页面联调说明。

## Boundary Notes

- 商品页面未访问 `/api/external/*`。
- 商品页面未访问 `/api/finance/*`。
- 商品页面未调用 `/admin/`。
- 前端未承载真实权限判断。
- 未上传真实附件。
- 未将真实业务数据保存到代码仓库。

## Validation

- `rg "/api/external|/api/finance|/admin/|/admin" frontend/src/api/products.js frontend/src/views/products`：无结果。
- `rg "BIGSELLER|SHOPEE|TIKTOK|TOKEN|API_KEY|PASSWORD|SECRET" frontend/src/api/products.js frontend/src/mock/products.js frontend/src/views/products`：无结果。
- `rg "/api/internal/products" frontend/src/api/products.js frontend/src/views/products -n`：仅显示商品内部 API 路径。
- `git diff --name-only -- backend rpa-agent docs/04_rpa`：无结果。
- 已执行：`cd frontend && npm run build`
- 结果：构建通过。
- 观察项：
  - Rollup 移除了 `@vueuse/core` 中位置不合规的 `/* #__PURE__ */` 注释。
  - 仍存在 Vite chunk size warning：`dist/assets/index-C9pt1ZWT.js` 约 `1,120.89 kB`，gzip 后约 `368.80 kB`。
  - 阶段1不强制拆包，继续作为性能优化观察项跟踪。
