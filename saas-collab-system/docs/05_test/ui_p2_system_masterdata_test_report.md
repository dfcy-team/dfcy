# UI-P2 系统治理与基础档案测试报告

## 1. 测试范围

- 组织、用户、角色、权限目录和安全运维接口。
- 平台、店铺、仓库和供应商基础档案接口。
- tenant 隔离、internal/external/RPA 用户类型边界和 action permission。
- 数据脱敏、审计日志、tenant 内唯一性、启停与引用保护。
- Mock/API 切换、路由能力、操作按钮双重校验和页面完整状态。

## 2. 后端专项结果

| 检查 | 结果 | 证据 |
|---|---|---|
| `python manage.py check` | PASS | System check identified no issues |
| `makemigrations --check --dry-run` | PASS | No changes detected |
| UI-P2 专项 pytest | PASS | 19 passed in 14.22s |
| 全量后端 pytest | PASS | 271 passed in 20.17s |

专项测试覆盖：用户列表 tenant 过滤与脱敏、permission 对应 scope 缺失时拒绝、`own/department/custom/all` 范围过滤、目标用户与可分配角色范围、用户角色绑定审计、角色第二页与总数、只读权限禁止写操作、组织唯一性与跨 tenant 父级拒绝、角色 permission/data scope 更新审计、基础档案列表/详情/状态范围、平台与供应商引用保护、供应商联系方式脱敏以及安全运维凭据边界。

## 3. 前端专项结果

| 检查 | 结果 | 证据 |
|---|---|---|
| UI-P2 专项 Vitest | PASS | 1 file，8 tests passed |
| 全量前端 Vitest | PASS | 4 files，69 tests passed |
| `npm run build` | PASS | 1903 modules transformed |
| 第三方 PURE 注释提示 | P2观察 | 来自 `@vueuse/core`，不阻断构建 |

专项测试覆盖：8 条 UI-P2 路由与 action permission、专用可分配角色目录、用户角色绑定和角色新建请求前二次校验、角色分页、严格 capability 状态、system/master-data 接口分区、脱敏字段、六层权限说明以及高风险自动化禁止项。

## 4. 页面实测

| 页面 | 结果 | 核验内容 |
|---|---|---|
| `/system/roles` | PASS | 六层权限、角色、权限数量、data scope 和动作入口完整 |
| `/system/security-operations` | PASS | 凭据只显示别名、指纹、版本和状态；无敏感明文 |
| `/master-data/suppliers` | PASS | 搜索、状态、分页、脱敏联系方式和启停入口完整 |
| 桌面视口 1440x900 | PASS | 无横向溢出，菜单、顶栏、标题和表格未重叠 |
| 移动视口 390x844 | PASS | `innerWidth=clientWidth=scrollWidth=390`，标题换行、退出入口和操作列完整 |

## 5. 全量回归

- 后端全量测试：271 passed。
- 前端全量测试：4 files、69 tests passed。
- 前端生产构建：1903 modules transformed，构建成功。
- `git diff --check`：通过；仅输出 Windows 工作区 LF/CRLF 转换提示。
- 安全扫描：命中项为加密字段名、测试占位值和禁止明文说明，未发现真实凭据。
- 浏览器真实认证态联调仍需使用受控 Pilot 账号和隔离测试数据，不使用生产凭据。

## 6. P2观察项

- 生产凭据托管和轮换目前仅展示引用元数据，完整运维流程待专项设计。
- 浏览器认证态 E2E 尚未配置专用测试账号与隔离数据。
- 移动端数据表采用横向表格容器，后续可按高频字段设计紧凑卡片视图。

## 7. 当前结论

UI-P2 四项 P1 已完成定向整改，专项与全量代码检查、测试和构建均通过，具备进入架构 R2 复审的条件。R1 报告作为原始审核记录保留，不回写其结论。
