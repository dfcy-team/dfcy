# SaaS 协同系统 V2.44.6 Reviewed 基线登记

## 1. 基线身份

- 登记日期：2026-08-12
- 代码提交：`5d64146940ac300c127a571d8d11164f35e76a3f`
- 基线分支：`codex/creator-v2.44.5-reviewed`
- 发布名称：V2.44.6 Reviewed
- 前端镜像：`saas-collab-frontend:creator-v2.44.6-reviewed-5d64146-20260812`
- 后端镜像：`saas-collab-backend:creator-v2.44.6-reviewed-5d64146-20260812`
- 应用层 VM：`192.168.174.131`
- 数据库层 VM：`192.168.174.132`

本文件是后续功能开发、菜单合并、路由调整、权限分配和发布审核的基础框架。任何新开发节点必须从本基线向前增加，不得使用旧分支或候选镜像覆盖当前结构。

## 2. 完整菜单结构

菜单顺序和层级以 `frontend/src/router/menu.js` 为唯一运行时来源。本基线登记如下。

1. 工作台
   - 工作台：`/`
2. 产品开发
   - 选品提报：`/development/requirements`
   - 需求审核：`/development/review`
   - 开发项目：`/development/projects`
   - 成本核算：`/development/costs`
   - 销售数据：`/development/sales`
   - 选品复盘：`/development/retrospectives`
   - 效能看板：`/development/dashboard`
3. 全球刊登
   - 全球刊登工作台：`/listings/workbench`
   - 刊登任务：`/listings/tasks`
   - 在线商品：`/listings/online-products`
   - 平台类目映射：`/listings/category-mappings`
   - 商品属性映射：`/listings/attribute-mappings`
   - 刊登日志：`/listings/logs`
   - 刊登异常：`/listings/exceptions`
   - 刊登资料：`/listings/sites`
   - 刊登模板：`/listings/templates`
4. 经营分析
   - 经营总览：`/analytics/overview`
   - 销售分析：`/analytics/sales`
   - 库存分析：`/analytics/inventory`
5. 经营决策
   - 库存预警：`/inventory/alerts`
   - 补货建议：`/inventory/replenishment`
   - 生命周期复盘：`/lifecycle/reviews`
   - 复盘历史：`/lifecycle/history`
   - 清仓申请：`/lifecycle/clearance-requests`
   - 经营预警：`/alerts/business`
6. 达人管理
   - 达人档案：`/influencers`
   - 建联任务：`/influencers/outreach-tasks`
   - 送样履约：`/influencers/sample-fulfillments`
7. 流程协同
   - 审批中心：`/workflow/approvals`
   - 异常中心：`/workflow/exceptions`
   - 协同回填：`/workflow/collaboration-events`
8. 业务协同
   - 新品市调：`/products/research`
   - 采购订单：`/purchasing/orders`
   - 供应链采购协同：`/supply-chain/purchase-orders`
   - 供应商绩效：`/suppliers/performance`
   - 价格中心：`/pricing/prices`
9. RPA协同
   - 任务中心：`/rpa/tasks`
   - 运行记录：`/rpa/runs`
   - 设备管理：`/rpa/devices`
   - 人工队列：`/rpa/manual-queue`
   - 稳定性：`/rpa/stability`
   - 账号串行锁：`/rpa/account-locks`
   - 页面签名：`/rpa/page-signatures`
10. API数据接入
    - 连接配置：`/integrations/configs`
    - 同步任务：`/integrations/sync-jobs`
    - 运行记录：`/integrations/sync-runs`
11. 财务中心
    - 财务导入：`/finance/imports`
    - 财务分析：`/finance/analytics`
    - 平台账单：`/finance/statements`
    - 提现记录：`/finance/withdrawals`
    - 银行到账：`/finance/bank-receipts`
    - 对账异常：`/finance/reconciliation/exceptions`
    - 对账差异：`/finance/reconciliation/matches`
12. 报表中心
    - 基础报表：`/reports/basic`
    - 报表导出：`/reports/exports`
13. 基础档案
    - 商品主数据：`/products/master`
    - 商品明细数据：`/products/details`
    - 分类设置：`/products/categories`
    - 属性设置：`/products/attributes`
    - 颜色设置：`/products/colors`
    - 规格设置：`/products/specifications`
    - 组合商品：`/products/bundles`
    - 平台档案：`/master-data/platforms`
    - 店铺档案：`/master-data/stores`
    - 仓库档案：`/master-data/warehouses`
    - 供应商档案：`/master-data/suppliers`
14. 系统治理
    - 组织架构：`/system/departments`
    - 用户目录：`/system/users`
    - 角色权限：`/system/roles`
    - 安全运维：`/system/security-operations`
    - 配置中心：`/settings/config-center`
    - 配置版本：`/settings/config-versions`
    - 平台准入：`/settings/platform-readiness`
    - 发布合同：`/releases/contracts`
    - 日志审计：`/audit/operations`
15. 治理与试点
    - API 合同：`/governance/api-contracts`
    - 助手治理：`/governance/assistants`
    - 试点准入：`/pilot/readiness`
    - 部署拓扑：`/pilot/topology`
    - 恢复演练：`/pilot/recovery`
    - 发布记录：`/pilot/releases`
    - 容量观察：`/pilot/capacity`
    - 试点控制台：`/pilot/control-room`
    - 专项安全评审：`/pilot/security-reviews`
    - 受控验证：`/pilot/verification-runs`
    - 性能验证：`/pilot/performance-runs`
    - 准入决策：`/pilot/entry-decisions`

固定位置规则：达人管理必须位于“经营决策”之后、“流程协同”之前。

## 3. 现有系统功能登记

### 产品与商品

- 产品开发需求、审核、项目、成本、销售、复盘和效能看板。
- 商品主数据、SPU/SKU、分类、属性、颜色、规格、组合商品。
- 商品生命周期、销售状态、状态建议、状态流转和清仓流程。
- 商品状态和权限名称使用中文显示映射，API 枚举值保持稳定。

### 全球刊登

- 全球刊登工作台、刊登任务、在线商品。
- 平台类目和商品属性映射。
- 刊登日志、刊登异常、刊登资料和模板。

### 达人管理

- 达人档案。
- 多目标达人建联、商品和店铺匹配、BD负责人、任务优先级和 PATCH 编辑。
- 送样履约、SKU数量、销售额、采购成本匹配、定价状态和履约汇总。
- 达人 V2.44.6 Reviewed 新增 21 个业务字段，仅位于达人数据模型。
- `influencers.0005` 和 `influencers.0006` 已登记并应用。

### 经营、协同与供应链

- 经营总览、销售分析、库存分析、库存预警、补货建议和经营预警。
- 审批、异常、协同回填。
- 新品市调、采购订单、供应链采购协同、供应商任务/发货/绩效和价格中心。

### RPA与数据接入

- RPA任务、运行记录、设备、人工队列、稳定性、账号锁和页面签名。
- 平台连接配置、同步任务、同步运行和 API 同步。

### 财务与报表

- 财务导入、平台账单、提现、银行到账、对账异常和差异。
- 财务分析、基础报表和报表导出。

### 基础档案与治理

- 平台、店铺、仓库和供应商档案。
- 组织、用户、角色权限、安全运维、配置版本、平台准入和发布合同。
- API合同、助手治理、试点准入、拓扑、恢复、发布、容量、控制台、安全评审、验证、性能和准入决策。

## 4. 权限与发布基线

- 唯一 Docker/Sudo 审核发布账号：`dfcy01`。
- `dev-a`：普通登录账号，无 Docker、无 sudo。
- `dev-b`：普通登录账号，无 Docker、无 sudo。
- 开发人员只提交代码、测试结果、迁移说明和发布包，不得直接发布到 VM。
- 所有发布必须由审核账号核对文件范围、菜单差异、测试、迁移计划和备份后执行。

## 5. 后续开发节点规则

1. 新功能必须从本登记提交或其后续受控提交创建分支。
2. 每个模块只能修改获授权的目录、菜单块、路由和权限。
3. 未获授权不得重命名、删除、移动其他菜单或修改其他模块界面。
4. 菜单调整必须提交调整前后结构、权限、路由和截图，重新取得授权。
5. 商品、权限、状态中文映射和全球刊登结构属于受保护基线，不得随模块增量回退。
6. 数据迁移必须先备份，检查迁移计划，并说明是否可逆及历史数据影响。
7. 发布前必须执行定向测试、前端全量测试、生产构建、Django system check 和运行时断言。
8. 发布镜像和 Compose 文件必须以审核版本为最后覆盖项，禁止追加未经审核的候选文件。
9. 发现非授权文件差异时停止合并和发布，重新申请授权。

## 6. 基线验证

- 前端达人定向测试：7/7。
- 前端全量测试：162/162。
- 生产构建：成功。
- Django system check：通过。
- 达人 21 字段运行时断言：通过。
- HTTPS：200。
- 全球刊登菜单及七条核心路由：保留。
- 商品表与商品页面：无 V2.44.6 非授权字段增量。
- 开发A、开发B Docker/Sudo权限：已撤销。

## 7. 变更登记要求

后续每个版本节点至少登记：版本号、父提交、负责人、授权范围、文件清单、菜单和路由差异、权限差异、迁移、备份、测试结果、镜像标签、部署时间和回退策略。
