# TK GMV Max 单日采集与展示交接

2026-10-31 直接部署至阿里云生产；仅 TK 广告采集、读取及对应广告工作台展示。未改账号、商城绑定、BD 数据或定时计划。

## 已验证数据

- 租户 1，TK1PH（店铺 23），广告主 7651940663654678546，YX-菲律宾-本土1号店。
- 业务日 2026-10-30，Asia/Manila，USD。
- 官方 GMV Max API 完整分页 18 个计划：消耗 71.02，报表收入 489.61，报表订单 54。
- SharedAdvertisingRawPayload 快照 1；审计 1096206。数据库回读与 API 汇总一致。
- 这是独立已验证原始快照，不写 BASIC 竞价日消耗，不刷新商城、BD 或财务报表。尚未与广告后台人工截图对账。

## 必须纳入后续发布的源码

- backend/apps/integrations/gmv_max_sync.py
- backend/apps/integrations/management/commands/sync_tiktok_gmv_max_day.py
- backend/apps/integrations/gmv_max_read.py
- backend/apps/reports/tiktok_ads_services.py
- frontend/src/components/TikTokAdsDailySpendOverview.vue
- backend/tests/test_gmv_max_day.py
- backend/tests/test_tiktok_daily_spend_report.py

复用既有凭据托管、权限、审批及租约；官方直连只读 API；不增加数据库迁移。查询页面仅读数据库，不重新采集。重复快照按最新身份、日期、币种、时区展示，不累加版本。

## 部署记录

- 采集文件目录：/opt/saas-collab/production/hotfix-tk-gmv-day-20261031/
- 展示补丁、备份及 receipt.json：/opt/saas-collab/production/hotfix-tk-gmv-view-20261031/
- 前端新入口 index-b33dd7df2f83.js；广告块 AdvertisingOverview-167f811cd8d1.js。
- 后端读取服务 SHA256 b18e79ad457da4d13529b8b6571557791ea77e7a88aab6659d45c300c1a224cd。
- 仅对当前生产广告生成块做有原文件哈希保护的增量修改，没有覆盖整套前端；Gunicorn HUP 重载，没有重启任务进程。
- 本次 44 项测试通过，Django check 通过，生成 JS 语法通过，生产只读回读返回两个广告户名称及上述快照。

## 管理员发布注意

直接修改容器内文件会被重新创建容器覆盖。下一次版本同步必须先合并上述源文件及测试，再正常构建，不要只合并 PR 而遗漏这些直接部署文件。先比对线上其他热修，禁止整套旧代码覆盖。账户名称此前独立热修另见 TK-Ads-account-name-20261031.md。

回滚展示时还原 before/tiktok_ads_services.py 和 before/index.html，并重载 Web worker；旧 JS 保留。不要删除快照、审计或业务记录。采集命令仅按显式指定的单日执行；本次未创建或开启定时任务。

页面验收：广告工作台 → TikTok 已存竞价消耗，日期选 2026-10-30。上方账户列表显示广告户名称，下方独立 GMV Max 区展示该日结果。未做真实浏览器视觉验收；人工广告后台金额核对仍待完成。
