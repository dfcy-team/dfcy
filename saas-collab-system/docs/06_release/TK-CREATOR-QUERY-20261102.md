# TK 达人查询清单拆分与审批交接

更新：v37已审批，后续v38已生效并单独开放18店商城自动续期。旧worker解析不兼容已在2026-11-02修复，见 TK-CREDENTIAL-WORKER-20261102.md；下文待审批描述为首次交付时状态。

2026-11-02 阿里云生产补丁。仅两个后端文件，不包含能力矩阵前端开关或批量达人资料回填。

## 改动

- production_settings.py 新增 creator_query_bindings，沿用精确租户、店铺代码、地区、真实店铺ID、连接配置ID校验。
- tiktok_creator_lookup.py 的列表与查询均只读取新清单，无 auto_refresh_bindings 回退。
- 令牌续期模块、账号权限、广告及同步任务不变。未调用平台达人API，未刷新Token。
- 6项无网络隔离测试通过；覆盖两清单隔离、无旧清单回退、缺身份/重复/非法租户拒绝。尚未完成真实平台查询验收。

## 已提交待审批

版本 v37，记录ID40，创建人ID1（root），基于当前生效v36创建。
包含租户1的18家 active商城授权记录，scope为 seller.creator_marketplace.read。
仅改 creator_query_bindings、affiliate_seller_creator_read_approved、affiliate_seller_creator_scope。提交前逐字段检查其余配置完全未变。
当前仍为 pending_approval，未代审批。须另一位有审批权限的管理员批准v37，不能审批旧v34替代。
部分记录令牌已到期；审批不会自动续期，查询仍会校验有效期、数据范围、真实身份与平台权限。

## 部署

备份/部署源：/opt/saas-collab/production/hotfix-creator-query-20261102/。
通过旧SHA校验再复制两个文件，逐字节回读；Gunicorn SIGHUP平滑加载，未重启容器。公网健康HTTP200。
合并源码后重建持久镜像，避免下次覆盖热修。其他长期进程若使用达人入口，也应在正式发布时加载新镜像；本次没有重启其他工作进程。

## 注意

生产配置页面尚无独立清单编辑控件。请直接审批既有v37，不重新提交整份页面配置，以免旧前端丢弃新字段。后续需补齐可视化管理与保留字段测试。
本次查询仅保存官方快照；不把审批通过当作成功入库，不用昵称推断达人ID，不自动覆盖人工档案。
回退时须先使达人查询失效，不能将仍有效的新审批配合旧代码恢复到令牌刷新清单。
