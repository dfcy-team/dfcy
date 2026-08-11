# SC-SUPPLY-FLOW-API-2 本地代码审核

- 日期：2026-08-08
- 结论：`PASS_FOR_CLIENT_IMPLEMENTATION`

## 范围

附件、集货、发运的内部 Web API、供应商 Web API、微信小程序 API，exact permission、完整 DataScope、供应商 binding/capability、通道互斥、DTO 裁剪和幂等适配。所有写入复用领域服务；未接生产对象存储或第三方系统。

## P1 复核

1. 新增默认关闭的 `ConsolidationSupplierCapability.can_submit_handover`；附件和交接写动作必须显式启用，未借用 packing capability。
2. 上传 token 改为服务端密钥 HMAC 派生，可在有效期内安全重建，同键重放响应稳定；数据库不存明文。
3. 不安全的可预测下载票据已 fail-closed 返回 503；supplier DTO 移除 SHA-256、内部业务绑定和存储信息。
4. 扩充 exact permission、完整/残缺 CUSTOM、OWN/DEPARTMENT、跨租户/供应商、Web/miniapp 通道、capability、幂等及 shipment 权限分离矩阵。

## 验证

- SQLite API2 + attach + consolidation + shipment：`28 passed`。
- MySQL 8.4 API2：`7 passed in 152.92s`。
- fresh MySQL migrations（含 consolidation.0006）：通过。
- check、migrate plan：通过。
- 临时数据库、容器、卷、缓存已清理；13314 空闲。
- 全仓 migration drift 仍只有既有 products 0014，未越权修改。

## 准入边界

允许进入内部 Web 与供应商微信小程序本地页面实现。下载、生产二进制上传、第三方物流/报关连接仍关闭；任何客户端不得绕过 API 推导或直接写权威状态。
