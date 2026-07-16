# UI-P2 系统治理与基础档案接口合同

## 1. 合同目标

UI-P2 统一系统治理、角色权限和基础档案的内部后台接口。所有接口仅允许 `internal` 用户访问，并以当前认证用户的 `tenant` 为数据边界。前端权限判断只控制页面与动作呈现，后端权限、tenant 和 data scope 校验是最终安全边界。

## 2. 统一响应

成功响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

列表数据位于 `data.results`，同时返回 `count`、`next` 和 `previous`。失败响应继续使用统一异常处理器，返回 `success=false`、错误码、消息和 `data=null` 或字段校验详情。

## 3. 系统治理接口

| 资源 | 方法与路径 | 读取权限 | 写入权限 | 关键边界 |
|---|---|---|---|---|
| 组织架构 | `GET/POST /api/internal/system/departments/` | `system.organization.view` | `system.organization.manage` | tenant 内名称与父级关系；跨 tenant 父级拒绝 |
| 用户目录 | `GET/POST /api/internal/system/users/` | `system.users.view` | `system.users.manage` | 仅 internal 用户；联系方式脱敏；初始密码只写 |
| 用户状态 | `POST /api/internal/system/users/{id}/status/` | `system.users.view` | `system.users.manage` | 禁止停用当前登录用户；写审计日志 |
| 用户角色 | `PUT /api/internal/system/users/{id}/roles/` | `system.users.view` | `system.users.manage` | 角色必须属于当前 tenant；写审计日志 |
| 可分配角色目录 | `GET /api/internal/system/user-role-options/` | `system.users.manage` | 不开放 | 只返回当前操作人 data scope 明确允许分配的启用角色；不依赖 `system.roles.view` |
| 角色 | `GET/POST /api/internal/system/roles/` | `system.roles.view` | `system.roles.manage` | tenant 内角色编码唯一 |
| 角色权限 | `PUT /api/internal/system/roles/{id}/permissions/` | `system.roles.view` | `system.roles.manage` | 同步 permission 与 data scope；写审计日志 |
| 权限目录 | `GET /api/internal/system/permissions/` | `system.roles.view` | 不开放 | 权限码为后端可信目录 |
| 安全运维 | `GET /api/internal/system/security-operations/` | `security.operations.view` | 不开放 | 只返回凭据别名、指纹、版本、状态与验证时间 |

角色权限采用六层合同：Tenant、用户类型、角色、Permission、Data scope、字段与流程。任一层不满足时，后端必须拒绝请求。

### 3.1 Data scope 执行语义

- Data scope 必须来自实际授予当前 permission 的启用角色；其他角色的 scope 不得扩大当前 permission。
- 只有 permission 而没有对应 Data scope 时返回 `403`，不得退化为 tenant 全量访问。
- `all`：允许访问当前 tenant 的全部目标资源。
- `own`：用户目录只允许当前用户；组织目录只允许当前用户所属部门；角色目录只允许当前用户已绑定角色。
- `department`：用户与角色按当前用户所属部门过滤；组织目录只返回当前部门。
- `custom`：系统治理使用 `user_ids`、`department_ids`、`role_ids`；基础档案使用 `platform_ids`、`store_ids`、`warehouse_ids`、`supplier_ids`。
- 创建根组织、创建无部门用户、新建角色、维护角色权限和安全运维汇总要求对应 permission 具备 `all` scope。
- 用户角色绑定同时校验目标用户范围和可分配角色范围；`all` 可分配 tenant 内启用角色，`custom` 仅可分配 `role_ids`，`own/department` 不自动获得角色提权能力。
- 列表、详情、更新、启停和角色绑定必须执行相同范围，不允许只过滤列表。

## 4. 基础档案接口

资源名仅允许 `platforms`、`stores`、`warehouses`、`suppliers`：

| 方法与路径 | 读取权限 | 写入权限 | 说明 |
|---|---|---|---|
| `GET /api/internal/master-data/{resource}/` | `masterdata.view` | - | 当前 tenant 列表、搜索、状态筛选和分页 |
| `POST /api/internal/master-data/{resource}/` | - | `masterdata.manage` | 创建档案，code 在 tenant 内唯一 |
| `GET /api/internal/master-data/{resource}/{id}/` | `masterdata.view` | - | 仅返回当前 tenant 对象 |
| `PATCH /api/internal/master-data/{resource}/{id}/` | - | `masterdata.manage` | 更新档案并写审计日志 |
| `POST /api/internal/master-data/{resource}/{id}/status/` | - | `masterdata.manage` | 启停档案并执行引用保护 |

引用保护至少包括：存在启用店铺时不得停用平台；存在进行中供应商任务时不得停用供应商。供应商邮箱和电话只返回脱敏字段，写入字段不得在响应中回显。

## 5. 错误状态

- `400`：请求结构、分页、字段格式或 tenant 内唯一性校验错误。
- `401`：未认证或会话失效。
- `403`：用户类型、权限、tenant 或 data scope 不满足。
- `404`：资源、对象不存在或不属于当前 tenant。
- `409`：引用保护、重复状态操作或当前状态冲突。
- `422`：跨字段业务规则校验失败。

## 6. 前端状态与动作

- `VITE_USE_MOCK=true`：使用 UI-P2 示例数据，不连接真实后端。
- `VITE_USE_MOCK=false`：调用上述接口；只有完成受控 Pilot 联调后才可标记 `connected`。
- 所有创建、启停、分配角色和配置权限动作在展示前检查 action permission，在发送请求前再次检查。
- 无权限动作隐藏或禁用；后端仍需再次拒绝越权请求。
- 页面 capability 初始为 `mock` 或 `pending`；仅由真实成功响应中的 `api_status=connected` 设置为已连接，网络 fallback 为 `degraded`，HTTP 失败不得保留 `connected`。

## 7. 安全边界

- 不返回密码、Token、Cookie、Session、API Key、API Secret 或凭据密文。
- 不在配置中心或安全运维页面提供真实密钥输入与明文查看能力。
- 不接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 不启用自动采购、自动改价、清仓、停售、归档、真实 RPA 或资金操作。
