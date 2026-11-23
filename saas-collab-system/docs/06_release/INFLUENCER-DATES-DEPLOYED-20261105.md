# 创建时间筛选：阿里云补部署

## 原因与范围

2026-11-05 实查 xtsy.dingfengchuangyu.com：活动入口 index-CFS-lxl7.js 所引用的建联、送样组件均无 created_from / created_to；后端 views.py 也没有日期过滤。PR #469 当时仍 OPEN，不能将此前广告功能的部署当作日期功能已上线。

本次只补两个列表的创建日期范围，不包含 #469 的视频关联变更。不修改数据库结构、业务记录、成本、状态、权限、同步或定时任务。

开始、结束日期均可单独填写；北京时间 UTC+8，结束日期包含全天；叠加原有作用域与筛选，在分页前过滤。更改日期回到第一页，重置同时清空日期。非法或倒置范围返回 400。

## 实际部署

- 目标：阿里云生产，https://xtsy.dingfengchuangyu.com 。不是 34。
- 备份与 receipt：/opt/saas-collab/production/hotfix-influencer-dates-20261105/ 。
- 构建脚本：deploy/influencer_dates_overlay_20261105.py 。根据生产快照精确锚点修改已有组件的筛选状态、查询参数、重置与日期控件，新增内容哈希组件；保留全部原有代码、Vue 共享依赖、其他路由。
- 前端：OutreachTaskList-dates-e03bdebdad54.js、SampleFulfillmentList-dates-a64957eb7b14.js；仅将当前入口的两个组件引用指向新文件，不替换 index.html、整套 dist 或广告功能。
- 后端：新增 apps/influencers/date_filters.py，仅在 views.py 两处列表创建日期排序前插入过滤；Gunicorn 平滑 HUP，不重启容器。
- 应用脚本检查容器 ID、每个原文件 SHA256 和新路径不存在，任一变化即拒绝覆盖。不可直接重放已执行脚本。

## 验证

- 日期边界、可选单边、非法日期、保留原查询作用域：9 项测试通过。
- 两个线上补丁组件：Node 语法检查和实际渲染函数构造、change 回调、查询参数、清空重置测试通过。
- VITE_USE_MOCK=false 完整前端构建通过。此 dist 只用于构建验证，没有覆盖生产整套前端。
- 部署前候选和部署后实际 Python 模块：各 8 项生产 SQL 只读接口检查通过。
- 送样 2026-11-05 当天与仅开始日期各返回 5 条；截至 2026-11-04 返回 9670 条；倒置范围 400。建联当日 0 条，截至前日 319 条。计数是核验瞬间快照。
- HTTPS 当前入口和两个新组件均 200，字节哈希匹配 receipt；生产现有其他文件未覆盖。
- 尚未完成用户真实登录浏览器中的视觉验收，接口检查不是浏览器验收。旧标签页需 Ctrl+F5 重新加载当前入口。

## 回滚

仅当原目标仍匹配 receipt 的 after 哈希时，将 backup-2 恢复到原入口 index-CFS-lxl7.js，将 backup-3 恢复到 /app/apps/influencers/views.py，再平滑 HUP。新增文件可留作未引用文件；无业务数据需要回滚。若哈希已被其他发布改变，先停止，不能覆盖后续改动。
