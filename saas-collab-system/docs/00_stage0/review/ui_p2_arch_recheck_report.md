# UI-P2-ARCH-R1 系统治理与基础档案架构复审报告

## 1. 复审对象

- 任务：`UI-P2-ARCH-R1`
- 复审日期：2026-07-16
- 项目根目录：`saas-collab-system/`
- 当前分支：`feature/ui-p2-system-admin-master-data`
- 当前 `HEAD`：`1b019ec69cf3e826727eef50e3e76923fe11c68e`
- 对比基线：`origin/main`，同为 `1b019ec69cf3e826727eef50e3e76923fe11c68e`
- 复审对象：当前工作区内尚未提交的 UI-P2 后端、前端、测试与合同文档成果
- 复审性质：只审核，不修复业务代码

工作区另有 `docs/00_stage0/architecture/` 和 `docs/01_architecture/` 下的既有未跟踪 DOCX 文件；这些文件不属于 UI-P2 实现，也未纳入本次结论或发生修改。

## 2. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：4 项未关闭。
- P2：3 项非阻断观察项。
- 工程检查、专项测试、全量回归和前端构建均通过，但测试通过不能替代未落地的 `data_scope`、动作权限和页面状态合同。

根据复审规则，无 P0 但仍存在 P1，因此不能判定 PASS。

## 3. 总体结果

| 复审域 | 结果 | 摘要 |
|---|---|---|
| 分支与文件范围 | PASS | UI-P2 变更位于预期后端、前端、测试和文档范围；既有 DOCX 已排除 |
| tenant 隔离 | PASS | 系统治理和基础档案查询、详情及状态操作均以当前用户 tenant 过滤 |
| 用户类型与 Permission | PASS | internal + 明确 `view/manage` 权限；无权限、external、RPA 均被拒绝 |
| Data scope | FAIL（P1） | 角色范围可配置和回显，但未应用到新接口查询与对象访问 |
| 脱敏与凭据边界 | PASS | 用户和供应商联系方式脱敏；初始密码只写；安全运维仅返回凭据元数据 |
| 审计与引用保护 | PASS | 用户、角色、档案写操作有审计；平台和供应商停用有引用保护 |
| 路由默认拒绝 | PASS | 8 条 UI-P2 路由均登记 capability，未登记非公开路径默认拒绝 |
| 前端动作权限 | FAIL（P1） | 通用创建/启停和权限保存具备双检；角色新建及用户角色绑定流程不完整 |
| 页面完整状态 | FAIL（P1） | 通用档案页状态完整；角色列表缺少分页，连接状态存在提前标记问题 |
| Mock/API 边界 | 部分通过 | Mock/API 切换有效；角色和安全运维初始状态可能误显示“已连接” |
| 安全与高风险边界 | PASS | 未发现真实平台、真实凭据、真实业务数据或高风险自动化 |

## 4. 系统治理复审

### 4.1 已通过项

1. `DepartmentCollectionView`、`UserCollectionView`、`RoleCollectionView` 和 `SecurityOperationsView` 均按 `request.user.tenant` 查询。
2. `DeclaredApplicationPermission` 同时要求认证、`internal` 用户类型和声明的 action permission。
3. 读取与写入分别使用 `system.organization.view/manage`、`system.users.view/manage`、`system.roles.view/manage` 和 `security.operations.view`。
4. 用户响应只包含 `email_masked`、`phone_masked`；`initial_password` 为 `write_only`，创建审计只记录用户名和状态。
5. 用户启停、用户角色更新、角色创建、角色权限与 data scope 更新均写入 tenant 审计日志。
6. 安全运维接口仅查询凭据别名、平台、环境、状态、指纹、密钥版本和验证时间，未返回 `credential_ciphertext` 或明文凭据。

### 4.2 未通过项

角色 `DataScope` 目前只在 `RolePermissionView` 中保存，在 `RoleAdminSerializer` 中回显；`DeclaredApplicationPermission` 只调用 `check_user_permission()`，系统治理和基础档案查询未调用 `get_user_data_scope()` 或等价过滤器。

独立动态探针创建了 `scope_type=own` 的 `system.users.view` 角色。该用户请求 `/api/internal/system/users/` 时返回：

```text
status=200
scope=own
returned_usernames=['other-visible-user', 'scope-viewer']
```

这证明 `own` 范围的用户仍可读取同 tenant 的其他用户，与冻结合同“后端 data scope 为最终安全边界”不一致。

## 5. 基础档案复审

### 5.1 已通过项

1. 平台、店铺、仓库和供应商模型均具备 `tenant` 外键，并具有 `(tenant, code)` 数据库唯一约束。
2. 列表、详情、PATCH 更新和状态变更均通过当前 tenant 获取对象；跨 tenant 对象表现为不可见。
3. 店铺序列化器校验所引用平台属于当前 tenant。
4. 平台存在启用店铺、供应商存在进行中任务时，停用返回 `409`，状态不发生变化。
5. 创建、更新和状态变更均写入 tenant 审计日志；前端停用/启用前有确认对话框。
6. 供应商邮箱和电话为只写输入、脱敏输出，接口响应不包含明文字段。
7. Mock 数据均为 `demo`、`示例`、`example.com` 等占位值。

### 5.2 待整改项

基础档案接口同样只按 tenant 过滤，未执行角色的 `all/department/own/custom` data scope。若该模块设计为 tenant 全量可见，应在合同中明确 `masterdata.view/manage` 只允许 `all` 范围；否则必须定义平台、店铺、仓库和供应商的自定义范围字段并在列表、详情、更新和状态操作中一致执行。

## 6. 前端复审

### 6.1 已通过项

1. 4 条系统治理路由和 4 条基础档案路由均登记 capability，并限定 `internal` 用户类型及对应 `view` 权限。
2. 全局路由合同覆盖所有非公开路由，未知路径由 `canAccessPath()` 默认拒绝。
3. `AdminResourcePage` 在按钮展示、打开创建对话框、提交创建和状态请求前均校验后端 action permission。
4. 通用资源页具备 loading、empty、error、列表、分页和详情抽屉状态。
5. `VITE_USE_MOCK=true` 只走 Mock；`false` 调用冻结的 `/api/internal/system/*` 和 `/api/internal/master-data/*` 路径。
6. API 封装未调用 `/admin/`、`/api/rpa/*` 或 `/api/finance/*`。

### 6.2 未通过项

1. `RolePermissionMatrix.vue` 的 `saveRole()` 在请求前检查 `system.roles.manage`，但 `submitRole()` 直接调用 `createRole()`，缺少同样的请求前二次校验。
2. `systemAdmin.js` 已提供 `updateUserRoles()`，但 `UserDirectory.vue` 未提供角色分配入口，因此“用户角色绑定”流程尚未完成，也无法验证其页面 action permission 双检。
3. 角色接口为分页接口，但角色页只调用默认第一页且没有分页控件；超过首 20 条的角色无法进入查看或配置流程。
4. `RolePermissionMatrix.vue` 和 `SecurityOperations.vue` 将 capability 初始值设为 `connected`。真实请求尚未完成或请求失败时，页面仍可能显示“已连接”；fallback 也未统一映射为 `degraded`。这不满足待联调接口不得提前标记生产 connected 的要求。

## 7. 独立执行结果

| 检查 | 实际结果 | 结论 |
|---|---|---|
| `python manage.py check` | `System check identified no issues (0 silenced)` | PASS |
| `python manage.py makemigrations --check --dry-run` | `No changes detected` | PASS |
| UI-P2 后端专项 pytest | `10 passed in 8.53s` | PASS |
| 后端全量 pytest | `262 passed in 17.17s` | PASS |
| Data scope 动态探针 | `own` 用户可见同 tenant 其他用户 | 复现 P1 |
| UI-P2 前端专项 Vitest | `1 file, 7 tests passed` | PASS |
| 前端全量 Vitest | `4 files, 68 tests passed` | PASS |
| `npm run build` | `1902 modules transformed`，构建成功 | PASS |
| 路由静态扫描 | 8 条 UI-P2 路由均有 capability；未知路由测试为拒绝 | PASS |
| 动作权限静态扫描 | 通用创建/启停与权限保存有双检；角色新建缺请求前复核 | 复现 P1 |
| 状态合同扫描 | 两个系统页初始值为 `connected` | 复现 P1 |
| `git diff --check` | 无空白错误，仅有 LF/CRLF 工作区提示 | PASS |
| Git 范围检查 | UI-P2 代码范围符合预期；既有未跟踪 DOCX 已排除 | PASS |

## 8. 安全扫描结果

1. 未发现提交中的真实 `.env`、私钥、证书、账号、密码、Token、Cookie、Session、API Key 或 API Secret。
2. 本地存在被忽略的 `backend/db.sqlite3`，当前无业务表且未被 Git 跟踪；仓库只跟踪 `.env.example` 类示例文件。
3. 密钥形态扫描仅命中 `package-lock.json` 的依赖完整性哈希；不是凭据。
4. UI-P2 源码中的密码、session 和凭据命中均为 `not-a-real-*`、`mock-*` 或禁止明文的说明文本。
5. 未发现真实 BigSeller、Shopee、TikTok/TK、银行或支付连接地址。
6. 未发现自动采购、自动改价、自动清仓、自动停售、自动归档、真实 RPA 或资金操作。
7. 前端权限仍只是呈现控制，后端 Permission 与 tenant 校验有效；但后端 data scope 缺口必须在收尾前关闭。

## 9. P0 问题

无。

## 10. P1 问题

| 编号 | 问题 | 证据 | 整改验收标准 |
|---|---|---|---|
| UI-P2-P1-001 | 系统治理和基础档案未执行后端 data scope | `api_permissions.py` 只检查 Permission；`system_views.py`、`masterdata/views.py` 只按 tenant 过滤；动态探针复现 `own` 可见他人 | 定义各资源 scope 语义；列表、详情、写入和状态操作执行同一范围；补充 `all/department/own/custom`、跨范围 403/404 和越权测试 |
| UI-P2-P1-002 | 角色与用户角色动作合同不完整 | `RolePermissionMatrix.vue::submitRole()` 无请求前 `manageAccess` 检查；`updateUserRoles()` 未被页面使用 | 新建角色请求前再次校验 `system.roles.manage`；用户目录提供受 `system.users.manage` 控制的角色绑定流程；展示和请求前均双检，并补组件测试 |
| UI-P2-P1-003 | 角色权限页未消费分页合同 | `fetchRoles()` 使用默认分页，页面无 `el-pagination`，只能访问首批角色 | 保存 `count/page/page_size`，提供分页和翻页加载；验证空页、最后一页和超过 20 条角色场景 |
| UI-P2-P1-004 | 连接状态存在提前或错误标记 | 角色权限、安全运维页面 capability 初始为 `connected`，失败分支不重置，fallback 未映射 `degraded` | 初始按 `useMock ? mock : pending`；仅真实成功响应设 `connected`；网络 fallback 设 `degraded`；HTTP 失败不得保留 connected，并补状态测试 |

## 11. P2 问题

1. UI-P2 专项测试未覆盖 data scope 实际过滤、角色新建二次校验、用户角色绑定和连接状态失败分支。
2. 同 code 跨 tenant 允许、店铺跨 tenant 平台拒绝主要由模型/序列化器静态证据确认，建议补充显式回归用例。
3. 前端构建存在 `@vueuse/core` 第三方 `PURE` 注释警告，不阻断本阶段；浏览器认证态 E2E 仍应在隔离 Pilot 数据下补充。

## 12. 整改建议

1. 先冻结 UI-P2 资源的 data scope 映射。系统用户建议支持 `own/department/all/custom user_ids`；基础档案建议支持明确的 `platform_ids/store_ids/warehouse_ids/supplier_ids`，或明确只允许 `all` scope。
2. 抽取后端统一 scope 过滤与对象访问函数，避免列表已过滤而详情、PATCH、状态端点遗漏。
3. 完成用户角色绑定页面，并统一使用 `getActionAccess()` 在展示与请求前双检。
4. 为角色页接入后端分页；统一系统页 capability 初始化、成功、失败和 fallback 状态机。
5. 增加针对以上四项 P1 的后端和前端测试，然后执行 `UI-P2-ARCH-R2`。

## 13. 收尾与下一阶段建议

1. **是否允许 UI-P2 正式收尾：不允许。** 四项 P1 尚未关闭。
2. **是否允许进入下一阶段界面设计：仅允许文档和原型准备，不允许正式开发或合并实现。** 应先完成 UI-P2 整改并通过 `UI-P2-ARCH-R2`。
3. 本次复审未修改 `backend/`、`frontend/`、`rpa-agent/` 或其他业务代码，仅新增本报告。
