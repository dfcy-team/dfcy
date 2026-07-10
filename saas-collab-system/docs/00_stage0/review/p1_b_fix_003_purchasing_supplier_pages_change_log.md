# P1-B-FIX-003 采购与供应商页面联调整改记录

## 整改内容

- 替换采购与供应商页面的 `Stage0Placeholder` 展示。
- 采购页面支持 loading、error、empty、list/table、detail。
- 供应商页面支持 loading、error、empty、list/table、detail、feedback form placeholder、shipment form placeholder。
- 供应商页面展示说明：供应商只能查看和回填当前供应商自己的任务，真实过滤以后端 tenant_id + supplier_id 为准。
- 更新 `frontend/src/api/purchasing.js`、`frontend/src/api/suppliers.js`、`frontend/src/mock/purchasing.js`、`frontend/src/mock/suppliers.js`。

## 接口

- 采购：`/api/internal/purchasing/orders/`
- 供应商：`/api/external/supplier/tasks/`
- 供应商回填：`/api/external/supplier/tasks/{id}/feedback/`
- 供应商出货：`/api/external/supplier/shipments/`

## 安全确认

- 采购页面未访问 `/api/external/*`。
- 供应商页面未访问 `/api/internal/*`。
- 供应商页面未访问 `/api/finance/*`。
- 供应商页面未调用 `/admin/`。
- 未实现真实微信服务号或小程序。
- 未上传真实附件。
- 未写真实供应商账号密码、真实物流单、银行或财务数据。
