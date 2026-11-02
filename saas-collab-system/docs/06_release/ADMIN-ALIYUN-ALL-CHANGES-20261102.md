# 管理员交接：2026-11-02 阿里云全部本对话改动

## 今晚同步入口

- 广告代码与本总交接：[PR #454](https://github.com/dfcy-team/dfcy/pull/454)，代码核对基线 efa89d5b。
- 视频、达人及商城续期配置兼容：[PR #456](https://github.com/dfcy-team/dfcy/pull/456)，代码核对基线 b0e66ed7。
- 两个PR均已提交，交接时仍为OPEN，不代表已合并。必须一起纳入发布候选；不是把任一分支整套覆盖生产。
- 本文覆盖本对话今天六处生产热修、数据操作、审批配置及调度变更，不仅是PR文件。其他人员同时实施的变更需另核对。
- 本轮交接仅只读检查生产并补充文档，不重新采集、续期、审批或重启。

## 六处现场改动及源码归属

所有目录均位于 `/opt/saas-collab/production/`。

| 现场目录 | 变化 | PR及专项文档 |
| --- | --- | --- |
| hotfix-ads-display-20261102 | GMV Max补导、ROI/平均成本显示、BASIC口径说明；曾热修旧广告chunk | #454，TK-ADS-GMV-DISPLAY-20261102.md |
| hotfix-ads-schedule-20261102 | 最近7个完整自然日的广告同步命令、service/timer | #454，TK-ADS-DAILY-GMV-20261102.md |
| hotfix-ads-overview-20261102 | 按日期/店铺/广告户/币种/时区分组概览，后端Decimal汇总与覆盖检查 | #454，TK-GMV-MAX-HIERARCHY-20261102.md |
| hotfix-video-profile-20261102 | 异常比例单字段隔离、可信登记视频关联、达人档案API观察展示 | #456，TK-VIDEO-PROFILE-20261102.md |
| hotfix-creator-query-20261102 | 达人查询清单与令牌续期清单分离，审批配置 | #456，TK-CREATOR-QUERY-20261102.md |
| hotfix-credential-config-20261102 | credentials worker配置解析兼容，与backend对齐 | #456，TK-CREDENTIAL-WORKER-20261102.md |

部署脚本、测试和源代码已在对应PR，不只提交编译资源。生产备份、回执不能作为可重复直接执行的部署包：脚本带旧哈希保护，正式构建后不要再次套用旧chunk补丁。

## 不在代码diff中的现场状态

### 广告数据与调度

- TK1PH店铺23，广告户7651940663654678546，2026-10-26至11-01：7个唯一日期，363.16 USD、295报表订单、2418.25 USD报表收入。原始快照保留，查询选最新观察，不累加历史快照。
- 区间ROI 6.66、平均下单成本1.23 USD。与包含当天的TikTok截图不是相同日期，不能声称完全对账。
- BASIC与GMV Max分开；缺失不补零，不同币种不相加。今日补导没有修改BASIC事实。
- 首次广告定时批次7成功/7失败：Nova.ph store因 gmv_max_store_not_verified 被拦截，不能用普通广告授权替代店铺归属证据。
- 当前概览读取另有 local_evidence_unverified 提示；不能抹去该提示或将历史数据可读当成当前映射已通过全部检查。
- `saas-tk-gmv-max-daily.timer` 已存在且本轮只读检查为 active/waiting；每天北京时间02:30，Persistent=true。仅同步通过现有核验且读取开启的映射，按各广告户时区取最近7个完整自然日。
- 对应service/timer源文件在#454。不要另建第二套cron或timer，不要因发布重复手动跑一次。

### 达人配置及商城续期

- 当日配置流程：v37开放独立creator_query_bindings；后续v38审批生效，18家TK商城精确绑定纳入续期。审批是数据库配置，不由git合并自动恢复。
- 旧worker不识别新字段，曾回退为空配置。今天只对齐其production_settings.py，确认无运行中续期后正常停止再启动credentials worker。
- 当日16:42回读9家到期店铺已续期至11月9日：TK6PH、TKKJ1PH、TKKJ1TH、TKKJ5PH、TK1PH、TK2PH、TK3PH、TK4PH、TK7PH。其他9家未到提前15分钟窗口，未强制轮换。
- 上述是当日已记录的验收，不是本次重新调用Token接口。广告Token不能套用商城refresh接口，本次未实现广告自动续期。
- 不要从旧前端重新提交整份生产配置，避免丢失creator_query_bindings；不能把达人清单重新并回auto_refresh_bindings。
- 专项文档中的“v37待审批”“达人审批关闭”是较早阶段记录，应以上述后续审批和发布现场实际生效版本为准，不要重新审批旧v34。

### 视频、达人档案与履约

- 当日已记录TK1PH 2026-10-25批次38：291行/6页，database_verified=true，1行异常比例隔离。reported_gmv与attributed_gmv保留不同语义。
- 当日TK1PH可信关联：linked=341，profiles_updated=240，identity_conflict=83，no_unique_registered_video=210，sample_or_publication_missing=341；送样状态更新0。不是全部店铺达人资料完成，也不是有视频即履约完成。
- 原夜间 `saas-tk-video-nightly.timer` 本轮仍为 active/waiting，每天北京时间20:00；不是今天新建的第二套任务。
- **本轮新核对：saas-tk-video-resume-20261102-2.service 已于11月2日15:37:13 CST退出，ExecMainStatus=137，Result=exit-code。不能宣称全店补齐完成。137本身不能证明一定是OOM，原因还需诊断。**
- 尾部日志显示店铺13、10月20日批次405完成1267行且database_verified=true，之前若干日也完成；这只是尾部进度证据，不是全范围计数。本轮没有重新查全库或重跑。
- 发布前先查运行租约/锁和失败原因；不要删除成功批次或强制接管。恢复必须通过已有正式入口，跳过成功日。
- 11月2日滚动30完整自然日为10月3日至11月1日；10月1日至2日旧缺口不在该窗口内。
- 联盟订单8/9/10月正式回补、月末刷新仍不能列为此次已完成项；本PR不补写这些数据。

## 线上源码核对

本轮SSH只读sha256sum与本地PR文件逐字节一致：

| /app下路径 | SHA256 |
| --- | --- |
| apps/integrations/gmv_max_overview.py | 4b163037ce52315731eb3955d96e1da6dad4567080d9996a14f2dd5eded52686 |
| apps/integrations/gmv_max_schedule.py | 25b95d95e4152f076fc1eca8f66a168e5b58419c6a9e60e9b5f0a19deee7c302 |
| apps/integrations/management/commands/sync_tiktok_gmv_max_recent.py | 90472a9ee034388ea48e033b470af435a0122ec48c7b37e1e6c652a7856f297b |
| apps/integrations/production_settings.py | adec2d0ba24198abde958bbad3c0e7a6736e57b0034e38343f06f87beb74e314 |
| apps/influencers/tiktok_creator_lookup.py | a22cb191f0c3134c78a2272748d0a73f45c2834272cde64c5986ea19c0f69908 |
| apps/influencers/tiktok_video_sync.py | 10e41318079460be653da7e25f84336182dbfc57fa61692df38d6fdf63110882 |
| apps/influencers/video_registered_reconcile.py | 032ce02f34cfa73018cfc98d159d39e2e91a6e52aa7d297183d8b1347fc83bd6 |
| apps/influencers/management/commands/reconcile_registered_tiktok_videos.py | 9e21c73f7b8cfea97666a9d32e9e428fe5ad205fbdac37efa629ffc323bffb94 |

backend与credentials worker的production_settings.py均匹配。报表服务及前端编译产物的部署哈希见hotfix-ads-overview-20261102/receipt.json；现场父组件有其他修改，不能用本地旧整文件直接覆盖。

## 今晚管理员发布顺序

1. 记录当前镜像、git基线、入口资源哈希、上述六目录回执、systemd单元、配置生效版本；备份受影响文件。不把密钥、Token、完整回调或生产环境文件提交Git。
2. 将#454和#456源码合并到当前正式发布分支，保留其他团队已上线改动。核对原视频迁移0041/0042/0043、既有GMV正式入口及10月31日热修基线；今日两PR未新增数据库迁移，不能代替此前版本。
3. 运行对应隔离测试、必要权限回归及生产构建。此前记录：广告调度4项、概览4项、前端比率2项；视频22项、清单隔离6项。不是本轮新跑测试，数据库集成/登录态全链路仍需补验。
4. 构建持久backend及credentials worker兼容镜像；frontend必须VITE_USE_MOCK=false。保留唯一Vue挂载入口，不能恢复旧index或引入演示账号。当前单文件容器热修在重建时会丢失，必须带入源码。
5. 与20:00视频和02:30广告任务错开发布，先核对活动任务与锁，正常排空后加载新版本；不得强杀正在写入的任务。更新视频runtime-manifest到实际已验证源文件哈希，不能取消保护。
6. 检查两个现有timer及service依赖仍有效，管理命令help与不带commit预检查通过。保留既有配置、授权、业务记录和审计，不重新建任务或重新兑换授权码。
7. 回归登录、达人列表/档案/送样页面、广告筛选；TK1PH上述7日应回读363.16 USD/295/2418.25 USD。核对worker读取18条精确绑定，失败状态不可美化成成功。
8. 记录正式发布SHA、镜像digest、时间与验收结果。若回退，先核对文件是否有后续改动，仅回退本次范围；新配置字段与解析器必须兼容，不能回退数据库事实或审批历史。

## 页面及未完成边界

页面：https://xtsy.dingfengchuangyu.com/analytics/advertising-overview

目前只有日期区间概览和已存日报；商品/LIVE分类、计划列表、计划详情、商品详情、视频素材花费下钻尚未实现。更改预算、目标ROI、启停广告属于平台写操作，此次没有上线，页面没有“更改计划”入口不是按钮被隐藏。

旧的AdvertisingOverview-DxaI_qd7.js补丁不是当前入口引用资源。最后概览部署针对AdvertisingOverview-088lMSCV.js及其CSS，保留现行父组件和共享依赖；正式构建后不应继续依赖这些固定文件名。

今天全部本对话已实施内容按上表归档；未实现功能、视频未完成补录和其他历史版本不冒充本次已交付。历史总交接另见生产admin-handoff-tk-all-20261031目录及PR #440，发布时一并保护。
