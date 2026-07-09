# P1-A-003 采购订单与供应商任务接口变更记录

## 基本信息

- 任务编号：P1-A-003
- 任务名称：采购订单与供应商任务 MVP 后端接口
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

本次按用户提供的 P1-A-003 任务说明执行，未补建上述架构/API/验收文档，避免越过本任务输出范围。

## 本次变更

### backend/apps/purchasing/

新建 purchasing app，包含：

- PurchaseOrder
  - tenant
  - po_no
  - sku_code
  - supplier_id
  - quantity
  - unit_price
  - delivery_date
  - payment_terms
  - status
  - approval_status
  - created_by
  - created_at
  - updated_at

新增内部采购接口：

- GET /api/internal/purchasing/orders/
- POST /api/internal/purchasing/orders/
- GET /api/internal/purchasing/orders/{id}/
- PATCH /api/internal/purchasing/orders/{id}/

### backend/apps/suppliers/

新建 suppliers app，包含：

- SupplierTask
  - tenant
  - supplier_id
  - task_no
  - sku_code
  - production_quantity
  - completed_quantity
  - expected_ship_date
  - status
  - is_overdue
  - feedback_note
  - exception_note
  - created_at
  - updated_at

- SupplierShipment
  - tenant
  - supplier_id
  - shipment_no
  - sku_code
  - ship_quantity
  - carton_count
  - weight
  - volume
  - shipping_mark
  - tracking_no
  - attachment_placeholder
  - status
  - created_at
  - updated_at

新增供应商外部接口：

- GET /api/external/supplier/tasks/
- GET /api/external/supplier/tasks/{id}/
- PATCH /api/external/supplier/tasks/{id}/feedback/
- GET /api/external/supplier/shipments/
- POST /api/external/supplier/shipments/
- GET /api/external/supplier/shipments/{id}/

## 安全与边界

- PurchaseOrder 仅 internal 用户可访问。
- SupplierTask 和 SupplierShipment 仅 external 用户可访问。
- 供应商接口按 tenant_id + supplier_id 过滤。
- supplier_id 来源于 ExternalUserProfile.supplier_id，internal 用户不能通过 external 接口伪装 supplier。
- external 用户不能访问 /api/internal/purchasing/*。
- rpa 用户不能访问供应商业务接口。
- 供应商接口不返回 unit_price、payment_terms 等采购财务字段。
- 暂不接真实微信服务号。
- 暂不接真实小程序。
- 暂不接真实外部平台。
- 不实现真实付款。
- 未写入真实密钥、真实平台配置、账号、Token 或 API Key。

## 测试覆盖

- internal 可管理采购订单。
- external 不能访问 internal 采购接口。
- supplier 只能看自己的任务。
- supplier 不能看其他 supplier 的任务或发货记录。
- internal 不能通过 external supplier 接口访问。
- rpa 不能访问 supplier 业务接口。
- tenant 隔离。
- 统一响应结构 success/code/message/data。
- 供应商创建发货记录不暴露采购财务数据。

## 验证记录

```powershell
cd saas-collab-system/backend
python manage.py check
pytest tests/test_purchasing_suppliers_api.py
pytest
python manage.py makemigrations --check --dry-run
```

执行结果：

- python manage.py check：通过，System check identified no issues。
- pytest tests/test_purchasing_suppliers_api.py：通过，7 passed。
- pytest：通过，76 passed。
- python manage.py makemigrations --check --dry-run：通过，No changes detected。
