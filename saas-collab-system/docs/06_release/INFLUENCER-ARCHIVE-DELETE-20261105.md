# 单个平台档案删除与全量 ID 盘点

## 追加 Shopee 平台

平台选项新增 Shopee（shopee），支持独立新建、关联新建和列表筛选，仍是一账号一份完整独立档案。平台数字 ID 可后补，不将 Shopee 账号拿去调用 TikTok API，也不自动新增 Shopee 授权。0045_influencer_shopee_platform 只更新平台字段 choices 的迁移状态，不创建业务数据；接在本 PR 的0044后。新增后端2项、前端现有平台表单69项通过，迁移状态检查无漂移。此追加项同样尚未部署。

## 功能边界

删除的是当前完整档案 ID，不是关联组，更不是这个人的所有平台账号。例：删除独立 Facebook 档案不会删除关联 TikTok 档案。旧式一个主档案下的嵌入平台账号不是独立完整档案，本功能不拆分、不硬删这些子账号。

列表“删除档案”、编辑底部“删除当前平台档案”，二次确认明确展示平台和账号。“只看已删除档案”提供恢复。当前主档案 ID、编号、平台身份、子账号、关联组成员、共享联系方式、黑名单、历史送样/任务/订单、成本及 BD 历史均保留。

删除时设置 is_deleted、deleted_at，并保存原启停状态；档案 status 改 inactive，避免被现有活跃达人选择器选中。默认列表和关联档案切换不展示已删除档案。恢复还原原启停状态，不解除黑名单，不释放/重分配用户名或数字 ID。

删除/恢复使用 DELETE/POST /api/internal/influencers/{id}/archive-deletion/，沿用 influencers.manage 与 tenant/country 数据范围；If-Match 必填。租户锁、目标行锁及版本校验防止覆盖并发编辑，逐次写入 archive_soft_delete/archive_restore 审计。普通编辑、启用、查询资料、新建关联档案及新增业务关联不能绕过已删除状态。后台接口未增加批量删除。

## 数据库与上线

新增 migration 0044_influencer_archive_soft_delete：3 个字段和 2 个检查约束。旧记录全部保持未删除。不删除数据表，不硬删业务记录。需要正式发布时先备份、演练并应用迁移，再启用新后端/前端；所有使用 Influencer 模型的 API 和 worker 要使用兼容版本。

本次仅完成代码、测试及 PR；没有把删除功能部署到阿里云，也没有执行任何用户档案删除。不得将数据库盘点成功当成此按钮已经上线。

## 验证

- 新增删除测试覆盖：单平台/关联组隔离、联系方式保留、任务送样成本逐字段不变、默认隐藏与恢复、原启停状态、保留黑名单、无版本/旧版本、跨租户、缺权限、已删除档案不可编辑/启用/新增关联、元数据只读。
- 临时 SQLite 上执行完整依赖链到 0044 迁移成功；makemigrations --check --dry-run 无漂移。不等同于生产 MySQL 迁移验收。
- 前端覆盖取消、二次确认、仅一个目标 ID、真实 API 与 If-Match、无权限、超时不自动重试、删除筛选与重置。
- 现有平台账号、关联档案、共享联系方式回归通过；完整前端构建通过。
- 后端 216 通过、1 跳过；前端 85 通过。跳过项及 SQLite 结果不能充当生产 MySQL 并发验证。
- 未做真实登录浏览器验收、真实 MySQL 并发测试或生产迁移。

## 全部达人 ID 盘点（阿里云只读快照）

已扫描当前 tenant=1 全部 25447 档案，不是只看本页：

| 平台 | 总档案 | 数字格式成立 | 缺数字 ID | 非数字格式 | 缺用户名 |
|---|---:|---:|---:|---:|---:|
| TikTok | 25444 | 24677 | 751 | 16 | 142 |
| Facebook | 3 | 0 | 3 | 0 | 0 |

“数字格式成立”仅语法检查，不表示已经全部通过 API 核实。非数字格式也不一定无效：可能属于 opaque/open ID，需要先核对字段语义，不应擅自清空。另有 1 组非空外部 ID 被 2 个档案共用，需要结合身份组人工核验，不能仅凭同 ID 合并。

缺失/格式差异/重复明细保存在宿主机受限目录 /opt/saas-collab/production/creator-id-inventory-20261105/{summary,issues,duplicates}.json。不含凭据。脚本 deploy/audit_creator_ids_20261105.py 只做 SQL 只读查询，不调用外部 API、不写业务数据。

## API 查询尚未完成的范围

此前14条已通过 TikTok Creator Marketplace 精确用户名查询补齐 handle、官方昵称和粉丝数，不代表补齐数字 ID；现有返回不提供可信 numeric creator_user_id。缺数字 ID的751条包含其中部分已补用户名档案。不得伪造或将 opaque ID写进数字字段。

已捕获 OAUTH_RATE_LIMITED。当前批次没有继续高频扫全部25444条、绕过限流或跨店反复重试；没有创建定时任务。剩余 API 核验应待平台允许后按配额分批进行。Facebook 需其自身 Graph API/App/账号授权，不能用 TikTok 接口补全。

权限开通位置（实际缺权限时才处理）：TikTok Shop Partner Center 应用 API 权限 Read Creator Marketplace / seller.creator_marketplace.read，审批后需要受影响店铺重新授权；系统侧仍需审批并配置 creator_query_bindings。当前成功查询店铺已有该 scope，已明确限流不是缺权限，不要为了限流新建应用或重复授权。
