# 正式 SaaS 只读数据并入记录（2026-08-24）

## 基线与回滚点

- Git 基线：`8e61d8ea605e439603d943bef203da1890b1a3a0`
- 工作分支：`feature/formal-saas-live-readonly-merge`
- 本地 MySQL 迁移前备份：`C:\Users\Administrator\Documents\Codex\backups\formal-live-readonly-merge-20260824\pre-formal-readonly-merge.sql`
- 备份大小：14,451,798 bytes
- 备份 SHA-256：`AB989E643A920813292AE6B47CDA7746F58E4F35F6CF114D52A712472155416B`
- 本地迁移后 schema-only：`backend/schema/local_formal_merge_20260824_schema.sql`（207 张表）

仓库中的 `backend/schema/current_vm_database_schema.sql` 未被覆盖。它包含 215 张表，其中有 27 张 `stg_devb_20260824_*` 暂存表；当前本地 MySQL 不含这些暂存表，但含 19 张该快照未记录的正式业务表。合并前必须由发布负责人决定正式环境采用哪个结构集合，不能用本地 dump 静默覆盖正式快照。

## 已并入

- Shopee、TikTok Shop、极风 WMS 生产只读客户端、HTTPS host allowlist、托管凭据引用和分页。
- 订单、退款、库存标准合同；复用 `sales_order`、`sales_order_item`、`refund_return`、`refund_return_item`、`inventory_snapshot`，没有创建平行事实表。
- 事实表幂等写入、`source_run`、`payload_hash`、整页事务和成功后游标推进。
- Celery 正式只读运行入口；HTTP 请求只入队，不在请求线程执行全量同步。
- TikTok Token 过期直接要求人工重新授权；人工刷新接口要求显式确认。
- 新权限 `integrations.run_live_readonly`；旧 `integrations.run` 仅保留给 Mock 运行入口。
- 生产前端禁止 Mock fallback；本地 Mock 也改为显式 `VITE_USE_MOCK=true` 才启用。
- 销售 CSV/TXT 真实文件、租户隔离目录、随机文件名、SHA-256、过期时间、五分钟下载凭证和下载审计。
- 同步成功日志只保存计数和字段名摘要，不保存原始业务样本或凭据。

## Django migrations

- `reports.0007_real_export_files`
- `permissions.0032_seed_live_readonly_sync_permission`

本地 MySQL 已应用；`python manage.py migrate --plan` 返回无待执行迁移。

## 环境变量（仅占位符）

生产只读能力默认关闭。值必须由发布审批和凭据托管流程提供，不得写入 Git。

```dotenv
LIVE_READONLY_SYNC_ENABLED=false
PLATFORM_NETWORK_MODE=DISABLED_UNTIL_APPROVED
LIVE_PLATFORM_SECURITY_APPROVED=false
LIVE_PLATFORM_ALLOWED_HOSTS=APPROVED_HOSTS_ONLY
LIVE_CUSTODY_BACKEND=refuse
LIVE_CUSTODY_SERVICE_URL=YOUR_APPROVED_CUSTODY_URL_HERE
LIVE_CUSTODY_SERVICE_HOST=YOUR_APPROVED_CUSTODY_HOST_HERE
CREDENTIAL_CUSTODY_PATH=YOUR_PROTECTED_CUSTODY_PATH_HERE
LIVE_SHOPEE_ORDER_LIST_PATH=/api/v2/order/get_order_list
LIVE_SHOPEE_ORDER_DETAIL_PATH=/api/v2/order/get_order_detail
LIVE_SHOPEE_RETURN_LIST_PATH=/api/v2/returns/get_return_list
LIVE_SHOPEE_RETURN_DETAIL_PATH=/api/v2/returns/get_return_detail
LIVE_TIKTOK_ORDER_LIST_PATH=/order/202309/orders/search
LIVE_TIKTOK_ORDER_DETAIL_PATH=/order/202309/orders
LIVE_TIKTOK_RETURN_LIST_PATH=/return_refund/202602/returns/search
LIVE_JIFENG_WMS_INVENTORY_PATH=/api/inventory/queryInventory
REPORT_EXPORT_ROOT=YOUR_CONTROLLED_EXPORT_DIRECTORY_HERE
REPORT_EXPORT_TTL_SECONDS=86400
```

## 验证结果

- Django check：PASS
- Migration drift：PASS，no changes detected
- Migration plan：PASS，无待执行迁移
- 正式并入专项后端测试：6/6 PASS
- 专项测试加权限目录测试：9/9 PASS
- 前端正式并入相关测试：44/44 PASS
- 前端 production build：PASS
- `git diff --check`：PASS
- 前端全量：217/218 PASS；唯一失败是旧 `frontend/nginx.pilot.conf` 缺少测试要求的 HTML/静态资源缓存段，与本次数据并入无关。

## 尚未完成的发布门禁

以下事项不能在没有正式审批、平台测试账号和发布决策的情况下代替完成：

- 平台原始 order/return list/detail JSON 的受控 TXT 归档。本轮 TXT 已是真实可下载文件，但内容来自脱敏标准事实，不冒充平台原始 JSON。
- 一个 tenant、Shopee 店铺、TikTok Shop 店铺和 PH/TH/MY WMS 的灰度同步与逐项对账。
- 六模块生产数据回填、备份恢复演练、正式镜像构建/digest、Git commit/tag 和发布审批。
- `current_vm_database_schema.sql` 与本地实际结构差异的发布裁决。

在上述门禁通过前，必须保持 `LIVE_READONLY_SYNC_ENABLED=false`。

## 回滚

1. 关闭 `LIVE_READONLY_SYNC_ENABLED`，停止新增正式只读任务。
2. 保留 `SyncRun`、审计和已写入事实，不执行全表删除。
3. 代码回到基线 commit；前端不得自动切回 Mock 冒充生产数据。
4. 新迁移均为加字段/种权限，默认保留结构。只有确认无数据依赖后才反向迁移。
5. 如必须恢复数据库，先校验上述备份 SHA-256，再在独立恢复实例验证，禁止直接覆盖当前库。
