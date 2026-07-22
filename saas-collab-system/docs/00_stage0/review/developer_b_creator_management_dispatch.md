# 开发B节点分发：达人管理

## 1. 任务信息

- 负责人：开发B。
- 建议分支：`feature/module-b-creator-management`。
- 基线：本分发 PR 合并后的最新 `main`。
- Local Sandbox profile：`creator-management`。
- 风险：档案、合作任务和合成效果为 L2；敏感字段、审批、权限和状态机为 L3。

## 2. 开发目标

面向内部达人运营人员，使用合成数据完成“达人候选档案 -> 合作提案 -> 人工审核 -> 合作任务 -> 效果复盘”的最小闭环。目标是让运营人员可以检索、分派和复盘，不连接真实达人平台、不自动触达达人、不处理结算。

本地样本至少包含两个 tenant、20 个合成达人、多个国家/平台、10 个合作记录及 loading/empty/error/forbidden 状态。

## 3. 后端内容

1. 新增独立 creators app 或符合现有工程边界的等价模块，不将达人模型放入 products、finance 或 suppliers。
2. 实现 profiles、collaborations、tasks 和 performance 资源，路径以模块 API 合同为唯一口径。
3. 所有核心模型包含 tenant；跨商品引用只读取 tenant 内授权商品摘要，不修改商品编码或生命周期。
4. 档案与合作状态只经 action 服务改变，通用 PATCH 不修改状态；模型 save、bulk 和并发请求不能绕过。
5. 合作提交人不得审批自己的合作，审批和取消保留审计、版本和原因。
6. 效果统计只使用合成聚合值；不保存平台 Token、Cookie、Session 或真实账号凭据。
7. 联系方式等敏感字段加密或掩码，列表、日志、错误、导出和前端状态中不得出现明文。
8. 新权限码和 `creator_dimensions` scope 必须通过迁移、权限目录和负向测试落地。

## 4. 前端内容

1. 增加达人档案列表/详情、合作列表/详情、任务列表和效果复盘页面。
2. 页面提供搜索、筛选、分页、loading、empty、error、403、404、冲突和校验状态。
3. 状态 action 按后端 permission 显示并在点击处理器二次校验；后端是唯一可信授权边界。
4. 敏感字段只显示掩码，不提供真实密钥、账号、Cookie、Session、结算或付款输入框。
5. 无“连接平台”“批量私信”“自动邀约”“自动发布”“自动结算”等真实动作。
6. Local Sandbox 的只读 `/mock/creator-management/*` 保持 Mock fallback；后端未实现前正式路径保持 `pending`。

## 5. API、权限和 scope

统一资源：

- `/api/internal/creators/profiles/*`
- `/api/internal/creators/collaborations/*`
- `/api/internal/creators/tasks/*`
- `/api/internal/creators/performance/`

权限使用 `creator.view/manage`、`creator.collaboration.view/manage/review`、`creator.task.view/manage` 和 `creator.performance.view`。CUSTOM scope 使用 `creator_dimensions`，只允许 platform、country、creator_id、collaboration_id 和 campaign_code。

缺失 scope 不等于 ALL；每个 action permission 独立求值。external、RPA、跨 tenant 和超 scope 用户必须被后端拒绝。达人模块不得调用 finance、admin 或 RPA Agent 执行路径。

## 6. 必须测试

- 两 tenant 的 profiles、collaborations、tasks 和 performance 隔离。
- `creator_dimensions` 的 ALL、缺失、空、未知、非法类型和超范围值。
- view/manage/review/task/performance 权限不能互相替代。
- 提交人与审核人职责分离；非法迁移、重复动作、并发和 bulk 绕过被拒绝。
- 敏感字段在 API、日志、异常和页面中保持掩码。
- 统一成功、分页、401、403、404、409 和 422 合同。
- Creator Mock 的 GET、405 写拒绝、404 未知路径和合成数据检查。
- 未实现接口保持 pending，Mock 保持 mock，联调完成后才允许 connected。
- Django check、迁移一致性、模块 pytest、全量 pytest、前端 test/build、Sandbox verify 和安全扫描。

## 7. 启动与验证

```powershell
cd deploy/dev-sandbox
.\sandbox.ps1 init
.\sandbox.ps1 start creator-management
.\sandbox.ps1 verify creator-management
```

开发结束后同步最新 `main`，再运行 `integration` profile。

## 8. 交付物

- creators 后端模块、迁移、权限和测试。
- 达人前端 API、Mock、路由、菜单、页面和组件测试。
- 更新后的模块 API 合同与 `frontend_api_mapping.md`。
- 开发B变更日志和本地/CI验证报告。
- Draft PR；明确 L2/L3、敏感字段策略、状态机和回滚方案。

## 9. 禁止项

- 不接真实 TikTok/TK、Shopee、BigSeller、社交媒体或达人平台。
- 不保存真实达人账号、联系方式、消息、合同、结算或付款数据。
- 不实现爬取、登录、自动邀约、自动私信、自动发布或真实 RPA。
- 不访问或修改库存、采购、供应商和财务业务数据。
- 不以页面隐藏代替后端 tenant、permission 和 `data_scope`。
