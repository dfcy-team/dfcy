# 系统角色权限与组织树改造验收登记（V2.44.68 候选增量）

## 状态与边界

- 登记日期：2026-09-06。
- 状态：**未发布**。本文件只记录候选工作树的实现与本地验证，不代表已合并、打包、部署或生产验收。
- 用户授权范围：系统管理、角色权限、组织架构、用户目录及其后端/API、迁移和测试；生产发布仍需独立审批。
- 唯一父基线：`22d5e04ece122f7d2d4d4a9ef81ac8edebd872cd`（`22d5e04`，V2.44.68 候选登记）。
- 候选工作分支：`codex/system-role-org-tree-management`。
- 当前工作树含未提交变更；本轮不创建提交、不发布、不操作生产环境或生产数据库。

## 本批次范围

### 阶段A：身份、角色与快速权限分配

- 平台 `is_superuser` 在界面显示为“平台超级管理员”，不作为可分配 Role；内置 `administrator` 显示为“租户管理员”，稳定 code 不变。
- 修复内置角色显示名：`002` 为“达人运营管理员”、`operations` 为“业务运营人员”、`product_developer` 为“产品开发人员”。
- Role 增加角色类型/保护标识，租户管理员保持不可编辑、删除、停用；内置业务角色、模板和自定义角色可区分显示。
- 提供可信模块权限包目录，四档权限仍展开并保存为 canonical `Role.permissions`；高风险权限必须额外明确确认，不因 `operate/admin` 自动获得。
- 角色权限矩阵支持“快速分配”和“高级配置”；未触及模块保留既有权限，`none` 会清理该模块权限及高风险项。

### 阶段B：组织范围、组织树与用户目录

- 新增 `department_tree` 数据范围：以使用者主部门为锚点递归包含下级；原 `department` 仍表示直属主部门范围。
- 新增租户隔离的组织树接口，保留原平铺部门接口；组织树返回节点状态、父级、子节点及按权限可见的人员计数。
- 用户列表支持 `department_id`、`include_descendants`、`unassigned` 筛选，主部门与兼任部门按去重后的组织匹配。
- 用户部门调整通过已有 UserDetail PATCH 能力，校验租户、数据范围并记录审计。
- 前端组织架构和用户目录共用 `DepartmentTree` 与树接口：树形管理、下级/直属切换、未分配节点、主部门/兼任部门编辑及字段权限隐藏均已接入。

## 迁移与权限目录同步

本批次只新增顺序迁移，不修改历史迁移：

1. `backend/apps/permissions/migrations/0042_role_metadata_and_display_names.py`：角色保护/类型字段及内置角色显示名安全修复。
2. `backend/apps/permissions/migrations/0043_datascope_department_tree.py`：新增 `DataScope.ScopeType.DEPARTMENT_TREE`，依赖 `0042`。

发布前必须在隔离数据库核对迁移头、回滚方案和现有租户数据；不得用回滚删除业务数据。权限目录必须与候选代码同步：

- 先按候选代码运行权限目录同步/校验命令（包括 `sync_permissions` 的 dry-run 或等价只读校验），确认稳定 permission code 未被重命名、删除或隐式授予。
- 核对角色权限包目录与 canonical `Role.permissions` 展开结果；新模块无权限包定义时应阻断发布，不得静默给普通角色补权。
- `administrator` 仅按既有目录同步例外；平台超级管理员身份不写入可分配角色列表。
- 核对 `0042`/`0043` 迁移文件的依赖头、迁移记录和权限目录版本一致，再执行正式迁移演练。
- 生产发布前保存租户级权限目录、角色、角色授权关系、用户角色关系和数据范围快照，发布后逐项比对并保留审计证据。

## 开发端、候选与生产 SHA 核对表

| 位置 | SHA / 状态 | 核对要求 |
| --- | --- | --- |
| 开发端 A | 待提供，未在本工作树中确认 | 提供完整提交 SHA、工作区状态及迁移/权限目录校验结果；不得只按标题或短分支名核对。 |
| 开发端 B | 待提供，未在本工作树中确认 | 提供完整提交 SHA、工作区状态及前后端测试结果；确认没有遗漏 `0042`/`0043` 或组织树接口。 |
| 候选版本 | **未生成独立提交 SHA**；当前为 `22d5e04` 基线上的未提交工作树 `codex/system-role-org-tree-management` | 候选打包前冻结工作树，生成唯一候选提交/镜像 SHA，并将该 SHA、迁移清单、权限目录快照和测试报告绑定。 |
| 生产版本 | **未提供、未部署** | 发布审批前不得填写或推断生产 SHA；由发布执行人以生产镜像/提交和数据库迁移记录回填。 |

### 开发端与发布后不一致处置

若发布后发现开发端 A、开发端 B、候选构建产物或生产实际版本不一致：

1. 立即冻结继续发布和权限目录自动同步，记录应用提交/镜像 SHA、数据库迁移头、权限目录版本及发布时间。
2. 以已审批的候选构建产物和本文件列出的迁移清单作为统一对照基准；不得用开发端临时分支或未审计本地文件覆盖线上状态。
3. 比较前端静态资源、后端代码、`0042`/`0043` 迁移、角色权限包目录和数据库迁移记录，形成差异清单；保留审计日志和权限快照。
4. 若生产缺少候选迁移或权限目录，先按受控流程补齐/校验；若生产多出未经批准的迁移或权限授予，暂停相关模块并由架构/安全负责人决定前向修复或回退应用版本。
5. 统一修正开发端 A/B、候选分支和发布登记，使三方指向同一候选 SHA 与迁移清单后，重新执行定向回归和发布门禁；生产 SHA 仅由实际发布账本回填。

## 验证命令与结果

以下命令均在候选工作树执行；验证不代表生产发布。

### 后端

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 角色快捷权限、组织树、权限拆分、租户管理员及权限目录模型 | `python -m pytest -q tests/test_role_quick_assignment.py tests/test_department_tree_management.py tests/test_role_permission_split.py tests/test_tenant_administrator_role.py tests/test_permission_catalog.py tests/test_permissions_models.py tests/test_tenants_accounts_models.py` | **通过：36 项** |
| auth API 精确响应回归 | `python -m pytest -q tests/test_auth_api.py` | **通过：8 项**；测试预期已纳入阶段A的 `role_labels`、`identity_label`。 |
| 后端全量回归 | `python -m pytest -q` | **通过：1064 项，跳过 28 项**（205.58 秒） |
| Django 系统检查 | `python manage.py check` | **通过：0 issues** |
| 迁移漂移检查 | `python manage.py makemigrations --check --dry-run` | **通过：No changes detected** |
| 权限目录一致性 | PowerShell `$env:DB_NAME=':memory:'; python -c "... migrate; sync_permissions --check ..."` | **通过：Permission catalog is complete**（临时内存库；未触碰开发/生产数据库） |

### 前端

| 检查 | 命令 | 结果 |
| --- | --- | --- |
| 步骤7组织树、角色权限 mock 包及系统管理专项 | `npm test -- --run tests/department-tree-management.spec.js tests/role-quick-assignment.spec.js tests/ui-p2-system-masterdata.spec.js` | **通过：3 个文件、22 项** |
| 前端全量测试（显式 Mock 写入模式） | `$env:VITE_USE_MOCK='true'; npm test -- --run --reporter=dot` | **通过：69 个文件、419 项** |
| 前端全量测试（未设置 `VITE_USE_MOCK` 的默认模式） | `npm test -- --run --reporter=dot` | **68 个文件、418 项通过，1 项既有模式失败**：`development-competitor.spec.js` 的 mutation mock 创建需求为空；显式 `VITE_USE_MOCK=true` 后通过。 |
| 前端生产构建 | `npm run build` | **通过：2114 modules**；仅有依赖包既有 Rollup `@vueuse` PURE 注释提示 |

### 工作树安全核对

- `git diff --check`、`git status --short` 在本轮验证结束时执行并登记；不执行 reset、checkout、clean 或其他覆盖/回退操作。
- 本批次未提交、未部署、未操作真实租户或生产凭据。

### 验证说明

- 后端 auth API 的精确响应测试已更新为阶段A契约，保留 `role_labels` 和 `identity_label` 的稳定显示语义。
- 未设置 `VITE_USE_MOCK=true` 时，前端 mutation mock 测试会按“写操作失败闭环”返回空响应；全量测试使用显式 Mock 写入模式，避免将网络失败伪装为成功。

## 发布前置条件

- 开发端 A、开发端 B、候选版本和生产版本 SHA 均由实际账本核对；不存在的 SHA 保持空缺，不得填造。
- `0042`/`0043` 在同版本隔离数据库完成迁移演练，权限目录同步和角色权限快照可复核。
- 后端定向/全量回归、Django check、migration check、前端专项/全量测试和 build 均通过；任何无关既有失败需由架构负责人明确豁免。
- 角色权限、组织树、用户部门调整和高风险权限确认完成租户隔离、字段脱敏和审计复核。
- 只有在候选 SHA 冻结、发布审批、备份及回退方案确认后，才可进入生产发布流程。
