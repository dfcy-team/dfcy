# V2.44.202 员工委托只读查询候选登记

日期：2026-10-01。状态：LOCAL_CANDIDATE_NOT_RELEASED。基线 V2.44.201 / ce8a74be74936f7cfed47e3447e4a26e07fbe4f6；登记时远端 deployed 标签最高为 201，未发现 202 标签。正式提交/合并前必须再次检查并发占用，候选登记不代表生产账本。

隔离分支：feat/employee-readonly-delegation；工作树：`.codex-tmp/employee-readonly-delegation`。不修改其他在制分支。

范围：新增独立员工委托授权/交换/撤销、本人能力目录、四类基础资源只读集合。两头认证、一次性 PKCE/state 授权码、哈希存储短时令牌、授权指纹、加密绑定分页、逐请求原生权限/DataScope及字段检查、无缓存响应和脱敏审计。既有机器同步/SSO合同、密钥、网络与菜单不变。

原 `/sso/authorize` 页面增加显式 purpose/audience 委托模式与本人确认文案，未新增菜单或路由。租户管理员自动目录同步/初始化排除新增委托 FIELD 自动分配，保留既有显式授予。

迁移：integrations.0036_employee_readonly_grant 新增委托表；integrations.0037_employee_readonly_field_catalog 新增 38 项 FIELD 目录定义，不自动分配角色。生产不执行本候选迁移。

默认全局关闭、调用方允许配置为空、字段策略为空。首批仅 products/product_details/stores/warehouses；sales_orders/purchase_orders/inventory_snapshots/financial_aggregates 明确待接入。未授权字段和资源不能读取，不用机器接口兜底。

合同、首批字段集合与 NAS 接入步骤：`docs/03_api/employee_readonly_nas_integration_20261001.md`；OpenAPI：`docs/03_api/employee_readonly_v1.openapi.yaml`；审阅与回滚：`docs/06_release/employee_readonly_security_review_20261001.md`。

本次仅准备代码、隔离测试、文档与候选登记。尚未创建生产镜像、部署、修改角色/调用方或启用。原系统前端退出集成和实际岗位页面对照仍是启用前门禁。用户确认具体资源/字段/岗位/调用方及发布范围后，由既有发布通道执行最后一步。

验收：根代理 SQLite 专项与原 SSO/租户管理员回归共 21 项通过（pytest --nomigrations）；worker 完整迁移后旧 SSO 与委托早期测试共 12 项通过。系统检查、迁移一致性检查、diff 检查通过。前端授权分流/错误模式与旧 SSO 共 10 项通过，生产构建通过，菜单快照仍为 108 菜单/142 路由。

界面烟测：127.0.0.1:5184，桌面 1280×720 与移动 390×844，员工委托确认文案和回调显示正常，点击后保持原页显示错误，无假跳转。此烟测仅启动前端，authorize 请求的 404 是预期的未连接后端证据，不算双端授权联调成功。Browser 插件技能不可用，使用已有 Playwright CLI；截图保留在主机临时目录。原生岗位对照、退出集成、NAS 联调和生产门禁待后续执行。
