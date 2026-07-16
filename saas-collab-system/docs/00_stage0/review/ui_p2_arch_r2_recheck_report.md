# UI-P2-ARCH-R2 系统治理与基础档案整改复审报告

## 1. 复审对象

- 任务：`UI-P2-ARCH-R2`
- 复审日期：2026-07-16
- 项目根目录：`saas-collab-system/`
- 当前分支：`feature/ui-p2-system-admin-master-data`
- 当前 `HEAD`：`1b019ec69cf3e826727eef50e3e76923fe11c68e`
- 对比基线：`origin/main`，同为 `1b019ec69cf3e826727eef50e3e76923fe11c68e`
- 复审对象：当前工作区内 UI-P2 四项 P1 整改代码、测试和合同文档
- 复审性质：独立审核，不修改业务代码

工作区中的 UI-P2 成果尚未提交；`docs/00_stage0/architecture/` 和 `docs/01_architecture/` 下既有未跟踪 DOCX 不属于本次复审对象，未读取、修改或纳入安全结论。

## 2. 复审结论

**PASS**

- P0：无。
- P1：无，R1 的 4 项 P1 均已关闭。
- P2：3 项非阻断观察项。
- 后端检查、迁移一致性、专项与全量 pytest、前端专项与全量 Vitest、生产构建、路径与安全扫描均独立执行通过。

根据复审规则，无 P0/P1，因此结论为 PASS。

## 3. 原 P1 关闭情况

| 原P1编号 | 问题 | 是否关闭 | 独立证据 | 备注 |
|---|---|---|---|---|
| UI-P2-P1-001 | 后端未执行 Data scope | 是 | `services.py::get_permission_data_scopes`、`api_permissions.py::DeclaredApplicationPermission`、`ui_p2_scopes.py`、系统与基础档案 views、后端专项测试 | permission 与 scope 同授权链；缺 scope 返回 403；列表、对象和写操作执行范围 |
| UI-P2-P1-002 | 角色与用户角色动作合同不完整 | 是 | `RolePermissionMatrix.vue`、`UserDirectory.vue`、`/api/internal/system/user-role-options/`、`UserRoleView`、审计测试 | 展示和请求前双检；目标用户和可分配角色均由后端限制 |
| UI-P2-P1-003 | 角色页未消费分页 | 是 | `RolePermissionMatrix.vue` 的 `page/pageSize/total` 与 `el-pagination`；第二页后端测试 | 超过 20 条角色可访问第二页；空页保留返回有效页的分页入口 |
| UI-P2-P1-004 | 连接状态提前或错误标记 | 是 | `request.js`、`AdminResourcePage.vue`、`RolePermissionMatrix.vue`、`SecurityOperations.vue` 与前端专项测试 | Mock、pending、connected、degraded 分支已区分，HTTP 失败不保留 connected |

## 4. Data scope 复审

### 4.1 授权链

1. `get_permission_data_scopes()` 只查询当前 tenant、当前用户、启用角色且该角色实际包含指定 permission 的 Data scope。
2. `DeclaredApplicationPermission` 同时要求认证、`internal`、action permission 和非空的 permission 对应 scope。
3. 超级管理员获得当前 tenant 的显式 `all` scope；普通用户不存在“有 permission 即默认全量”的退化路径。
4. 专项用例验证只有 permission、没有 Data scope 时访问用户目录返回 `403`。

### 4.2 系统治理范围

- 用户：`own` 仅本人；`department` 为当前部门用户；`custom` 支持 `user_ids/department_ids`；`all` 为当前 tenant。
- 部门：`own/department` 仅当前部门；`custom` 使用 `department_ids`；根部门创建要求 `all`。
- 角色：`own` 为已绑定角色；`department` 为当前部门用户绑定角色；`custom` 使用 `role_ids`；角色创建和 permission/scope 维护要求 `all`。
- 用户创建、状态变更和角色绑定均先通过目标用户范围过滤。
- 安全运维聚合显式要求 `security.operations.view` 的 `all` scope。

### 4.3 基础档案范围

`MASTER_DATA_SCOPE_KEYS` 固定映射：

- `platforms -> platform_ids`
- `stores -> store_ids`
- `warehouses -> warehouse_ids`
- `suppliers -> supplier_ids`

列表、详情、PATCH 和状态变更调用同一个资源范围过滤器；新建档案要求 `masterdata.manage` 的 `all` scope。店铺引用平台还会按当前 tenant 和 `platform_ids` 复核。专项测试验证自定义平台范围的列表、详情、状态和创建边界，以及跨 tenant 引用拒绝。

结论：UI-P2-P1-001 已关闭。

## 5. 角色动作权限流程复审

1. 新建角色按钮使用 `system.roles.manage` 控制；`submitRole()` 在发请求前再次检查 `manageAccess.allowed`。
2. 用户目录提供“分配角色”入口；打开角色对话框和保存前均重新检查 `system.users.manage`。
3. 可分配角色使用专用 `GET /api/internal/system/user-role-options/`，该接口声明 `system.users.manage`，不依赖 `system.roles.view`。
4. 后端角色绑定先按 `system.users.manage` scope 获取目标用户，再按同 permission 的 `all` 或 `custom.role_ids` 获取可分配启用角色；范围外角色返回 `403`，范围外用户返回 `404`。
5. `own/department` scope 不自动取得任意角色分配权，避免仅凭用户可见范围产生角色提权。
6. 用户角色变更写入 `user_roles_update` 审计；角色 permission/Data scope 变更审计包含变更前后 permission 与 scope config。
7. 专项测试验证仅有 `system.users.manage`、没有 `system.roles.view` 时流程可用，并验证 API 直接提交范围外用户或角色无法绕过。

结论：UI-P2-P1-002 已关闭。

## 6. 角色分页复审

1. 角色页维护 `page=1`、固定 `pageSize=20` 和后端 `count`。
2. 请求显式传递 `page/page_size/search`，搜索时回到第一页。
3. `el-pagination` 绑定当前页、总数和翻页加载。
4. 当当前页因数据变化返回空状态时，只要已有 `total`，分页入口仍保留，可返回有效页。
5. 后端专项用例创建 25 个附加角色，验证第二页响应 `count=26`、6 条结果、存在 previous 且 next 为空。

结论：UI-P2-P1-003 已关闭。

## 7. 连接状态复审

1. 通用资源页、角色页和安全运维页初始 capability 均为 `useMock ? 'mock' : 'pending'`。
2. Mock 响应携带 `status=mock`，不会显示 connected。
3. 真实 Axios 成功响应由 `requestApi()` 注入 `api_status=connected`；页面不再以缺省成功直接猜测 connected。
4. 无 HTTP 响应的网络失败才允许回退 Mock，并写入 `api_status=fallback`，页面映射为 degraded。
5. 具有 HTTP 状态的 401/403/404/409/422 不执行 Mock fallback，页面 capability 设置为 pending，并由完整状态组件显示认证、权限、空数据、冲突或校验状态。
6. 静态扫描未发现 UI-P2 页面使用 `ref('connected')`、`status || 'connected'` 或无标识成功即 connected 的旧模式。

结论：UI-P2-P1-004 已关闭。

## 8. 独立执行结果

| 检查 | R2实际结果 | 结论 |
|---|---|---|
| `python manage.py check` | `System check identified no issues (0 silenced)` | PASS |
| `python manage.py makemigrations --check --dry-run` | `No changes detected` | PASS |
| UI-P2 后端专项 pytest | `19 passed in 13.17s` | PASS |
| 后端全量 pytest | `271 passed in 19.55s` | PASS |
| UI-P2 前端专项 Vitest | `1 file / 8 tests passed` | PASS |
| 前端全量 Vitest | `4 files / 69 tests passed` | PASS |
| `npm run build` | `1903 modules transformed`，构建成功 | PASS |
| UI-P2 API 路径扫描 | 未发现 `/admin/`、`/api/rpa/`、`/api/finance/` | PASS |
| 路由合同扫描 | 8 条 UI-P2 路由均登记 internal + view permission；未知路径默认拒绝 | PASS |
| 状态标记扫描 | connected 仅在真实请求成功注入；fallback 为 degraded | PASS |
| `git diff --check` | 无空白错误；仅 Windows LF/CRLF 提示 | PASS |
| 生成物检查 | `frontend/dist/`、`frontend/node_modules/` 均被忽略 | PASS |

## 9. 安全扫描结果

1. 私钥头、AWS Key 形态和长 `sk-*` Token 扫描无命中。
2. Git 跟踪的环境文件仅为根目录、frontend 和 rpa-agent 的 `.env.example`。
3. 平台 URL 扫描命中均为历史审核报告中的 `example.com` 示例说明，不是真实平台配置。
4. UI-P2 前端 API 与页面未访问 `/admin/`、RPA Agent 执行接口或财务接口。
5. `rpa-agent/` 与 `docs/04_rpa/` 无本次工作区变更。
6. 未发现真实平台、真实凭据、真实供应商/订单/财务数据或高风险自动化。
7. 范围外的未跟踪 DOCX 未纳入内容扫描，提交时必须继续排除或另行审核。

## 10. P0 问题

无。

## 11. P1 问题

无。R1 四项 P1 均已关闭。

## 12. P2 问题

1. 浏览器真实认证态 E2E 尚未在隔离 Pilot 数据与专用测试账号下执行；不影响本次代码与合同复审结论。
2. 前端构建仍有 `@vueuse/core` 第三方 `PURE` 注释位置提示，构建成功，不阻断 UI-P2。
3. UI-P2 成果当前仍为未提交工作区；提交时必须精确限定 UI-P2 文件，排除两组既有未跟踪 DOCX，并在 PR 中保留本报告和测试证据。

## 13. 收尾结论

1. **是否允许 UI-P2 正式收尾：允许。** 四项原 P1 已关闭，可进入提交、PR 和合并流程。
2. **是否允许进入下一阶段界面设计：允许，但应在 UI-P2 PR 合并最新 main 后创建下一阶段分支。** 不应基于未提交工作区或旧分支继续正式开发。
3. 本次 R2 仅新增本报告，未修改 `backend/`、`frontend/`、`rpa-agent/` 或其他业务代码。
