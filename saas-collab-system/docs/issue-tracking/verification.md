# 事件跟踪本地交付验证

日期：2026-11-26（北京时间）。分支 feat/issue-tracking-20261126，基线 2c1f39c7。

## 最终入口
右上角“个人设置 → 事件跟踪”；左侧不新增独立业务菜单。系统管理增加“事件跟踪配置”。首页摘要打开个人设置同一页签；旧 /issue-tracking 深链接保留兼容。

## 自动验证
- 后端：`python -m pytest tests/test_issue_tracking_api.py tests/test_issue_tracking_links.py tests/test_issue_tracking_context.py -q --nomigrations`：17 passed，3.55秒。使用临时数据库覆盖权限、状态闭环、候选范围、附件、通知、审计、日期和办理反馈时间。
- 完整迁移：`python -m pytest tests/test_issue_tracking_api.py tests/test_issue_tracking_links.py -q --disable-warnings`：14 passed，345.72秒；从空测试数据库执行项目完整迁移链。随后新增的3项上下文测试及反馈时间修正不改变数据库结构，已在最终17项测试中验证。
- `python manage.py check`：无问题。
- `python manage.py makemigrations --check --dry-run`：No changes detected。
- 前端：7个测试文件20项通过，包含原个人设置回归及新增个人入口、截图、表单、悬浮、日期、配置和摘要联动；见 frontend-tests.log。
- `VITE_USE_MOCK=false npm run build`：通过，15.21秒；包含菜单快照及既有hotfix保护检查，见 frontend-build.log。快照为134项菜单、173项路由。
- `git diff --check`：通过。

## 浏览器实际验收
使用 Playwright CLI，在 localhost 独立验收库和真实本地API上操作，没有用模拟接口冒充写入。
- 创建事项，反馈办理进展，提交完成，确认关闭；时间线保存全部操作，见 browser-closed.png。
- 右上角个人设置打开事件跟踪页签，左侧没有独立业务入口，见 browser-personal-settings.png、browser-snapshot.txt。
- 从个人设置创建带截图事项；实际执行遮挡并确认后上传，见 browser-screenshot-attachment.png。数据库中PNG附件140196字节；确定性像素检查新增47215个遮挡色像素，原图同色像素0，见 screenshot-verification.json。
- 实际打开审批页面的悬浮跟踪抽屉；鼠标拖动可移动，普通点击可打开，不把拖动误判为打开。
- 首页摘要刷新及按事项打开个人设置详情由组件测试验证。

## 交付边界
代码、迁移、测试、截图和使用说明均保存在本地独立工作区。未执行外部发布。正式启用按 usage-and-acceptance.md 中的迁移、权限同步、配置授权及菜单规则流程办理。
