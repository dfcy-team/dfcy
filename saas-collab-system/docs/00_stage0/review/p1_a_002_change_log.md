# P1-A-002 商品市调与商品主数据接口变更记录

## 基本信息

- 任务编号：P1-A-002
- 任务名称：商品市调与商品主数据 MVP 后端接口
- 执行分支：feature/phase1-a-backend-mvp-api
- 执行目录：saas-collab-system/

## 准入检查

- 当前分支已确认是 feature/phase1-a-backend-mvp-api。
- 当前分支已确认不是 feature/ar0-001-stage0-file-scope。
- 本次未修改 frontend/、rpa-agent/、docs/04_rpa/。

## 输入文档

以下输入文档在当前 main 基线中尚未落地，仅存在对应 docs 目录占位：

- docs/01_architecture/phase1_mvp_scope.md：未找到
- docs/03_api/phase1_api_priority.md：未找到
- docs/05_test/phase1_acceptance_checklist.md：未找到

本次按用户提供的 P1-A-002 任务说明执行，未补建上述架构/API/验收文档，避免越过本任务输出范围。

## 本次变更

### backend/apps/products/

新建 products app，包含：

- ProductResearch
  - tenant
  - research_no
  - product_name
  - platform
  - competitor_url
  - estimated_sales
  - estimated_gross_margin
  - risk_points
  - approval_status
  - created_by
  - created_at
  - updated_at

- ProductSPU
  - tenant
  - spu_code
  - product_name
  - category
  - lifecycle_status
  - sales_status
  - is_code_frozen
  - created_at
  - updated_at

- ProductSKU
  - tenant
  - spu
  - sku_code
  - size
  - material
  - selling_points
  - package_weight
  - package_volume
  - is_code_frozen
  - created_at
  - updated_at

### API 接口

新增 internal 产品接口：

- GET /api/internal/products/research/
- POST /api/internal/products/research/
- GET /api/internal/products/research/{id}/
- PATCH /api/internal/products/research/{id}/
- GET /api/internal/products/spus/
- POST /api/internal/products/spus/
- GET /api/internal/products/spus/{id}/
- PATCH /api/internal/products/spus/{id}/
- POST /api/internal/products/spus/{id}/freeze-code/
- GET /api/internal/products/skus/
- POST /api/internal/products/skus/
- GET /api/internal/products/skus/{id}/
- PATCH /api/internal/products/skus/{id}/

## 安全与边界

- 所有 products 模型均包含 tenant。
- 所有查询均按 request.user.tenant 过滤。
- 所有接口均使用 IsInternalUser。
- external 用户不可访问。
- rpa 用户不可访问。
- SPU 编码冻结后不得修改 spu_code。
- SKU 编码冻结后不得修改 sku_code。
- SPU freeze-code 接口会同步冻结该 SPU 下现有 SKU 编码。
- 暂不接真实平台。
- 暂不实现真实审批流，仅保留 approval_status。
- 未写入真实密钥、真实平台配置、账号、Token 或 API Key。

## 测试覆盖

- internal 用户可创建和查询商品市调。
- internal 用户可创建 SPU 和 SKU。
- external 用户拒绝访问。
- rpa 用户拒绝访问。
- tenant 隔离：列表和详情均不可越租户访问。
- freeze-code 后禁止修改 SPU/SKU code 字段。
- 统一响应结构 success/code/message/data 已覆盖。
- SKU 不可绑定其他 tenant 的 SPU。

## 验证记录

```powershell
cd saas-collab-system/backend
python manage.py check
pytest tests/test_products_api.py
pytest
```

执行结果：

- python manage.py check：通过，System check identified no issues。
- pytest tests/test_products_api.py：通过，7 passed。
- pytest：通过，69 passed。
