# 单个平台档案删除与全量 ID 盘点

## 追加 Shopee 平台

平台选项新增 Shopee（shopee），支持独立新建、关联新建和列表筛选，仍是一账号一份完整独立档案。平台数字 ID 可后补，不将 Shopee 账号拿去调用 TikTok API，也不自动新增 Shopee 授权。0045_influencer_shopee_platform 只更新平台字段 choices 的迁移状态，不创建业务数据；接在本 PR 的0044后。新增后端2项、前端现有平台表单69项通过，迁移状态检查无漂移。已按下文实际部署回执上线。

## 功能边界

删除的是当前完整档案 ID，不是关联组，更不是这个人的所有平台账号。例：删除独立 Facebook 档案不会删除关联 TikTok 档案。旧式一个主档案下的嵌入平台账号不是独立完整档案，本功能不拆分、不硬删这些子账号。

列表“删除档案”、编辑底部“删除当前平台档案”，二次确认明确展示平台和账号。“只看已删除档案”提供恢复。当前主档案 ID、编号、平台身份、子账号、关联组成员、共享联系方式、黑名单、历史送样/任务/订单、成本及 BD 历史均保留。

删除时设置 is_deleted、deleted_at，并保存原启停状态；档案 status 改 inactive，避免被现有活跃达人选择器选中。默认列表和关联档案切换不展示已删除档案。恢复还原原启停状态，不解除黑名单，不释放/重分配用户名或数字 ID。

删除/恢复使用 DELETE/POST /api/internal/influencers/{id}/archive-deletion/，沿用 influencers.manage 与 tenant/country 数据范围；If-Match 必填。租户锁、目标行锁及版本校验防止覆盖并发编辑，逐次写入 archive_soft_delete/archive_restore 审计。普通编辑、启用、查询资料、新建关联档案及新增业务关联不能绕过已删除状态。后台接口未增加批量删除。

## 数据库与上线

新增 migration 0044_influencer_archive_soft_delete：3 个字段和 2 个检查约束。旧记录全部保持未删除。不删除数据表，不硬删业务记录。需要正式发布时先备份、演练并应用迁移，再启用新后端/前端；所有使用 Influencer 模型的 API 和 worker 要使用兼容版本。

初次提交只完成代码、测试及 PR。用户随后明确要求直接部署；现已按下文回执部署到阿里云，没有执行任何用户档案删除。

## 验证

- 新增删除测试覆盖：单平台/关联组隔离、联系方式保留、任务送样成本逐字段不变、默认隐藏与恢复、原启停状态、保留黑名单、无版本/旧版本、跨租户、缺权限、已删除档案不可编辑/启用/新增关联、元数据只读。
- 临时 SQLite 上执行完整依赖链到 0044 迁移成功；makemigrations --check --dry-run 无漂移。不等同于生产 MySQL 迁移验收。
- 前端覆盖取消、二次确认、仅一个目标 ID、真实 API 与 If-Match、无权限、超时不自动重试、删除筛选与重置。
- 现有平台账号、关联档案、共享联系方式回归通过；完整前端构建通过。
- 后端 216 通过、1 跳过；前端 85 通过。跳过项及 SQLite 结果不能充当生产 MySQL 并发验证。
- 初次提交未做真实登录浏览器验收、真实 MySQL 并发测试或生产迁移；之后的实际部署状态以以下回执为准。

## 2026-11-05 实际部署回执

- 阿里云 https://xtsy.dingfengchuangyu.com/influencers ，不是34。
- /opt/saas-collab/production/hotfix-archive-shopee-20261105/ 保存 plan、源码备份、receipt、迁移日志及数据库备份。备份压缩文件2385202字节，目录0700。
- 检查生产文件原SHA及容器ID后，仅应用4c891fcb、ea2d0fc9的相关源码hunk，保留线上日期筛选和其他热修复。没有用PR旧版整文件覆盖 views.py/services.py。
- 真实MySQL原生迁移执行到0045成功；记录中已有25448个原档案（比早先盘点多一条新建），全部原有字段的前后指纹一致，新 is_deleted 全为False，没有档案被删除。
- 生产 Gunicorn平滑HUP；不重启容器，不改变权限/配置/定时任务。Celery继续使用兼容的旧缓存模型；新增列向后兼容，删除档案保持inactive，数据库约束阻止重新启用。后续正式镜像发布仍应包含本PR全部代码和迁移。
- 前端仅替换当前 index-CFS-lxl7.js 的两个达人组件引用，目标为 InfluencerList-archives-41eab5a57852.js。沿用共享Vue、ElementPlus、授权store和原请求客户端；不替换index.html、广告、日期筛选或整套dist。
- 两个公共JS均HTTPS200且字节哈希匹配部署receipt。新JS SHA256：41eab5a5785212ad9e699b3391d3a182f5a79b8d2ddb9cbaa42c12b2311aaea0；入口after SHA256：8a79b7eebe6a5ca73447fdc73a84e71405542128ad4bfc6ecd6b7748d19bcf58。
- 正式视图在SQL只读事务验证：普通达人列表25448、已删除筛选0、Shopee筛选0（尚未新建Shopee档案）；新删除/恢复路由解析正确。送样2026-11-01到11-04创建日期筛选仍为HTTP200，82条。
- 没有在生产创建测试档案或执行真实删除/恢复。浏览器打开后需要登录，用户选择自己测试；不能将HTTP及后台验证描述为已完成用户视觉验收。旧标签页需强制刷新。
- 回滚必须先确认目标仍匹配receipt且没有新增删除/恢复业务操作，再恢复原源码和入口并HUP；保留新增字段和迁移审计，不自动反向删除列。若后续有用户操作或发布，先停止核对，不覆盖后续变更。

## 后续达人查询批次

用户要求继续查询后，使用已审批关联店铺做低频搜索，不创建后台定时任务。TK3PH的iam_veronica01只读探测成功、精确匹配1个；返回包含creator_open_id而非numeric creator_user_id，探测未写业务数据。

随后冻结752个缺数字ID档案，执行 /tmp/creator-details-batch-20261105-1400/ 这一个有限批次，每次间隔6秒，第一次API失败即停止全批，不换店铺/令牌绕过限流。实际处理5个候选，2次API请求：

- 档案10，eiram.annek：成功更新官方资料，审计370183；数字ID仍为空。
- 3条没有唯一可用关联授权国家，保持原样。
- mommylhaivlogs / TKKJ4PH返回OAUTH_RATE_LIMITED，停止批次。余747条没有继续调用，不能声称已经查询完成。

连同早先14条，目前累计15条资料成功写入（并非新增15个数字ID）。本次断点、写入前字段和结果已复制到宿主机 /opt/saas-collab/production/creator-details-batch-20261105-1400/ 。继续时先核对结果和限流解除情况；禁止直接重放整个apply，禁止将OpenID写到数字字段。

## 全部达人 ID 盘点（阿里云只读快照）

已扫描当前 tenant=1 全部 25447 档案，不是只看本页：

| 平台 | 总档案 | 数字格式成立 | 缺数字 ID | 非数字格式 | 缺用户名 |
|---|---:|---:|---:|---:|---:|
| TikTok | 25444 | 24677 | 751 | 16 | 142 |
| Facebook | 3 | 0 | 3 | 0 | 0 |

“数字格式成立”仅语法检查，不表示已经全部通过 API 核实。非数字格式也不一定无效：可能属于 opaque/open ID，需要先核对字段语义，不应擅自清空。另有 1 组非空外部 ID 被 2 个档案共用，需要结合身份组人工核验，不能仅凭同 ID 合并。

缺失/格式差异/重复明细保存在宿主机受限目录 /opt/saas-collab/production/creator-id-inventory-20261105/{summary,issues,duplicates}.json。不含凭据。脚本 deploy/audit_creator_ids_20261105.py 只做 SQL 只读查询，不调用外部 API、不写业务数据。

## API 查询尚未完成的范围

### 2026-11-05 达人列表 404 修复

原因是部署用前端 overlay 的压缩模块导出映射错误，列表函数误绑定为黑名单操作函数。已按线上模块实际 HTTP 方法和 URL 修正全部映射，新增 `frontend/verify-archive-overlay-api.mjs`，以捕获的线上模块执行录制传输验证，不发送网络或业务写入。

12个方法/地址契约、2个标签映射和6项删除功能前端测试通过。仅替换达人组件和入口内该组件的两处引用，不修改业务数据；线上公开资源哈希验证通过，正式后端授权列表视图返回200。尚未进行用户登录浏览器验收。部署回执：`/opt/saas-collab/production/hotfix-archive-api-20261105/receipt.json`；组件为 `InfluencerList-archives-ac5a19e1cf59.js`。可恢复该目录的 `entry-before.js` 回退本次前端修复。按用户最新要求，本次不代建PR，不创建版本号。

此前14条已通过 TikTok Creator Marketplace 精确用户名查询补齐 handle、官方昵称和粉丝数，不代表补齐数字 ID；现有返回不提供可信 numeric creator_user_id。缺数字 ID的751条包含其中部分已补用户名档案。不得伪造或将 opaque ID写进数字字段。

已捕获 OAUTH_RATE_LIMITED。当前批次没有继续高频扫全部25444条、绕过限流或跨店反复重试；没有创建定时任务。剩余 API 核验应待平台允许后按配额分批进行。Facebook 需其自身 Graph API/App/账号授权，不能用 TikTok 接口补全。

权限开通位置（实际缺权限时才处理）：TikTok Shop Partner Center 应用 API 权限 Read Creator Marketplace / seller.creator_marketplace.read，审批后需要受影响店铺重新授权；系统侧仍需审批并配置 creator_query_bindings。当前成功查询店铺已有该 scope，已明确限流不是缺权限，不要为了限流新建应用或重复授权。
