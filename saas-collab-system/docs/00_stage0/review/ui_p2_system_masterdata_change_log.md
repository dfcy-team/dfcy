# UI-P2 系统治理与基础档案变更记录

## 1. 任务信息

- 阶段：UI-P2
- 分支：`feature/ui-p2-system-admin-master-data`
- 日期：2026-07-16
- 目标：在 UI-P1 可信会话和权限骨架上实现系统治理、六层权限和基础档案的 Mock/API 双模式页面。

## 2. 系统治理

- 新增组织架构、用户目录、角色权限和安全运维页面。
- 新增组织、用户、角色、权限目录和安全运维内部接口。
- 用户列表按 tenant 隔离，邮箱和手机号只返回脱敏字段。
- 角色权限同时维护 Permission 与 Data scope，并记录操作审计。
- 页面展示 Tenant、用户类型、角色、Permission、Data scope、字段与流程六层权限合同。
- 安全运维只返回凭据别名、指纹、版本、状态和验证时间，不返回密文或明文凭据。

## 3. 基础档案

- 新增平台、店铺、仓库和供应商档案模型、迁移、序列化器和接口。
- 档案 code 在 tenant 内唯一，所有查询和详情均按当前 tenant 过滤。
- 新增统一列表、详情、创建、搜索、分页和启停页面骨架。
- 平台存在启用店铺时禁止停用；供应商存在进行中任务时禁止停用。
- 供应商联系人邮箱和手机号仅脱敏回显。

## 4. 权限与路由

- 新增 `system.organization.view/manage`、`system.users.view/manage`、`system.roles.view/manage`、`masterdata.view/manage`、`security.operations.view` 权限码。
- 新增权限目录种子迁移。
- 8 条 UI-P2 路由全部登记 route capability，未知非公开路径继续默认拒绝。
- 创建、启停、角色配置等动作使用后端 action permission，并在展示和请求前双重校验。

## 5. 前端体验

- 新增“基础档案”和扩展后的“系统治理”菜单。
- 新增通用 `AdminResourcePage`，统一 loading、empty、error、列表、分页、详情抽屉、创建和状态确认。
- 保留 `VITE_USE_MOCK`，Mock 模式不连接真实后端；真实模式按冻结合同调用内部接口。
- 桌面端已实测角色权限、安全运维和供应商档案，无页面重叠或横向溢出。

## 6. 测试与验证

- 新增后端 UI-P2 tenant、权限、脱敏、唯一性、引用保护和审计测试。
- 新增前端 UI-P2 路由、动作权限、接口分区、脱敏和高风险边界测试。
- 测试结果记录于 `docs/05_test/ui_p2_system_masterdata_test_report.md`。

## 7. 安全确认

- 未提交真实 `.env`、账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未提交真实供应商、订单、财务、银行或平台数据。
- 未接入真实平台、银行或支付系统。
- 未新增真实 RPA 脚本或启用高风险自动化。
- 前端权限仅改善体验，后端 tenant、data scope 与 Permission 校验仍为最终边界。

## 8. 待复审事项

- 架构员需复核六层权限合同、UI-P2 action permission、tenant 隔离、脱敏和引用保护。
- 受控 Pilot 环境需在 `VITE_USE_MOCK=false` 下复验真实登录后的系统治理与基础档案接口。
- 生产凭据托管、轮换、撤销和浏览器认证态 E2E 仍需后续专项设计。

## 9. R1 P1 定向整改

- `UI-P2-P1-001`：后端权限声明层要求 permission 对应 Data scope；系统用户、部门、角色和基础档案均按 `all/department/own/custom` 执行列表、对象和写操作范围。
- `UI-P2-P1-002`：角色新建与用户角色绑定均在展示和请求前校验 action permission；新增 `/api/internal/system/user-role-options/`，并在后端同时限制目标用户与可分配角色，防止直接调用 API 绕过。
- `UI-P2-P1-003`：角色权限页消费 `count/page/page_size`，提供分页控件，保留空页返回上一页的操作入口；后端测试覆盖超过 20 条角色的第二页。
- `UI-P2-P1-004`：页面初始状态统一为 `mock/pending`；只有真实 API 成功并带 `api_status=connected` 才显示已连接，网络 fallback 映射为 `degraded`，HTTP 失败不保留 connected。
- R1 报告不做回写或改结论；以上整改等待 `UI-P2-ARCH-R2` 独立复审。
