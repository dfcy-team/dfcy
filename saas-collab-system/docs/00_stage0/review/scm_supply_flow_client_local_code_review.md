# SC-SUPPLY-FLOW-CLIENT-3/4 本地代码审核

- 日期：2026-08-08
- 结论：`PASS_FOR_FINAL_LOCAL_GATE`

## 范围

内部 Web 集货/发运运营面板与供应商微信小程序 assignment/交接页面。客户端只调用 API2；生产附件上传、下载票据和第三方物流连接保持关闭。

## P1 复核

1. Web shipment 状态已与后端统一：draft、loading、customs_declared、dispatched、port_arrived、warehouse_arrived、warehouse_cleared、cancelled。
2. consolidation ready 使用 exact `supply.consolidation.receive`，不再误用 manage。
3. 集货分配明确输入物理箱 ID，shipment 转入明确输入 consolidation allocation ID；多次 dispatch 只发送 transferred shipment allocation IDs。
4. supplier DTO 返回当前发布版本下裁剪后的 accepted evidence ID/状态；小程序首次交接使用该集合，不再读取尚未提交的冻结 evidence_ids。

## 双端边界

- development + localUploadEnabled 双开关之外不展示上传能力；Mock/生产不伪造成功。
- JPEG/PNG、HEIC 提示、10 MiB、相机/相册拒绝、重复点击、弱网重试文案及 safe-area 已覆盖。
- 地址支持换行，时间由服务端 ISO 8601 提供；权威状态始终刷新 API 后更新。
- download-ticket 明确未启用。

## 验证

- Frontend 定向 Vitest：`3 passed`。
- Frontend build：通过。
- Miniapp tests：`29 passed`。
- Miniapp validate：通过。
- Backend supplier accepted-evidence DTO 回归：`9 passed`。

允许进入最终本地全链路门禁；不代表生产发布或 Android/iPhone 真机验收完成。
