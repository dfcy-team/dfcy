# V2.44.109 广告分析菜单发布候选（等待受控发布）

日期：2026-09-15  
状态：`WAITING_FOR_CONTROLLED_RELEASE`。本版本仅完成本地隔离候选登记，尚未推送、合并、构建不可变镜像或部署。

## 基线与候选

- 已核验的最新部署版本：V2.44.108。
- V2.44.107、V2.44.108 已完成受控部署，本批次登记为 V2.44.109。
- 隔离基线：`origin/main` `153ca95f256f631087b1a83916c5fd7d0a6f4832`（V2.44.108）。
- 候选分支：`release/v244109-advertising-v108`。
- 功能提交：`e84de7070165bd43080e6f9f6a80a1984f2f70a3`（由原始功能提交 `82580c0e486ac9e162b8588dfb7b738156e4bc47` 重放到 V2.44.108 基线）。

## 授权范围与功能边界

本批次只增加广告分析和费用对账入口，不重复建设广告账户或广告同步菜单：

- 经营分析：新增“广告总览”“广告投放分析”。
- 财务中心：新增“广告费用对账”。
- 复用 `analytics.view`、`finance.view` 和现有菜单权限注册机制。
- 页面为只读 L1 能力；广告报表、归因链路和费用数据未接入时显示明确空状态。
- 不执行预算调整、停投、关键词修改、账单确认、付款或任何平台写操作。

## 变更清单

- `backend/apps/permissions/menu_registry.json`：登记 3 项菜单权限和 3 项路由权限。
- `frontend/src/router/menu.js`：增加 3 个菜单入口及路由能力契约。
- `frontend/src/router/index.js`：增加 3 个页面路由。
- `frontend/src/api/advertising.js`：增加 pending 只读数据边界，不返回伪造业务数据。
- `frontend/src/views/analytics/AdvertisingOverview.vue`：广告总览空状态页面。
- `frontend/src/views/analytics/AdvertisingPerformance.vue`：广告投放分析空状态页面。
- `frontend/src/views/finance/AdvertisingReconciliation.vue`：广告费用对账空状态页面。
- `frontend/tests/advertising-menu-routing.spec.js`：菜单、路由、权限和只读边界测试。
- `frontend/tests/v24433-menu-baseline.spec.js`：菜单基线数量更新为 106。

本批次无数据库模型或迁移、无角色授权数据、无平台凭据、无部署或 Compose 文件变更。

## 本地门禁

- 广告及菜单基线定向测试：10 项通过。
- 前端完整测试：107 个测试文件、658 项通过。
- 后端菜单权限注册测试：5 项通过。
- 菜单权限快照：104 项菜单权限、136 项路由权限，一致性检查通过。
- 前端生产构建：通过。
- `git diff --check`：通过。
- `package-lock.json` 未修改；安装阶段报告既有依赖树 2 个 moderate、1 个 high 风险，本批次未自动升级依赖。

## 待发布门禁

1. 架构员复核候选相对 V2.44.108 基线的 10 个文件差异，并确认不回退 V2.44.108 修复。
2. 推送候选分支并通过受控 PR/CI；禁止从当前开发工作区直接构建生产镜像。
3. 重新执行完整前端、后端和菜单权限门禁，生成不可变镜像与摘要。
4. 发布前刷新虚拟机实时版本、数据库迁移、角色权限及菜单快照，确认累计发布范围。
5. 取得最终发布确认后才能切换镜像；部署结果另行登记，不能将本候选文档作为已发布证明。

回退方式：发布失败时恢复发布前已登记的前端镜像摘要；本批次无数据库迁移或业务数据写入，不需要数据库反向迁移。
