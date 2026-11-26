# 事件跟踪验收矩阵

本地验收日期：2026-11-26。路径均相对 saas-collab-system；浏览器使用独立 SQLite 测试数据。

| 编号 | 需求 | 当前证据 | 结果 |
|---|---|---|---|
| A01 | 个人设置入口及四类视图 | UserSettingsDrawer.vue；Index.vue；issueTrackingPersonal.test.js；browser-personal-settings.png | 通过 |
| A02 | 人员候选、唯一负责人、协办范围 | Issue.assignee、IssueSerializer；候选部门测试及候选请求者权限测试 | 通过 |
| A03 | 租户隔离及参与可见性 | test_tracking_flow_and_isolation；配置跨租户测试 | 通过 |
| A04 | 管辖部门、下级、有效期、细分权限 | test_department_grant_expiry_and_descendants；配置有效期及授权撤销测试 | 通过 |
| A05 | 发起、反馈、提交、退回、关闭、重开 | test_tracking_flow_and_isolation；browser-closed.png 实际浏览器闭环 | 通过 |
| A06 | 改派、改期、移交及操作审计 | test_reassign_reschedule_transfer_and_history；Index.changeText | 通过 |
| A07 | 菜单配置及服务端约束 | test_menu_requires_existing_enabled_rule；test_linked_record_cannot_bypass_menu_rule_by_omitting_menu | 通过 |
| A08 | 悬浮点击、拖动、收起和上下文切换 | issueTrackingInteraction.test.js；审批页面实际打开抽屉和鼠标拖动验证 | 通过 |
| A09 | 页面、单据关联及业务独立鉴权 | links.py复用原业务scope；test_issue_tracking_links.py；候选请求者与处理人校验 | 通过 |
| A10 | 截图预览、圈选、遮挡、裁剪、确认 | 4项截图组件测试；实际上传PNG；screenshot-verification.json | 通过 |
| A11 | 私有附件上传及下载重新鉴权 | 附件主管只读测试；撤销授权后下载拒绝测试；实际截图附件140196字节 | 通过 |
| A12 | 催办冷却、通知接收、关闭停止催办 | 闭环及通知标读越权测试；序列化器按状态裁剪动作 | 通过 |
| A13 | 逾期历史、办理反馈时间、确认时长 | 改期及逾期测试；test_creator_note_does_not_start_handler_feedback_clock；北京时间显示测试 | 通过 |
| A14 | 首页摘要、筛选、历史查询 | issueTrackingSummary.test.js；分页历史及日期全天测试 | 通过 |
| A15 | 权限导出、迁移及构建 | 134菜单/173路由快照检查；完整迁移14项通过；迁移无漂移；最终构建通过 | 通过 |
| A16 | 使用及回退说明、开发登记 | usage-and-acceptance.md；implementation.md；verification.md | 通过 |

业务记录适配范围：审批、异常、采购订单、供应商发货、物流批次、入库单。其他菜单可启用页面级跟踪，新增业务记录类型需要增加读取范围适配，未知类型由服务端拒绝。
