# 阿里云广告按店铺汇总交接（2026-11-03）

## 已部署范围

- 入口：`https://xtsy.dingfengchuangyu.com/analytics/advertising-overview`。
- GMV Max 默认按店铺汇总，可切换广告户视图、展开广告户每日明细。
- 不新增主投/辅助配置。原始快照、广告户 ID、来源和现有绑定均保留。
- 不同平台店铺身份、币种、报表时区分别汇总；BASIC 与 GMV Max 分开。
- 金额用 Decimal；ROI、平均订单成本按合计重新计算，不平均各广告户比例。
- 广告订单及收入是报表口径相加，不声称为跨户去重的商城订单或 GMV。
- 缺失广告户日不补零；重复日冲突不展示金额。同币种/时区的缺失已映射账户计入覆盖分母。

## 绑定边界

新增 `historical_binding_confirmed` 仅用于历史汇总。检查同租户查询范围内、同店铺、配置、Token 的已绑定会话、绑定结果和已验证候选信息，不因无关当前配置版本变化删除历史展示。

这不是实时授权有效证明，不修改 `_locally_verified`、同步门禁或存储指纹。原有 `local_evidence_unverified` 警告保留。

无当前店铺历史证据的 4 个换绑映射不计入店铺汇总，明细不删除：TK6PH 三个、TKKJ3PH 一个。此次未修复、启用或迁移它们。

## 实测

- 本地 7 个纯函数测试通过（系统 Python 无 pytest，使用 runpy 逐个执行全部 test_ 函数）。
- 非 mock 前端完整构建通过；新组件 JS 语法及线上依赖导出校验通过。
- 生产 Django 只读事务回读 TK1PH：2026-10-26 至 2026-11-01，USD/Asia-Manila，7/7 广告户日，363.16 消耗、2418.25 报表收入、295 订单、ROI 6.66、单均 1.23。
- 全可见范围回读：1 个汇总分组；4 个无当前店铺历史证据映射排除，TK6PH 分组为 0。
- 登录页 HTTP 200；未完成真实登录后的浏览器交互验收。生产真实多广告户合计暂无样本，合计逻辑由合成测试验证。

## 生产落盘及版本同步注意

备份、部署脚本、回执目录：`/opt/saas-collab/production/hotfix-ads-shop-summary-20261103/`。

仅替换以下文件：

| 容器 | 文件 | 部署 SHA256 |
| --- | --- | --- |
| production-backend-1 | /app/apps/integrations/gmv_max_overview.py | 7402feb43bd958b126c9b977f976bbffde4b6ec4378e245102b75776492b3990 |
| production-backend-1 | /app/apps/reports/tiktok_ads_services.py | 715879fb00c55c5957a9ae8c98674114e214685fc320a24ebdbcb708581c27e7 |
| production-frontend-1 | /usr/share/nginx/html/assets/AdvertisingOverview-088lMSCV.js | 4378f25792e3f53c3ab40e34c8b96cf489042f7d48093b904824f7cffe06782d |

前端只替换 TK 组件，保留线上广告父页面的后续修改、共享依赖、入口和 CSS；后台通过 Gunicorn HUP 平滑重载，没有重启容器。既有采集 Python 进程保留。

没有数据库迁移、数据写入、重新采集、权限调整、账号变更、Token 刷新、读取开关或定时任务变更。

管理员同步版本时合并本次 Vue 源码及两个 Python 文件，不要用本地旧版整个前端目录覆盖线上其他改动。部署脚本只适用于此次已核对哈希的版本，不能当通用脚本重复运行。容器重建会覆盖热修，必须先将源代码纳入正式镜像。

## 回滚

核对目标文件仍为以上哈希后，从同目录 `before-helper.py`、`before-service.py`、`before.js` 分别恢复三个文件，再平滑重载 Gunicorn。存在后续修改时停止直接覆盖，先比较差异。无需数据库回滚。
