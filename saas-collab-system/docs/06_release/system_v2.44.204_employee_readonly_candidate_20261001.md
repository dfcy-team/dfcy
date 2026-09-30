# V2.44.204 员工委托只读查询候选登记

日期：2026-10-01。状态：REGISTERED_CANDIDATE_AWAITING_FINAL_DELIVERY_NOT_DEPLOYED。V2.44.202 已保留给飞书 QR，V2.44.203 已保留给飞书六标签；虚拟机发布通道已确认 V2.44.204 无其他批次占用并登记为待发布候选（登记 ID：vm-candidate-2-44-204-employee-readonly-delegation）。初始实现提交为 `94697a172b4127fb645204727687eabe84c737dd`，开发基线 V2.44.201；后续文档修正不等于最终发布 SHA。计划发布父版本为 V2.44.203，构建镜像前必须正常合并最终 203、保留前序改动并复核，不强推或重写历史。

默认关闭的代码发布已获授权，可在版本协调确认后先由虚拟机通道发布，再由阿里云通道审核发布并登记；此授权不包含启用委托或扩大生产权限。当前未部署，未创建生产镜像或执行生产迁移。

范围：新增独立员工委托授权/交换/撤销、本人能力目录、四类基础资源只读集合。两头认证、一次性 PKCE/state 授权码、哈希存储短时令牌、授权指纹、加密绑定分页、逐请求原生权限/DataScope及字段检查、无缓存响应和脱敏审计。既有机器同步/SSO合同、密钥、网络与菜单不变。

原 `/sso/authorize` 页面增加显式 purpose/audience 委托模式与本人确认文案，未新增菜单或路由。租户管理员自动目录同步/初始化排除新增委托 FIELD 自动分配，保留既有显式授予。

迁移：`integrations.0036_employee_readonly_grant` 新增委托表；`integrations.0037_employee_readonly_field_catalog` 新增 37 项 FIELD 目录定义（products 9、product_details 12、stores 9、warehouses 7），不自动分配角色。正常合入 Feishu 202 后，新增 `integrations.0038_merge_feishu_login_employee_readonly`，明确依赖 `0036_feishuloginsession` 与 `0037_employee_readonly_field_catalog`，operations 为空，不修改两条既有业务迁移。正式接续 203 后仍须复核实际最终迁移图并完整演练，不能把当前 202 分叉修复当作最终 203 门禁已通过。首批资源仅 products/product_details/stores/warehouses；sales_orders/purchase_orders/inventory_snapshots/financial_aggregates 明确待接入。全局关闭、调用方允许配置为空、字段策略为空；未授权字段与资源不可读，不用机器接口兜底。生产尚未执行候选迁移；正式部署仅执行已审阅并验证的最终迁移清单。

合同与 NAS 接入步骤：`docs/03_api/employee_readonly_nas_integration_20261001.md`；OpenAPI：`docs/03_api/employee_readonly_v1.openapi.yaml`；安全审阅与回滚：`docs/06_release/employee_readonly_security_review_20261001.md`。

验收证据：根代理 SQLite 专项与原 SSO/租户管理员回归 21 项通过；worker 完整迁移后旧 SSO 与委托早期测试 12 项通过；前端授权分流/错误模式与旧 SSO 10 项通过，生产构建通过，菜单快照 108 菜单/142 路由。界面烟测只启动前端，authorize 请求 404 为预期，不算双端授权联调。上述为本地候选证据，不代表部署验收。

部署与启用分离：退出集成调用 revoke-all 仍是启用门禁，默认关闭的发布阶段可保持待办。启用前还需实际岗位页面对照、NAS 双端联调、最终 client/tenant、回调、来源 CIDR、资源/字段/岗位授权矩阵及回滚确认。本次发布不得开启全局开关、加入调用方、改角色或扩字段/资源授权；均未授权。虚拟机与阿里云发布登记后，本候选仍保持关闭。

当前接续进度：已正常合入 202 主分支提交 `235a18a0479082185473e7c7bd23c8f0fd5ba9bc`，保留扫码登录、原账号回退及既有配置代码。前端累计 19 项回归、生产构建与菜单快照通过。Django check、迁移一致性及全新 SQLite 完整迁移通过；目录 37 项、无角色/用户角色/委托自动生成，三项运行时配置 False/[]/{}。员工委托、原身份 SSO 与飞书共 48 项通过；两套角色回归共 14 项通过。两处旧“管理员获授所有 Permission”测试断言已改为全部原生权限且拒绝自动委托字段，生产授权逻辑未因此放宽。新 HEAD CI 待完成；本候选仍不是接续 203 后的最终发布源码。
