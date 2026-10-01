# V2.44.204 员工委托只读查询候选登记

日期：2026-10-01。状态：REGISTERED_CANDIDATE_AWAITING_FINAL_DELIVERY_NOT_DEPLOYED。虚拟机发布通道已确认 V2.44.204 无其他批次占用并登记为待发布候选（登记 ID：vm-candidate-2-44-204-employee-readonly-delegation），202/203 原编号保留。初始实现提交为 `94697a172b4127fb645204727687eabe84c737dd`，开发基线 V2.44.201。现已正常合入 202/203，实际发布父版本源码为 V2.44.203 / `219cd7e20f2cef613673b0cdd0177ca929a0b94f`，未强推或重写历史。虚拟机已对该 203 完成部署验收、双账本登记与 deployed 标签核对，回执时间为 2026-10-01 00:06:09 UTC；阿里云前序发布回执仍须单独核验。旧 `0128ffa` 及接续它的候选测试只作历史证据，禁止据此发布。204 仍待最新 HEAD CI、独立安全审阅和发布通道验收；不是最终合并 main/部署 SHA。

默认关闭的代码发布已获授权，可在版本协调确认后先由虚拟机通道发布，再由阿里云通道审核发布并登记；此授权不包含启用委托或扩大生产权限。当前未部署，未创建生产镜像或执行生产迁移。

范围：新增独立员工委托授权/交换/撤销、本人能力目录、四类基础资源只读集合。两头认证、一次性 PKCE/state 授权码、哈希存储短时令牌、授权指纹、加密绑定分页、逐请求原生权限/DataScope及字段检查、无缓存响应和脱敏审计。既有机器同步/SSO合同、密钥、网络与菜单不变。

原 `/sso/authorize` 页面增加显式 purpose/audience 委托模式与本人确认文案，未新增菜单或路由。租户管理员自动目录同步/初始化排除新增委托 FIELD 自动分配，保留既有显式授予。

迁移：`integrations.0036_employee_readonly_grant` 新增委托表；`integrations.0037_employee_readonly_field_catalog` 新增 37 项 FIELD 目录定义（products 9、product_details 12、stores 9、warehouses 7），不自动分配角色。正常合入 Feishu 202 后新增无操作 `0038_merge_feishu_login_employee_readonly`，合并 `0036_feishuloginsession` 与员工 `0037`；合入最终 203 后新增无操作 `0039_merge_feishu_delivery_employee_readonly`，合并 `0037_feishu_delivery` 与 `0038`。两条合并迁移 operations 均为空，不修改既有业务迁移。全新 SQLite 完整迁移、迁移一致性和最终单叶 0039 验证通过，全图待迁移为 0；发布通道仍需复核最终不可变镜像与实际环境迁移计划。首批资源仅 products/product_details/stores/warehouses；sales_orders/purchase_orders/inventory_snapshots/financial_aggregates 明确待接入。全局关闭、调用方允许配置为空、字段策略为空；未授权字段与资源不可读，不用机器接口兜底。生产尚未执行员工候选四项迁移；正式部署仅执行已审阅并验证的最终迁移清单。

合同与 NAS 接入步骤：`docs/03_api/employee_readonly_nas_integration_20261001.md`；OpenAPI：`docs/03_api/employee_readonly_v1.openapi.yaml`；安全审阅与回滚：`docs/06_release/employee_readonly_security_review_20261001.md`。

验收证据：根代理 SQLite 专项与原 SSO/租户管理员回归 21 项通过；worker 完整迁移后旧 SSO 与委托早期测试 12 项通过；前端授权分流/错误模式与旧 SSO 10 项通过，生产构建通过，菜单快照 108 菜单/142 路由。界面烟测只启动前端，authorize 请求 404 为预期，不算双端授权联调。上述为本地候选证据，不代表部署验收。

部署与启用分离：退出集成调用 revoke-all 仍是启用门禁，默认关闭的发布阶段可保持待办。启用前还需实际岗位页面对照、NAS 双端联调、最终 client/tenant、回调、来源 CIDR、资源/字段/岗位授权矩阵及回滚确认。本次发布不得开启全局开关、加入调用方、改角色或扩字段/资源授权；均未授权。虚拟机与阿里云发布登记后，本候选仍保持关闭。

202 阶段历史验收：正常合入主分支提交 `235a18a0479082185473e7c7bd23c8f0fd5ba9bc`，保留扫码登录及原账号回退。前端 19 项、构建、菜单快照，Django check、迁移一致性及新 SQLite 完整迁移均通过；目录 37 项、零角色/用户角色/委托自动生成、配置 False/[]/{}。功能回归 48 项、两套角色 14 项通过。两处旧“管理员获授所有 Permission”断言改为全部原生权限且拒绝自动委托字段，未放宽生产授权。该阶段源码仅接续 202，不作为最终 203 验收证据。

旧 203 快照接续验收（历史）：正常合入 `0128ffa0ec74314da0a4a2b2dba539b9f085e210` 后，0039 单叶、全图迁移完成、37 字段/零委托记录、False/[]/{} 均通过。八文件累计后端回归 109 项；前端全量 149 文件/871 项、生产构建与菜单快照 108/142 通过。该父快照已被 219cd7e 替代，不能作为最终发布门禁。

正确 203 父版本接续验收：正常合入 `219cd7e20f2cef613673b0cdd0177ca929a0b94f`，保留通讯录/单聊事件权限说明及其回归补丁。该补丁不改模型、迁移或前端；候选前端树与已验证的 149 文件/871 项及构建快照一致。八文件后端回归 110 项通过（完整迁移模式）；Django check、makemigrations --check --dry-run、全新 SQLite 完整迁移均通过，0039 单叶、全图待迁移 0、37 字段定义/零委托、默认 False/[]/{}。最新候选 HEAD 的全部 CI 与独立安全审阅仍为门禁，以上不代表生产验收。
