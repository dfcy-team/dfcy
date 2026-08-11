# PR-A3 销售与库存离线导入 Draft 发布说明

状态：Draft / offline synthetic only / not production approved。

本变更新增 `pr-a3-normalized-v1`、离线订单/退款/库存模型、批次幂等、事务游标、tenant/store/platform 隔离及内部查询/导入/重试 API。默认 `PR_A3_SYNTHETIC_IMPORT_ENABLED=false`。

本变更不包含真实 Shopee/TikTok 响应 adapter，不发起真实网络请求，不消费 webhook，不运行计划任务，不执行历史回补、平台写入、采购、财务或 RPA。两平台继续 `pending/mock`，Production synchronization 保持 OFF。

本 Draft 已通过 SQLite、focused/full backend、frontend tests/build 和本地安全扫描。MySQL 8.4 因本机环境不可用保持 BLOCKED；因此不满足生产发布或真实同步条件。

部署前若只进行批准的离线合同测试，必须显式设置 `PR_A3_SYNTHETIC_IMPORT_ENABLED=true`，使用 synthetic normalized 数据和固定 Review SHA。其他环境保持默认关闭。真实平台样本与 adapter 必须进入新的独立设计、安全和数据复审。
