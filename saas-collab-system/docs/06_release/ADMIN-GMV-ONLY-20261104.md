# 阿里云 TikTok 广告 GMV Max 展示修复（2026-11-04）

## 范围与原因

用户要求广告投放分析只展示 GMV Max，不再使用 BASIC 竞价零消耗作为店铺广告表现。本次保留 BASIC 历史数据及旧 API 默认契约，不删除数据、不停用其他采集任务、不改账号权限。

## 修改

- 广告报表增加 `report_type=gmv_max` 分支，在 BASIC 查询之前返回，仅读取已有 GMV Max 快照。
- 前端广告总览/投放分析组件明确请求 GMV Max，默认按店铺汇总，可查看广告主明细；不同币种、时区和平台店铺身份不混算。
- 汇总 ROI 按收入合计/消耗合计计算，不平均每日 ROI；缺失不作为零。
- 保留历史绑定证据与当前采集资格的区分，不借展示历史数据放开采集校验。
- 审计查询只读取需要的列；超时显示缩小日期或选择店铺的提示。
- 没有计划级表现时明确提示，不用账户日消耗伪造计划、商品或视频指标。

## 已部署与验证

服务器：阿里云 production，后端 production-backend-1，前端 production-frontend-1。

热修目录：`/opt/saas-collab/production/hotfix-gmv-only-20261104/`。
`receipt.json` 记录修改前后哈希，成功执行的 `backup-<UTC时间>` 保存原文件。第一次因容器没有 kill 命令回滚；改用 Python 发送 Gunicorn HUP 后成功应用。

后端替换文件：

- apps/integrations/gmv_max_overview.py
- apps/integrations/gmv_max_read.py
- apps/reports/tiktok_ads_services.py
- apps/reports/tiktok_ads_views.py

前端热修新增 `TikTokGmvOnly-20261104.js`、`MarketingAdvertising-GmvOnly20261104.js`，更新现有入口的广告模块引用；未替换完整站点或登录模块。

验证结果：

- 前端针对性测试 10 项通过；后端纯汇总测试 7 项通过。
- 生产数据库只读事务，租户1 root 权限下调用正式视图：2026-10-28 至 2026-11-03，HTTP 200，scope=GMVMax，102 条日记录，92 条正消耗，15 个店铺汇总组，本次耗时 0.302 秒。
- 返回仍含 collection_disabled / local_evidence_unverified 警告，不代表所有映射具备采集资格。
- 登录页及两个新前端资源 HTTP 200。未完成登录后的浏览器交互验收；单次视图耗时不代表网络端到端延迟。
- 没有触发重新拉数、令牌兑换、数据库迁移、数据写入或修改定时任务。

## 管理员同步注意

本次是容器内定点热修，重建容器会覆盖。必须合入本 PR 的后端及 Vue 源码后构建正式镜像，不要仅同步部署脚本或覆盖当前容器。前端源码为 `frontend/src/components/TikTokAdsDailySpendOverview.vue`。

`deploy/gmv_only_20261104.py` 是绑定本次资产哈希的一次性脚本，不能用于其他版本。`deploy/ads_shop_summary_20261103.py` 为先前方案存档，不要在当前环境运行。

回滚时先对照 receipt 核实线上仍为本次 after 哈希；从对应 backup 恢复四个后端文件及入口 JS，随后仅对后端 Gunicorn 做优雅 HUP。若有后续改动，先人工比对，不覆盖。

正式镜像验收：广告页面只发送 report_type=gmv_max；BASIC 区域不可见；店铺汇总和日明细金额一致；缺失、零消耗、币种隔离及无计划明细提示正确；其他采集任务不受影响。

页面： https://xtsy.dingfengchuangyu.com/marketing/advertising/tiktok/performance
