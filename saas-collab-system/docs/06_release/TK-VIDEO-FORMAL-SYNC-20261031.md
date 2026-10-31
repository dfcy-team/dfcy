# TK 视频正式入库与夜间同步交接

版本标识：TK-VIDEO-20261031.2。部署日期：2026-10-31。

## 当前结论

- 已直接部署阿里云生产后端的视频限定热修复，已执行 influencers 0041、0042、0043 迁移。
- TK1PH（租户1、店铺23）2026-10-30 已完成真实 API 正式入库及数据库逐行回读，批次1；重复执行跳过，无重复新增。
- 全店首次补录已启动，范围为执行时18家有效授权 TikTok 商城店铺，2026-10-01 至 2026-10-30，按各店业务时区划日。本文发布时仍在运行，不能当作全量验收完成。
- 交接前最后只读快照：26个店铺日completed，2416条正式日指标；9个旧进程invalid_video_rate失败日期等待修正版续跑，1个店铺日running。此为动态进度，不是最终结果。
- 夜间独立视频任务已启用：北京时间每天20:00，最近30个完整自然日，不含当天。不是旧自动跟进的02:00时间。
- 本次没有修改商城/广告授权、账号权限、广告报表、商品同步、联盟订单、建联或送样记录，没有重启后台/前端/其他同步服务。
- 本次履约自动更新为0。未证实的达人 Open ID 对应关系及视频发布时间时区，不用于自动完成送样任务。

## TK1PH 真实验收

| 项目 | API | 正式库回读 |
| --- | ---: | ---: |
| 视频日指标条数 | 288（6页） | 288 |
| reported_gmv / PHP | 13995.71 | 13995.7100 |
| attributed_gmv / PHP | 17185.49 | 17185.4900 |
| views | 18569 | 18569 |
| sku_orders | 33 | 33 |

其他证据：281条视频-商品关联；6页原始证据和1条提交对账证据；批次1 completed、attempt_count=1。重复执行结果 already_completed，未重复访问视频分页接口。上述金额不能当作佣金或广告 GMV 使用。

原API的 orders 未返回，保留 NULL，不用 sku_orders 冒充。原发布时间是无时区字符串，保留在原始证据中，正式 published_at 暂为 NULL。creator_open_id 单独保存，不冒充达人数字ID。

真实数据发现某视频 product_clicks=1、sku_orders=2、ctor=2.0000。新增 reported_ctor 原样存储；不除以100、不截断到1、不填入原0到1概率字段 click_to_order_rate。

全店初跑又发现CTR=2或3：API确实返回1次播放、2或3次点击，属于原生比率，不应限为概率。0043仅移除ctr的错误上限，仍校验非负和字段精度；完播率等其余边界未放开。TK6PH 2026-10-19原失败批次13已用新代码成功补录58条并回读对账。未中断旧执行进程，因此它仍可能记录旧invalid_video_rate；已安排串行续跑补齐，不算已全部修复完成。

## API 与表

官方直连 GET /analytics/202605/shop_videos/performance，复用 SaaS 商城凭据托管、签名、店铺身份核验和现有网络审批；不经 dfcy 中转，不刷新外部托管 Token。

- TikTokShopVideo：租户、店铺、视频身份和作者公开信息。
- TikTokVideoProduct：视频与平台商品关联，不自动创建错误的内部SKU关联。
- TikTokVideoDailyMetric：视频按店铺当地日期、币种保存指标；未知为NULL。
- TikTokVideoSyncBatch：逐店逐日运行状态、租约、重试次数及完成计数。
- TikTokVideoSyncEvidence：原始分页和提交前后差异、摘要哈希、回读结果。

Stage 批次1的326条历史观察没有被假冒为本次正式数据。正式数据来自重新调用上述API。

## 同步规则

- 仅租户1，平台tiktok，当前有效授权和启用店铺；逐店再次检查权限、真实店铺绑定、analytics scope、币种、时区和现有审批。
- 每店串行、逐日分页，每日之间暂停2秒；完整分页和total_count一致后才提交当日事实。
- 系统文件锁防止全店任务重叠；数据库每日租约防止同店同日并发。
- 唯一身份：租户+店铺+视频；日指标：租户+视频+日期。重新同步保留主键，新可靠值可修正降低或明确0，NULL不擦除已知。
- API丢失此前已入库行、币种/身份冲突、分页不全、授权变化或租约丢失会阻止当日正式提交。失败后停止该店后续日期，其他店继续。
- 无平台写操作；无广告API调用；无达人/建联/送样状态自动变更。
- 原始视频数可能包括长期未发布新内容的视频，属于当天API返回范围，不等同于当天发布数。

## 直接部署的文件

后端容器 production-backend-1，工作目录 /app：

1. apps/influencers/models.py：只替换 TikTokVideoDailyMetric 类并追加 TikTokVideoSyncEvidence 类，保留其余生产内容。
2. apps/influencers/tiktok_video_sync.py：新增正式采集与对账服务。
3. apps/influencers/management/commands/sync_tiktok_shop_videos.py：新增独立视频执行入口。
4. apps/influencers/migrations/0041_video_nullable_metrics_and_receipts.py：19个既有指标可空、原始GMV/SKU订单及证据表。
5. apps/influencers/migrations/0042_video_reported_ctor.py：原始CTOR字段。
6. apps/influencers/migrations/0043_video_native_click_ratio.py：保留可超过1的API原始CTR。

服务器热修复目录：/opt/saas-collab/production/hotfix-tk-video-sync-20261031/。

包含生产前备份 before/models.py、空视频表备份 data-before.json、补丁源码、部署脚本、receipt.json 和 runtime-manifest.json。后者包含实际运行文件SHA256。models-patched.py是合并生产现状后的快照；不要用本地完整models.py覆盖生产。

运行模型SHA256：291cf4c59d5e73d4bf440772ec26245c92775f3bb2bef8d5f268886886549521。

同步服务SHA256：fa10780c637964b10be47b2f6f52de5797207b2bab2276c45350a53fef64466a。

## 调度与查看

此版本使用独立视频管理命令和systemd任务，未修改通用SyncJob资源枚举、能力矩阵或前端。不要因通用同步任务页没有VIDEO条目就重复创建任务。

```sh
# 首次全店补录状态及逐日安全结果
systemctl status saas-tk-video-backfill-20261031.service --no-pager
journalctl -u saas-tk-video-backfill-20261031.service -n 50 --no-pager

# CTR修复后续跑，先等待首次任务文件锁释放，不会并发提交
systemctl status saas-tk-video-resume-20261031.service --no-pager
journalctl -u saas-tk-video-resume-20261031.service -n 50 --no-pager

# 每晚20:00调度及后续运行
systemctl list-timers saas-tk-video-nightly.timer --no-pager
journalctl -u saas-tk-video-nightly.service -n 50 --no-pager
```

服务文件：/etc/systemd/system/saas-tk-video-nightly.service、saas-tk-video-nightly.timer。

执行包装：热修复目录/run_tk_video_nightly_20261031.py。首次运行跳过已有成功日；夜间使用--refresh更新最近30天已观察事实。若初次任务仍占锁，夜间任务不重复启动。旧Codex tk-30自动化已改成只读跟进，不再提交同步。

绑定有效不等于Token永久有效。授权过期或审批不满足时会记录blocked，不偷偷续期其他系统的凭据。

## 后续同步版本必须注意

这是容器内限定热修复，不是已合并PR或已发布新镜像。普通容器restart保留可写层，但容器recreate/镜像升级会丢失热修复。必须先把上述限定模型块、两个新模块、两项迁移合入正式版本，再重建镜像。

本地参考仓库基线435c29841191de7b2dd5351c30389281856d2141 / V2.44.330；本地还有别的未提交改动，禁止整目录覆盖生产。

新版本发布前检查迁移编号是否冲突，保持已执行0041/0042/0043历史一致。不要把已经执行的迁移文件原地改成别的业务迁移。

执行包装每次校验runtime-manifest.json。后续版本文件变化会停止本视频任务，避免静默使用缺失/未经核对的实现。管理员合并并验证后再更新清单，不能只修改哈希掩盖代码缺失。

迁移之前视频正式表为空；后续已有业务事实，禁止用空备份恢复覆盖，也不要倒退迁移删除数据。回退先停视频timer、确认正在运行的批次状态，保留新增表字段和证据，再安排兼容代码回退。不要重启全体服务或删除业务记录。

## 验证与尚未验收

- 本地独立SQLite测试：视频同步与既有dataset合计61 passed。
- 带完整迁移的早期视频测试16 passed（含0041）；0042/0043已在生产执行成功，最终makemigrations --check无差异。
- 生产check无错误；MySQL已有其他模块条件唯一约束警告未修改。
- TK1PH单日真实API、正式分表、金额计数回读和重复跳过已验收。
- 全店30天批次仍在跑，以逐日completed与提交证据为准，不宣称全部完成。
- 达人OpenID映射、发布时间时区和自动履约仍未验收，保持不更新；本次没有新增视频展示前端。

管理员最终验收请记录每店完成/失败/阻塞日期、正式日指标数、同币种金额及错误原因。严禁将不同币种直接加总、将未知指标当0、将排队/正在运行当成功。
