# 阿里云更新记录维护

## 自动维护入口（V353 候选）

在 frontend 目录执行以下步骤。版本号取已分配的发布版本，不自动抢占编号；changes.json 是审核过的非空中文字符串数组。history.json 必须取上一阿里云成功部署制品的 release-notes.json（首次接入可用 V349 R3 已验证源码快照）。prepare 默认使用北京时间当天，也可显式传 --date YYYY-MM-DD。

```sh
npm run release:prepare -- --history /path/history.json --version 2.44.353 --changes-file /path/changes.json
npm run release:build -- --history /path/history.json --version 2.44.353
```

prepare 在构建与源码冻结前追加条目、保留历史。build 校验版本与历史，强制关闭模拟模式并使用同源 API。普通 vite build 同样拒绝缺失或不为 false 的 VITE_USE_MOCK，避免再次误发演示产物。构建产物额外输出 release-notes.json，供发布回读与下一版继承历史。

发布由原有控制器执行。其成功检查后生成独立的标准部署凭证（status 为 PASS，version 为实际版本），再调用：

```sh
npm run release:confirm -- --history /path/history.json --version 2.44.353 --deployment-receipt /path/deployment-pass.json --url https://xtsy.dingfengchuangyu.com/release-notes.json --output /path/notes-registration.json
```

confirm 校验部署凭证和 HTTPS 线上内容逐字节一致，才生成可重复调用的成功回执；失败、版本不符或线上内容不符不会登记成功。它不会自动部署、推送、合并、改写正式台账或宣布人工验收完成。历史发布控制器的封存脚本不修改；下一次发布需在其准备/成功回读步骤接入这些入口。此次自动化仍为本地候选，未因本次登记而在远端激活。

入口：顶部右侧「更新记录」，位于「个人设置」左侧。弹窗按日期、版本倒序展示，可滚动回查；不增加数据库、后台编辑或业务菜单权限。

## 每次阿里云发布必做

1. 构建前，在 `frontend/src/data/releaseNotes.json` 追加本次发布条目：`version` 为不带 V 的实际发布版本号，`date` 为北京时间发布日期（YYYY-MM-DD），`changes` 为简短中文说明数组。内容概括本次实际发布的新增、优化、修复，保留历史条目，不录入密码、地址、客户数据或内部操作细节。
2. 将记录修改与本次前端一起构建、交付。即使仅更新后端，也要同步发布含新记录的前端；只修改源文件不会更新线上显示。本功能自身的更新说明在实际发布编号、日期确定后追加，不预占编号或伪造已上线记录。
3. 发布成功后，打开阿里云「更新记录」，核对顶部条目版本、日期和内容，作为发布完成检查项。只有虚拟机验证或候选登记的版本不写入阿里云历史。
4. 发布失败或取消时，删除未成功条目再交付下一次发布；跨日延期先修正日期并重新构建。回滚使用原前端制品，下一次发布前按真实成功历史校对记录。

无需增加自动通知、审批流程或独立更新服务。静态记录由发布人员随版本维护，不会自动读取 Git 提交或部署台账。弹窗记录的是发布历史，不是实时运行版本探测。

## 初始记录依据

首次收录 V2.44.315，日期 2026-10-27，仅补录可核实的两条图片展示变更，不推测更早版本历史。

- 运行提交：`27eb1bc28f7052c988fa8f7c32a5420b36596a1c`。
- 功能来源：`system_v2.44.315_platform_product_image_source_candidate_20261026.md`，以及该提交中的平台商品图片变更。
- 本地部署凭证：工作区 `发布控制/V2.44.315阿里云累计发布_20261027/deployment-final-summary315.json`，状态为 `V315_CLOUD_TECHNICAL_DEPLOYMENT_PASS`，北京时间 2026-10-27 17:54:09 完成；对应回读凭证 `roll-r3-state-20261027T095453Z.json`。
- 该凭证同时注明人工业务验收和正式登记未完成，正式指针为 V2.44.303；记录表示部署过的版本，不声明人工业务验收已完成。

## 验证

在 `frontend` 目录运行 `npm test -- tests/release-notes.spec.js tests/user-settings.spec.js tests/main-layout-navigation-tabs.spec.js` 和 `npm run build`。

2026-10-28 开发验证：上述 3 个测试文件共 18 项通过；生产构建通过；菜单权限快照一致（118 项菜单、152 项路由）；`git diff --check` 通过。构建仅有依赖注释警告。未做真实浏览器视觉验收，未部署阿里云。

开发分支：`feat/release-notes-20261028`；基线为上文 V315 运行提交。合并到后续发布版本时保留该版本的其他功能，并在确定发布编号和日期后追加本次更新记录。
