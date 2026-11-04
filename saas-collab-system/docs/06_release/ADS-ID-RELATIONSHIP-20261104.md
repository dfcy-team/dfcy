# 阿里云 GMV Max 店铺 ID 关联核验

## 已部署范围

保留 GMV Max 专用页面，只读官方接口确认关系，不根据时区、国家或广告户名称猜测店铺。

- GET `/open_api/v1.3/gmv_max/store/list/`：按广告户读取可访问店铺，精确匹配 Shop 授权的 `platform_store_id`。
- GET `/open_api/v1.3/gmv_max/exclusive_authorization/get/`：传入广告户 ID、店铺 ID、平台明确返回的 `store_authorized_bc_id`，核对响应中的两个 ID。
- 实测当前户返回 `EFFECTIVE`，对应店铺列表的专属主户；非当前户返回 `UNAUTHORIZED`，且店铺列表明确指出另一个主户。冲突、缺参数、未知状态不推断成功。
- 调用前及提交前沿用权限、租户、审批、凭据、Shop 授权、租约门禁。只追加现有不可变审计，不修改映射、不恢复账号、不兑换新授权。
- 当前观测保存真实核验时间，24小时后、映射/配置改变或有效 Shop 身份改变后不再显示为新鲜核验；它不是历史生效起点。

官方接口说明：<https://github.com/tiktok/tiktok-business-api-sdk/blob/main/python_sdk/docs/StoreApi.md>

## 历史和覆盖率

- 原日报保留广告户、平台店铺 ID、日期及原币种；本次不改金额、订单或历史归属。
- 新读取逻辑核对原始快照中的店铺列表证据、专属广告户及店铺限定报表范围；缺少证据的历史快照不伪装成关联已核验。
- 后端返回 `api_coverage`，前端不再仅因某账户没有日报就自行排除或宣称关系已确认。
- 已证明的不同历史投放户按各自报表日期保留。当前授权观测只用于观测当日，不回填为昨天或上周的新投放户。
- 日报缺口继续警告，不自动归到当前户，不补金额零。当前新核验户即使没有日报，也可在观测日形成待采集项；不把今天的核验倒推整周。
- 时区仅用于报表自然日及币种/报表维度隔离，不是店铺归属依据。
- 现有映射模型、权限范围不变。本轮只核验已批准映射；不会自动为一个广告户新增其他店铺采集。平台支持同户多店，但未登记店铺仍须独立 Shop 授权与显式建模，不能把账户全部消耗算给任意一家店。

## 定时行为

未新增或修改 systemd timer。既有 `sync_tiktok_gmv_max_recent` 在每个账户采集前进行一次受控核验，确认非当前户则保留历史并跳过本次新增采集。当前户的单日报表再核对两个官方接口，分页及金额校验不变。

独立维护命令：

```text
python manage.py verify_tiktok_gmv_relationships --tenant-id 1 --actor-id 1 --commit
```

`--mapping-id` 可重复指定；不带 `--commit` 仍会只读调用平台，但不追加关系审计。禁用映射不会被启用；失败不会自动重试或绕过审批。

## 首次核验结果

2026-11-04北京时间约15:00至15:05，对51个已启用映射执行一次核验：

| 结果 | 数量 |
| --- | --- |
| 当前投放户已确认 | 16 |
| 非当前投放户已确认，历史保留 | 26 |
| 未核验成功，未改绑定 | 9 |

9个待核验映射 ID：`6、7、20、21、26、38、39、42、43`。不声称它们是无广告数据，也不盲目重试。4个禁用映射未纳入本轮执行。

共追加42条 `ads_gmv_store_relation` 成功观测。主记录范围为审计 ID `1181356` 至 `1181397`，逐条回执见服务器 `probe-apply.jsonl`。42条可读观测已通过正式视图回读，包括 TKKJ1PH 当前户24和非当前户25的同店铺 ID/当前主户交叉校验。

## 部署与验证

- 正式备份和回执：`/opt/saas-collab/production/hotfix-ads-relationships-20261104-r3/`。
- r1/r2仅为未应用的预演目录，勿重放。r3的 `plan.json`、`receipt.json`、`verification.json`、`candidate-verification.txt`、`after-verification.txt` 和 `probe-apply.jsonl` 为执行证据。
- AST对比及文件哈希防并发覆盖；保留线上 `advertising_store_scope` 等后续修改。
- 后端修改4个现有文件、新增核验模块及命令；Gunicorn平滑HUP，未重建容器。
- 前端新增 `TikTokGmvStatus-cd1b1dfa70e6.js`、`MarketingAdvertising-GmvStatus-0d7aa06f6e8e.js`；只改当前主模块的广告子模块引用，未替换 index.html 或全站 dist。
- 后端79项定向测试通过（隔离内存SQLite、`--nomigrations`），前端19项通过，非mock生产构建通过。未声称完整MySQL迁移测试或登录浏览器验收。
- 生产只读正式视图返回200，105条日报全部具有可核对的店铺/广告户报表证据，42条当前关系观测可读。
- TKKJ2PH、TKKJ3PH均为1个广告户、7/7。金额指纹保持：`96592ae6d5d7d37c3e49c564c8003a087507d572f24b0f8b217ad09c248378c9`。
- 新资源及公网主模块均HTTPS 200，哈希匹配回执。需强制刷新已缓存的主模块；用户页面交互仍待用户验收。

## 回滚边界

先确认每个目标仍等于r3回执的after哈希。恢复 `backup/0` 至 `backup/3` 对应的4个原Python文件以及 `backup/entry.js` 对应主模块，再平滑HUP。若有后续变更则停止直接回滚。

新增但不再引用的模块/资源可保留。审计为真实只读核验观测，不删除，不回写历史金额。不要重跑旧覆盖率或GMV-only部署脚本。
