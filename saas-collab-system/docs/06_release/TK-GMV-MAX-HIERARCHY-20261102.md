# GMV Max 分层查询交接（第一阶段）

## 本次代码范围

仅广告报表后端与广告组件。沿用已有租户、店铺可见性过滤，不调用平台写接口，不改变授权、投放、预算、账号权限或其他模块。

图一：沿用店铺、广告户、开始/结束日期筛选，新增按店铺、真实平台店铺ID、广告户、币种和报表时区分组的区间概览。
展示成本、SKU订单数、平均下单成本、报表收入、ROI和覆盖天数。
金额使用后端Decimal；ROI=收入合计/成本合计，平均成本=成本合计/SKU订单数合计，不累加每日比率。
少一天即标已采集小计；超限、无数据、重复同日快照不能伪装成0或完整总额。不同币种和时区不合并。
此阶段只读现有GMV_MAX_CAMPAIGN日报，不把BASIC报表叠加，也不重新导入旧表。

## 尚未实现、不得当作上线验收

1. 商品GMV Max/LIVE GMV Max分类：需采集官方计划类型，禁止根据计划名称猜测。
2. 计划详情：计划ID、名称、状态、预算/目标ROI（只读）、区间指标及日趋势。
3. 计划内商品：按真实商品ID展示商品名称、图片和该层级报表指标。
4. 商品内创意：视频/商品卡分开，展示作品ID、账号、授权类型、状态、发布时间及API实际返回的花费/订单/收入。
5. 直播单独保留直播间/场次身份，不伪造商品或视频关联。

每层均需保存来源、维度、日期、币种、时区、完整分页证据和采集时间，采用独立幂等键。查询只读数据库，不在每次点击时触发全量拉数。
计划汇总、商品明细、视频明细不能上下相加；某层缺失字段显示未知。商品卡没有视频ID不能计入视频。
GMV Max报表收入可能包含自然及付费归因，不等于纯付费成交或商城销售额。
截图本身不是API字段可用性的证明；深层接口需使用已核验店铺和广告户先跑一天并对账。

## 验证与部署状态

4项纯函数隔离测试通过（精确累加与加权比率、缺日期、身份/币种/时区隔离、重复与零分母）。
2项前端比率测试通过。未运行完整Django报表权限回归；本机默认Python没有pytest。
生产模式前端构建通过（VITE_USE_MOCK=false）；菜单权限快照检查通过。
2026-11-02已将第一阶段广告概览定向部署阿里云；图二至图六仍未实现。
禁止覆盖整个生产前端目录发布此组件，必须基于线上当前源合并构建，明确VITE_USE_MOCK=false并回归登录及达人页面，防止覆盖其他热修。

## 官方参考

- https://github.com/tiktok/tiktok-business-api-sdk/blob/main/python_sdk/docs/ReportingApi.md
- https://ads.tiktok.com/resources/help/article/how-to-see-reporting-for-your-product-gmv-max-campaign

商城续期worker修复和9店真实续期证据见PR456的TK-CREDENTIAL-WORKER-20261102.md，不包含广告令牌刷新实现。

## 阿里云实际部署记录

访问 https://xtsy.dingfengchuangyu.com/analytics/advertising-overview ，选择“TikTok 已存竞价消耗”页签，查看上方GMV Max概览。首次访问请Ctrl+F5刷新。

备份及回执目录：`/opt/saas-collab/production/hotfix-ads-overview-20261102/`。
脚本：`deploy_ads_overview_20261102.py`。发布前核对哈希，保留before.js、before.css、before-service.py、entry-before.html、dependency-map.json、receipt.json。

生产当前入口引用AdvertisingOverview-088lMSCV.js，不是之前热修的DxaI_qd7版本。本次只替换已构建的TikTok广告组件，保留线上广告父组件、其他报表和全部共享依赖；不上传旧工作树的整套dist、不替换index.html、入口JS或Vue。
后台仅增加gmv_max_overview.py和报表响应字段，向已核对的Gunicorn主进程发送HUP平滑重载。不重启数据库、worker或同步任务。无业务数据写入、无授权/账号/权限修改。

已验证：
- 发布产物JS语法、Python语法、导入的共享模块导出符号检查通过；所有发布文件回读哈希一致。
- 广告页面、登录页面和当前广告JS均HTTP 200。
- 生产只读事务中执行完整报表视图权限检查，租户1现有root用户，TK1PH店铺23，2026-10-26至2026-11-01：HTTP 200，7/7天，无重复冲突；成本363.16 USD，订单295，收入2418.25 USD，ROI6.66，平均下单成本1.23 USD。
- 当前映射存在local_evidence_unverified，广告名为空时界面回退显示广告主ID；未绕过核验或篡改名称。历史日报展示不代表当前授权已重新验收。
- 内置浏览器核验超时，尚未完成登录态视觉验收；不得将HTTP检查写成完整浏览器验收。

管理员正式同步时必须合并PR454源文件后构建生产镜像（VITE_USE_MOCK=false）。当前为容器定向热修，容器重建可能覆盖；不要仅复制旧PR或覆盖整个生产前端。PR456是独立的达人/视频及商城续期配置兼容修复，并非本广告页面重复PR。

回退：在确认receipt.json中的部署后哈希仍匹配且无后续修改后，恢复before-service.py、before.js、before.css，平滑重载Gunicorn；新增纯函数文件可保留为不再引用的文件。不要回退数据库或用户配置。
