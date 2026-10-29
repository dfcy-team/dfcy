# 采购付款 API 契约

统一路径：`/api/internal/supply-chain/v2/costs/{kind}/{id}/payments/`，`kind` 为 `purchase`、`shipment` 或 `batch`。

`GET` 返回 `{data:{summary:{due_amount,opening_amount,paid_amount,applied_amount,remaining_amount,available_prepayment},version,entries:[],available_prepayments:[]}}`。金额均为四位小数的十进制字符串。`opening_amount` 表示旧累计结算形成的期初付款；`paid_amount` 是期初加逐笔实付，`applied_amount` 是抵扣，`remaining_amount=max(due_amount-paid_amount-applied_amount,0)`（采购单抵扣只是用途，不重复减少已付）。`purchase` 的 `available_prepayment` 是采购预付款未抵扣余额；发货单只列出关联采购单的可用预付款。entry 统一包含 `{id,entry_type:'payment'|'application'|'opening',amount,date,reference_number,notes,account_snapshot,attachments,reversed,is_reversal,reversal_reason}`。`available_prepayments` 包含 `{id,reference_number,available_amount}`。

`POST` 新增单笔付款，必需 `amount`（大于零）、`date`、`payee_account_id`、`expected_version`；`notes` 可选，`reference_number` 可选（省略时系统生成）。请求必须携带 `Idempotency-Key`。账户必须属于当前租户及关联供应商/货运公司且有效。响应返回更新后的 summary、version、entries 和 available_prepayments。付款记录不可编辑或删除。

采购预付款抵扣：`POST /api/internal/supply-chain/v2/costs/shipment/{id}/prepayment-applications/`，请求 `{payment_id,amount,date,expected_version}` 并携带幂等键；只允许抵扣当前发货单关联采购单的预付款未抵扣余额。抵扣不产生支付或成本变更。

冲销付款：`POST /costs/{kind}/{id}/payments/{payment_id}/reverse/`，请求 `{reason,expected_version}` 并带幂等键。已有未撤销抵扣的采购预付款不能冲销。冲销抵扣：`POST /costs/shipment/{id}/prepayment-applications/{application_id}/reverse/`，同样请求 `{reason,expected_version}`。冲销只追加记录，summary 按未冲销记录计算。

凭证：`GET/POST /costs/{kind}/{id}/payments/{payment_id}/vouchers/`；POST 使用 multipart 字段 `file`，GET 列出凭证。下载路径追加 `/{voucher_id}/download/`。沿用现有 PDF/JPG/PNG 校验及 10MB 上限。

旧累计结算 API 保留读取兼容；已有旧累计金额作为期初值。逐笔付款启用后，旧累计写入必须拒绝，避免重复登记。
