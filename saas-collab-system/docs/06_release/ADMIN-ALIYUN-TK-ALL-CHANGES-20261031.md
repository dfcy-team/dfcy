# 阿里云 TK 接入完整交接：授权、广告、视频及前端紧急修复

日期：2026-10-31。本文为本对话改动的汇总入口，不只包含PR，也包含生产容器热修复、数据库/凭据配置和systemd任务。动态状态以管理员交接时再次只读核查为准。

## PR交接补充（北京时间2026-10-31 13:35核查）

- 本PR仅提交管理员交接文档，不包含业务代码、迁移执行、生产部署或审批操作。合并本文档不等于生产热修复源码已合入主干；管理员仍须按文件清单逐项比对现场与主干，不能直接覆盖容器。
- 修正版续跑出现新的实质失败：TKKJ1PH（店铺8）2026-10-06，批次123仍返回`invalid_video_rate`。这不是仅等待修复的旧进程失败，需定位具体指标后再决定修复；本次未重试、未放宽校验。
- 当时已完成131个店铺日，131份提交回读证据已验证；正式日指标PHP 44445条、THB 1494条、MYR 173条，合计46112条。另有16个失败店铺日和1个运行中店铺日。尚未覆盖18家全部540个店铺日，不能验收为完成。
- 下文及配套文档中的计数是更早的时间快照；以本补充及后续运行证据为准。续跑尚在执行，保留自动跟进及既有夜间任务，不另开重复任务。
- 本PR没有附带密钥、Token、授权码、完整授权回调或生产业务备份；管理员应在服务器上读取受控回执与哈希清单。

## 一、先看结论

| 项目 | 已完成 | 未完成或限制 |
| --- | --- | --- |
| 商城授权 | 现场18家TK店铺有当前有效商城授权 | 11家启用店铺没有当前有效授权；不等同于从未授权 |
| 广告授权配置 | 广告连接#33 verified，网络和读取开启，写入关闭；广告回调已配置 | 授权与商城独立；不能用商城Token代替广告授权 |
| 广告绑定 | TK1PH已绑定2个广告主，读取均开启 | 其他店铺尚无广告主映射；#33广告同步任务数量0 |
| 广告户名称 | API和能力矩阵、广告工作台显示账号名称 | 名称不能代替广告主ID和店铺归属核验 |
| GMV Max | TK1PH指定广告主2026-10-30单日真实API快照及展示已接入 | 未开定时；不是全店全量，不与BASIC或商城GMV混加 |
| 视频正式入库 | 0041/0042/0043迁移、独立采集命令、分页证据和数据库回读已部署 | 全店近30天仍在执行，不能说已全部完成 |
| 视频夜间任务 | 阿里云服务器每天北京时间20:00同步最近30完整当地自然日 | 不含当天；通用SyncJob/能力矩阵没有新增VIDEO入口 |
| 达人信息查询 | 现有代码和权限检查保留 | 运行时达人查询审批仍关闭，尚不能宣称真实查询全部可用 |
| 自动履约完成 | 未改建联、送样、归因或负责人 | 达人OpenID对应和发布时间时区未验收，履约更新0 |
| 独立广告配置页 | 本地候选代码和测试存在 | 线上无setup模块和路由，明确未部署；当前走店铺档案API接入 |
| 白屏 | 新旧前端入口重复挂载已修复 | 登录后具体业务数据仍需使用实际账号回归 |

这不是“全部模块已经接通”的交付。不要把已绑定、已启用、健康、原始快照、Stage暂存、正式入库和最终业务对账混为一谈。

## 二、授权和待处理店铺

### 商城

回调：`https://xtsy.dingfengchuangyu.com/integrations/tiktok/shop-callback`。

本次只读核查有当前有效授权的18家：

`TK1MY、TK1PH、TK1TH、TK2PH、TK3PH、TK4PH、TK6PH、TK7PH、TK9PH、TKKJ1MY、TKKJ1PH、TKKJ1TH、TKKJ2PH、TKKJ3PH、TKKJ4PH、TKKJ4TH、TKKJ5PH、TKKJ6TH`。

启用中但没有当前有效商城授权的11家：

`TK4TH、TK5PH、TK5TH、TK8PH、TKKJ2TH、TKKJ3MY、TKKJ3TH、TKKJ5TH、TKKJ6MY、TKKJ6PH、TKKJ7PH`。

管理员应分别检查未绑定、过期、撤销、身份核验失败，而非一律新增或覆盖授权。有效授权名单会随时间变化；没有授权的店铺不会被夜间任务强行绕过。

商城手动URL导入的设计记录见`tiktok-manual-direct-import-20261026.md`：允许明确人工导入缺state回调，不代表取消用户/租户/浏览器上下文、配置、真实店铺身份和确认绑定检查；错误state不能随意忽略。不要把这种商城人工导入规则套用到广告OAuth。

历史TK1MY换绑、商品同步、建联商品来源匹配等议题，本轮没有重新完成端到端验收；保留历史归属和审计，不能仅凭本文推断全部已修复。现有生产差异清单已额外列出相关文件供管理员溯源。

### 广告

- App ID：`7651554890895851537`，不是商城Service ID。
- 回调：`https://xtsy.dingfengchuangyu.com/integrations/tiktok-ads/direct-callback`。
- 连接：租户1、广告配置#33。当前verified，network_enabled=true，sync_read_enabled=true，sync_write_enabled=false。
- 官方Marketing网络准入和OAuth回调白名单是两项不同配置，必须都满足。
- App Secret通过既有凭据轮换接口托管，审计1096188，历史连接版本4到5；不得写到代码、文档或发布环境明文覆盖。回调与嵌套redirect_uri已统一。
- TK1PH广告户：Nova.ph store / `7365788829120397328` / PHP / Asia/Manila；YX-菲律宾-本土1号店 / `7651940663654678546` / USD / Asia/Manila。两户读取均开启。
- 目前广告映射只有上述两条，#33没有同步任务。绑定成功不等于已经拉取全部广告报表。

人工授权流程：店铺档案 → 目标店铺API接入 → 广告API选择配置 → “填写/粘贴回调URL”生成本次授权链接 → 在已登录正确广告账号的浏览器完成授权 → 回原SaaS会话回填对应完整回调一次 → 核验广告主 → 明确选择并确认绑定。

state由SaaS生成，必须对应同一次会话，不能换店、换用户、重复生成链接后混用旧回调。结果未知时先查授权会话及诊断记录，不重复兑换旧授权码；Token已取得但映射未确认也不算绑定完成。站斧拦截自有SaaS回调域名属于浏览器访问策略，不是Token必然过期。

当前映射唯一约束为“租户+广告主”。一店多广告主可用；一广告主多店仍不能作为已支持交付，不能把账户总消耗复制到多个店铺。

### 审批和刷新

- 运行时`affiliate_seller_creator_read_approved=false`，达人查询scope为空。管理员需先按SaaS流程准备精确店铺范围和查询权限，再由另一位有权管理员审批。
- `auto_refresh_enabled=true`但`auto_refresh_bindings=[]`。不能据此声称全部店铺由SaaS自动续期；还应核对各授权的托管归属。
- 达人查询清单与令牌刷新清单应独立维护。本文不宣称拆分方案已经部署；禁止为开达人查询而顺带扩大令牌刷新范围。
- v34历史草案混入modules，审批被禁用曾是草案内容问题。后续改用干净草案v35、再加官方出站域名v36。旧文档底部仍有“审批v34/等待v35”的历史描述，已过时，不能照抄审批。当前广告配置已具备就绪条件，不需要为过去的问题盲目重复授权。
- 独立广告setup页尚未部署，不能要求管理员访问不存在的页面；其本地候选不应随本次版本同步夹带上线。

## 三、直接部署文件和配置

以下路径相对`saas-collab-system/`，容器内后端前缀为`/app/`。

| 功能 | 必须保留/合入的源码 | 现场记录目录 |
| --- | --- | --- |
| 广告配置校验 | backend/apps/integrations/serializers.py、platform_schema_service.py | hotfix-tk-ads-config-20261030 |
| 广告授权诊断 | backend/apps/integrations/tiktok_ads_oauth.py | hotfix-tk-ads-diagnostics-20261031 |
| 广告户名称 | backend/apps/integrations/ads_capability_api.py；frontend/src/components/TikTokAdsCapabilityMatrix.vue | hotfix-tk-ads-name-20261031 |
| GMV Max单日采集 | backend/apps/integrations/gmv_max_sync.py；management/commands/sync_tiktok_gmv_max_day.py | hotfix-tk-gmv-day-20261031 |
| GMV Max及名称展示 | backend/apps/integrations/gmv_max_read.py；backend/apps/reports/tiktok_ads_services.py；frontend/src/components/TikTokAdsDailySpendOverview.vue | hotfix-tk-gmv-view-20261031 |
| 视频分表及采集 | backend/apps/influencers/models.py的两个限定类；tiktok_video_sync.py；management/commands/sync_tiktok_shop_videos.py；迁移0041/0042/0043 | hotfix-tk-video-sync-20261031 |
| 白屏入口修复 | 当前前端index.html、canonical入口、兼容重导出入口和bootstrap | hotfix-single-entry-20261031 |

现场目录共同前缀：`/opt/saas-collab/production/`。各目录的before、after、receipt、ADMIN-HANDOFF按实际文件布局保存，不要跨批次拿旧备份整套覆盖。

广告配置调整属于数据库/凭据托管状态，不是Git提交；systemd定时器属于服务器配置，也不在旧镜像里。仅合并PR无法覆盖全部变更。

### 其他已存在生产差异，必须保留并追溯

本轮docker diff另外发现以下文件偏离当前镜像，不能确认都是本轮新增，也不能遗漏或误删：

- backend/apps/influencers/platform_accounts.py、views.py。
- backend/apps/integrations/product_mapping_service.py、readonly_clients.py、platform_product_ingestion.py。
- 前端`/etc/nginx/conf.d/default.conf`和历史静态资源改动。
- 既有现场回执目录`emergency-archive-read-20261030`、`emergency-owner-cpu-20261030T102200`。

这些内容应与相应负责人/现场回执核对后合并，不能拿本地旧分支覆盖。本文列出是为了防丢失，不是宣称完成了其全量审查。

## 四、数据验收和未启用项

### GMV Max

TK1PH广告主`7651940663654678546`，2026-10-30、Asia/Manila、USD，完整18计划：消耗71.02、报表收入489.61、报表订单54。SharedAdvertisingRawPayload快照1，审计1096206，API与快照回读一致。

这是独立原始快照展示，不写BASIC竞价日消耗；没有GMV Max夜间全店任务，尚未用TikTok后台人工截图完成最终金额对账。PHP与USD分开，GMV Max与BASIC、商城GMV、联盟计佣口径分开。

### 视频

TK1PH店铺23、2026-10-30：288条日指标、6页、281条视频商品关联；views18569、sku_orders33、reported_gmv13995.71 PHP、attributed_gmv17185.49 PHP。逐行数据库回读通过，复导跳过。

独立模型：TikTokShopVideo、TikTokVideoProduct、TikTokVideoDailyMetric、TikTokVideoSyncBatch、TikTokVideoSyncEvidence。Stage旧326条不能冒充正式数据；正式表来自重新读取API。

19个历史指标字段改为可空；原始GMV、SKU订单、CTOR独立保存。原生CTR可因重复点击超过1，0043去掉错误上限，但不强行改值。订单数缺失不当0，sku_orders不冒充orders；无时区发布时间和不明达人身份不猜测。

交接只读快照：54个店铺日completed，4229条正式日指标，16个旧执行进程校验失败日期待修正版续跑，1个日期running。此数字仅代表核查时刻，不是全量完成结果。61项本地测试通过；全店最终结果由跟进任务后续通知。

服务器每天北京时间20:00执行`saas-tk-video-nightly.timer`，按店铺业务时区处理最近30完整自然日，逐店串行，复用已授权凭据，文件锁和数据库租约防重。首次任务`saas-tk-video-backfill-20261031.service`，修正版串行续跑`saas-tk-video-resume-20261031.service`。不得另开一个相同全店任务。

视频通用同步列表、视频前端查询界面没有本次新增；日表具备租户/店铺/日期索引，不代表7天/9天自定义查询页面已经上线。自动履约仍为0，不修改建联、送样、归因负责人或人民币成本。

### 联盟订单、达人查询

商城已授权不能证明联盟订单、达人信息、视频和BD绩效全部权限通过。联盟订单本轮未做新的全链路验收，不能复用视频结果宣布已接好；达人查询审批尚未开启。后续应逐店验证正式入口、scope、完整分页、幂等和金额，再接归因/绩效刷新，不直接改旧业务记录。

## 五、白屏修复和版本合并红线

新HTML入口曾指向index-b33dd7df2f83.js，页面组件仍引用index-BrPhyQb4.js，两份代码都mount应用，产生nextSibling空引用并白屏。已保留单一canonical入口，其他入口只重导出，并保留最新广告工作台与能力矩阵块。

真实Edge验证：未登录访问送样路径能正常显示企业登录页，无脚本错误，送样模块动态加载成功。未冒用用户登录态，登录后数据需实际用户验收。

不得照旧广告文档直接把入口恢复为index-b33dd7df2f83.js或index-84691451bdf8.js的旧内容。发布应整体保证入口/chunks依赖一致，不能只改入口文件名；也不能用旧完整前端覆盖现场功能。构建必须保持真实API模式，禁止演示账号/Mock兜底。

## 六、管理员执行顺序

1. 备份现场受影响源码、静态资源、Nginx、systemd和现有回执；读取本目录CURRENT-RUNTIME-HASHES.json。不要导出Secret、Token、完整回调或数据库业务备份到公开仓库。
2. 对照清单合并热修复源码与测试，并核对未归属的生产差异。基线435c29841191de7b2dd5351c30389281856d2141 / V2.44.330仅是起点，不等于当前生产全部代码。
3. 保持已执行0041/0042/0043迁移历史一致，检查其他分支编号冲突。不要删除视频事实、审计、授权历史，不用入库前空备份覆盖现在的数据。
4. 保留广告#33配置及凭据引用、已有商城绑定、审批历史和权限。不要重放旧草案、种子数据或旧环境Secret。
5. 在隔离环境跑相关测试；按匹配源码正常构建。验证登录、送样、广告授权会话、广告户名称、GMV Max只读展示和视频重复执行。
6. 重建容器会丢失可写层热修复。发布前先把清单内容放入新镜像，不能只拉旧镜像后宣称已同步版本。
7. 视频包装每次核验runtime-manifest.json，代码改变会停止任务。合并验证完成后才更新哈希清单，不能只改哈希绕过检查。不要在补录仍运行时另起重复同步。
8. 回滚需按单项兼容方案进行，不回滚账号/授权/业务数据库。停任务、重启或清理前明确影响范围；保留已取得事实和审计。
9. 将最终Git提交、镜像摘要、部署时间、文件哈希和验收证据写入正式更新记录。本次直接部署不自动等同于PR已提交或合并。

## 七、配套文档索引

- TK-Ads-config-hotfix-20261030.md：广告配置边界与审批草案修正；其中旧待审批状态已过时。
- TK-Ads-diagnostics-20261031.md：授权失败阶段、诊断号和出站准入；旧“等待审批”不代表当前状态。
- TK-Ads-secret-correction-20261031.md：配置/凭据变更审计，不含密钥。
- TK-Ads-account-name-20261031.md：名称API与能力矩阵；旧入口回滚方式被白屏修复取代。
- TK-GMV-Max-day-and-view-20261031.md：单日采集及展示；旧入口说明被白屏修复取代。
- TK-VIDEO-FORMAL-SYNC-20261031.md：视频表、迁移、任务、对账与边界。
- FRONTEND-WHITE-SCREEN-20261031.md：白屏原因和最终入口修复。
- TK广告配置页管理员交接-20261030.md：未部署候选页面，不能当作线上功能。
- tiktok-manual-direct-import-20261026.md：商城人工URL导入设计及风险，不代替当前端到端验收。

本汇总与现场最新回执优先于旧文档的过程性状态。本文没有修改任何配置、重新授权、开启额外任务或停止现有任务。
