# V2.44.66 店铺与仓库 API 接入闭环合版候选登记

## 版本登记

- 登记日期：2026-09-05
- 候选版本：V2.44.66
- 目标父版本：V2.44.65（`v2.44.65-deployed`，`740b958`）
- 实施工作区：`dfcy/.codex-work/v24466-store-warehouse-candidate`（分支 `codex/v24466-store-warehouse-candidate`）
- 合版原则：仓库 API 接入调整与店铺 API 增量必须进入同一不可变镜像、同一版本号和同一次受控发布，不再拆分店铺子版本。
- 候选状态：已在 V2.44.65 干净基线（`740b958`）按最小差异片段完成店铺与仓库 API 接入合版，本地候选门禁已通过；仍须由架构员完成受保护 `main` 合并、受控 CI、虚拟机检查与部署，当前登记不等同于已部署。
- 数据库迁移：仅新增 `permissions.0040_register_warehouse_api_authorization_permissions`，依赖部署基线已有的 `permissions.0039_register_warehouse_connector_role_permissions`。0040 幂等登记店铺与仓库 API 权限，并为内置系统管理员补齐既有操作依赖；既有店铺模型迁移、`permissions.0031` 及仓库连接器权限迁移不重复迁移。

## 同版功能范围

### 仓库 API 接入

- 在“基础档案 → 仓库档案 → API 接入”补齐配置绑定、更换绑定、创建库存同步任务、生产只读检查、查看任务和解除绑定的页面闭环。
- 三方仓与平台仓先绑定已启用、类型匹配且已实现连接器的仓储服务平台；条件不足时按钮显示“API 接入（待配置）”并直接说明下一步。
- 仓库授权、库存同步任务和只读检查按租户、仓库、连接配置、平台、环境、区域及资源类型精确关联；旧配置任务不会被误判为当前绑定的可用任务。
- 凭据继续只通过受控维护入口提交；仓库绑定接口不接收、不读取、不回显原始密钥或 Token。

### 店铺 API 增量

- 店铺授权统一收口到“基础档案 → 店铺档案 → API 接入”，行内弹窗提供重新授权、刷新令牌、平台只读检查、撤销授权和查看同步任务。
- 店铺入口与主体接口同时要求 `integrations.view` 和 `integrations.store.view`；不能使用多权限 OR 语义替代该交集。
- 店铺只读检查必须提交当前 `store_authorization_id`，并与仓库授权 ID 互斥；后端按当前租户、配置、活动授权和对应同步任务精确执行，不得落到同一配置下的其他店铺。
- 店铺刷新令牌同时受 `integrations.store.authorize` 与 `integrations.credential.rotate` 的权限和数据范围交集约束。
- 新建店铺同步任务从授权派生 `store_id` 并纳入 `integrations.manage` 数据范围；已撤销、过期或其他非活动授权不能创建任务。
- 显式 Mock 模式支持 `OAuth start → simulation_callback → callback` 内存演练，字段统一为 `authorization_url`，不打开模拟地址、不产生或回显真实凭据。
- 旧“店铺授权”菜单页删除，旧页面地址 `/integrations/authorizations` 兼容重定向至店铺档案；准备度和生产配置页面的整改入口同步改为店铺档案。

### 共享生产边界

- `requestWithMockFallback` 对 POST、PUT、PATCH、DELETE 采用失败关闭：只有显式 `VITE_USE_MOCK=true` 才允许模拟写操作；真实/生产模式网络失败必须返回失败，不能降级成成功 Mock。
- 生产构建和运行环境必须显式配置 `VITE_USE_MOCK=false`；只读 GET 的兼容降级不构成生产写入授权。
- 新店铺授权审计不再写入 `credential_id`、`token_id` 等托管引用；统一审计脱敏器在写入与序列化时递归剔除 Token、密钥、密码、授权码、Cookie、Session、认证请求头及密文类字段，同时保留 `authorization_id`、`token_refreshed`、`authorization_status`、`session_status` 等幂等与运维证据，且不改写历史数据库记录。
- 全球刊登、库存写回、价格、订单或履约写操作不因本次合版自动开放，继续使用独立审批、预览、幂等、审计和生产开关。

## 角色权限登记

| 页面或动作 | 最小权限 |
| --- | --- |
| 打开店铺 API 接入 | `masterdata.view` + `integrations.view` + `integrations.store.view` |
| 发起/重新发起店铺授权 | 上述查看权限 + `integrations.store.authorize` |
| 刷新店铺令牌 | 上述查看权限 + `integrations.store.authorize` + `integrations.credential.rotate` |
| 撤销店铺授权 | 上述查看权限 + `integrations.store.revoke` |
| 保存店铺读取能力矩阵 | `integrations.store.view` + `integrations.store.authorize`，且授权为活动状态 |
| 打开仓库 API 接入 | `masterdata.view` + `integrations.view` + `integrations.warehouse.view` |
| 绑定/更换仓库配置 | 上述查看权限 + `integrations.warehouse.authorize` |
| 解除仓库绑定 | 上述查看权限 + `integrations.warehouse.revoke` |
| 执行平台生产只读检查 | 对应主体查看权限 + `integrations.run_live_readonly`，并满足配置及任务数据范围 |
| 维护连接配置或凭据 | 分别使用 `integrations.config.*` 与 `integrations.credential.rotate` |

内置 `administrator` 由 0040 获得店铺查看/授权/撤销、仓库查看/绑定/解除，以及目录中已存在的 `integrations.view`、`integrations.manage`、`integrations.run_live_readonly`、`integrations.credential.rotate`，并登记全量数据范围。其他角色仍需管理员显式分配权限与数据范围。

旧页面 `/integrations/authorizations` 重定向到店铺档案后，历史仅有集成权限但没有 `masterdata.view` 的角色会失败关闭；后端 API `/integrations/store-authorizations` 仍是接口路径，不是页面 URL。上线前必须按上表完成角色升级，不得通过放宽路由或主体接口绕过。

## 基线融合清单

店铺 API 的模型、OAuth 后端基础、授权服务和旧迁移已经存在于 `v2.44.65-deployed`。干净候选只移植 V2.44.66 增量，禁止重复复制旧店铺后端或重跑 0031。

需按审查差异片段融合的核心文件包括：

- 后端：`apps/integrations/subject_access_service.py`、`views.py`、`serializers.py`、`store_authorization_service.py`、`warehouse_authorization_service.py`、`urls_internal.py`，以及 `apps/permissions/ui_p6_scopes.py`、`api_permissions.py`、`catalog.py`、`services.py`、迁移 0040（依赖基线 0039）。
- 前端：`src/api/request.js`、`src/api/integrations.js`、`src/components/SubjectApiAccessDialog.vue`、店铺/仓库档案页、准备度与生产配置页、同步任务页、路由和菜单、相关 Mock 与权限数据。
- 页面收口：删除重复的 `src/views/integrations/StoreAuthorizationList.vue`，保留旧 URL 到店铺档案的兼容重定向。
- 测试：店铺/仓库授权闭环、角色权限、数据范围、请求失败关闭、菜单路由及页面操作演练相关用例。

原实施工作区相对部署基线存在历史分叉；候选中的 `router/index.js`、`router/menu.js`、`mock/systemAdmin.js` 等共享文件已在 `v2.44.65-deployed` 上按目标 hunk 重放，未用整文件覆盖，保留 V2.44.62—V2.44.65 的菜单、租户、角色和模块开关增量。全球刊登等其他未核定变更未进入本合版清单。

## 验证登记

| 门禁 | 结果 |
| --- | --- |
| 店铺 + 仓库后端联合专项 | PASS，28 passed；覆盖主体必填、权限交集、区域/资源范围、陈旧换绑、审计脱敏和凭据托管边界 |
| 店铺 + 仓库前端运行时专项 | PASS，4 files / 31 tests；覆盖真实组件交互、OAuth 写失败关闭、广告资源禁用及 Mock 不支持资源拒绝 |
| 后端全量 pytest | PASS，980 passed / 28 skipped；使用仓库内独立 `--basetemp` 规避 Windows 全局临时目录权限故障 |
| 前端全量 Vitest（显式 `VITE_USE_MOCK=true`） | PASS，61 files / 365 tests |
| Django 系统检查 | PASS，0 issues |
| 权限迁移图 | PASS，`permissions.0040` 线性位于基线 `0039` 之后 |
| 迁移漂移检查 | PASS，No changes detected |
| 前端生产构建 | PASS，`VITE_USE_MOCK=false`，Vite 6.4.3 / 2111 modules transformed |
| 店铺 Mock 页面演练 | PASS，干净候选运行于隔离端口并实际验收：Shopee 店铺行内入口、重新授权、刷新令牌、销售订单/退款退货资源选择、建任务、平台只读检查、撤销、任务查看，以及待处理/已过期/已撤销/异常历史详情均可达；凭据只显示掩码。 |
| 仓库 Mock 页面演练 | PASS，干净候选运行于隔离端口并实际验收：马来极风仓身份与连接器一致，绑定/换绑、授权详情、库存任务、生产只读检查、任务查看、解绑、凭据维护，以及四类历史详情均可达。 |
| 前后端独立只读复核 | PASS；后端主体/任务范围分层、审计幂等证据、仓库区域与陈旧换绑无残余阻断；前端广告平台负向门禁、Mock allow-list、OAuth fail-closed、历史详情及按钮权限无残余阻断 |
| 生产控制树静态门禁 | PASS，`production-baseline-check --ci` |
| 候选 Git 对象可移交性 | PASS，候选 HEAD 与部署基线的 connectivity 检查、完整 bundle 创建及 verify 均通过；共享仓库的其他历史引用仍存在预存缺失对象，受控发布必须从远端干净 clone 合并候选，不依赖本机全局 object store |
| 受保护 main、远程 CI 与制品核验 | 待架构员合并候选后执行；生产工作流拒绝不在 `main` 历史中的 SHA |
| 虚拟机受控 check | 待架构员通过 GitHub Production forced-command CI 密钥执行；本地登记密钥未绑定受控入口，未使用普通 SSH shell 绕过 |

## 发布与回滚限制

生产发布只能由架构员通过受控 CI 完成。本次不直接修改虚拟机、不创建部署标签、不覆盖生产 Compose、环境文件、镜像摘要或版本账本。

若干净候选验证失败，保持 `v2.44.65-deployed` 不变并丢弃 V2.44.66 候选；不得手工逆向修改生产数据库。权限迁移保持幂等，应用回退时保留新增权限行不会扩大旧版本可调用接口的能力。
