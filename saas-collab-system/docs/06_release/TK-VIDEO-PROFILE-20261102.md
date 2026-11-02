# 阿里云 TK 视频及达人档案交接（2026-11-02）

## 当日交接补充（后续状态优先）

全部当日阿里云改动总清单见[PR454管理员总交接](https://github.com/dfcy-team/dfcy/blob/fix/tk-advertising-gmv-display-20261102/saas-collab-system/docs/06_release/ADMIN-ALIYUN-ALL-CHANGES-20261102.md)。今晚应同时纳入PR454与PR456，不只同步视频文件。

后续v37/v38已审批生效；下文“达人审批仍关闭”是早期验收时点，不是当前状态。商城续期worker兼容修复及9店续期结果见TK-CREDENTIAL-WORKER-20261102.md。

交接只读检查发现 `saas-tk-video-resume-20261102-2.service` 于2026-11-02 15:37:13 CST退出137，状态failed。尾部店铺13、10月20日批次405完成1267行并回读验证，但不能据此认定全店补齐。137原因尚未确诊，不直接断言OOM。原20:00 nightly timer仍active/waiting；本轮没有调度、重试或重启。

## 范围与线上修改

仅视频采集、可信视频关联、达人档案展示；未修改广告、账号、商城授权或财务。无数据库迁移。

- `tiktok_video_sync.py`：API finish_rate/v_to_l_rate 超过 1 时，仅隔离该指标，保留原始证据，标记 degraded，不再使整个店铺日失败。不擅自除以 100；未知值不覆盖已知值。负数、非有限值等仍拒绝。优先判断平台最新可用日期，缺失列表不能算零数据。
- `video_registered_reconcile.py` 与命令 `reconcile_registered_tiktok_videos`：同租户、同店铺、精确视频 ID 与既有登记达人账号共同核对后关联。保留人工档案，仅在 historical_performance.api_video_observations 增加逐店视频数量和日期覆盖；操作有审计。
- 达人档案详情增加“API 视频关联（已核对）”。不是粉丝资料更新，也不代表送样完成。
- 履约仅复用既有状态服务，必须已有可信送样关联、发布时间、同商品与唯一送样证据。未猜测 OpenID 与数字达人 ID 的关系，未把无时区时间强行转换，未覆盖历史任务。

## 本次已验证结果

- 22 项隔离测试通过（无生产数据库和网络）；Vue 模板编译及部署 JS 语法检查通过。关联业务的数据库集成测试仍需补充，不将单元测试称为完整验收。
- TK1PH 店铺23，2026-10-25，批次38：6页、291行正式入库，database_verified=true；1行异常比例隔离。PHP reported_gmv=16860.46，attributed_gmv=21946.83，两种口径不得混用。
- TK1PH 关联实际执行：linked=341，profiles_updated=240，identity_conflict=83，no_unique_registered_video=210，sample_or_publication_missing=341。送样状态更新0。
- 达人真实查询审批仍关闭，未绕过审批。官方达人粉丝、地区等资料尚未补拉。

## 补齐任务与未完成项

已启动 `saas-tk-video-repair-20261102.service`，调用原串行 runner 的 `--initial`：仅当前有效授权店铺、最近30个完整本地自然日、成功日跳过；复用 worker.lock 与 runtime-manifest 检查，不刷新 Token、不改变权限。

启动不等于完成。以 journalctl、TikTokVideoSyncBatch、Evidence 和正式日指标回读为准。2026-11-02的滚动范围为10月3日至11月1日；10月1日至2日旧历史缺口不在此次范围内，不得宣称10月全量完成。未授权/过期/审批不足店铺仍阻塞。

全店达人关联尚未执行；已验证展示和实际写入仅 TK1PH。送样匹配证据不足仍保留原状态。后续须补齐可信发布时间与送样关联，不能直接把所有视频归为履约完成。

## 部署证据与管理员同步注意

服务器目录：`/opt/saas-collab/production/hotfix-video-profile-20261102/`。
保存 `video.before.py`、`manifest.before.json`、`frontend.before.js`、`frontend.after.js` 和部署 receipt。部署脚本为本目录同级 `deploy_video_profile_20261102.py`，有旧哈希校验；不能对已变更代码盲目重跑。

本次直接更新 production-backend-1 的三个视频 Python 文件，以及 production-frontend-1 中现有 `InfluencerList-BbjPKNMM.js` 单一文件。未重启服务。已同步更新旧视频 runtime-manifest 对应源文件哈希，未取消版本保护。

管理员必须合并本 PR 后重建持久镜像，不能仅重建旧镜像覆盖容器热修。前端正式构建应从 Vue 源码生成新哈希资源；现场临时单文件替换可能需要强制刷新。未进行登录态页面端到端验证。

更换部署版本前核对现行 hotfix 和其他任务改动；不得以本分支全量覆盖生产已有广告等更新。回退仅针对本次文件，并协调 runtime-manifest；不得删除已导入事实或撤销审计。平台已知指标不因回退擦除。
