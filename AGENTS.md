# 阿里云版本更新记录

发布准备必须使用 frontend 的 `npm run release:prepare`、`npm run release:build` 和成功部署后的 `npm run release:confirm`，参数见维护说明。`--history` 必须是上一阿里云已部署制品的 release-notes.json 或有部署凭证的历史快照，不能用待发布文件自身代替。现有单次发布控制器在冻结源码前执行 prepare/check，成功回读后执行 confirm；禁止修改已封存或已执行的历史控制器。confirm 仅生成更新记录成功回执，不替代正式发布台账或业务验收。

每次发布阿里云新版本，必须同步维护 `saas-collab-system/frontend/src/data/releaseNotes.json`。规则见 `saas-collab-system/docs/06_release/aliyun-release-notes.md`。

构建前追加本次计划发布的版本号、实际计划发布日期（北京时间）和简短更新内容，使记录随前端一起发布。发布完成后必须核对线上更新记录与实际发布版本、日期一致；发布失败或取消的条目不得混入后续正式发布，跨日延期需修正日期后重新构建。虚拟机测试版本、未发布候选不作为阿里云历史记录。
