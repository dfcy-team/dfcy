# AR0-003 开发B前端与RPA准备审核报告

## 1. 审核对象

- 项目根目录：`saas-collab-system/`
- 审核范围：
  - `frontend/`
  - `rpa-agent/`
  - `docs/04_rpa/`
  - `docs/00_stage0/`
- 审核时间：2026-07-08
- 审核人员：系统架构需求拆分和核实人员

本次审核只生成报告，不修改 `backend/`、`frontend/`、`rpa-agent/`、`docker-compose.yml`、`.env.example`、`package.json`、业务代码、配置代码或 RPA 脚本。

## 2. 审核结论

结论：`FAIL`

判断依据：

- 存在 P0 问题。
- `frontend/` 目录不存在，无法满足前端工程结构、页面占位、Mock 数据、API 封装、路由菜单、登录状态等阶段0审核要求。
- `rpa-agent/` 目录不存在，无法满足 RPA Agent 目录、截图/日志/缓存、任务样例、Agent 约束等阶段0审核要求。
- `docs/04_rpa/` 仅有 `examples/.gitkeep`，缺少 BigSeller RPA 步骤文档和 payload 样例。
- `docs/00_stage0/frontend_api_mapping.md` 不存在，缺少前后端接口对接清单。

## 3. 已完成项

### 阶段0范围文档

- 已存在 `docs/00_stage0/stage0_file_scope.md`。
- 已明确项目根目录固定为 `saas-collab-system/`。
- 已明确开发B允许修改 `frontend/`、`rpa-agent/`、`docs/00_stage0/`、`docs/04_rpa/`。
- 已明确前端不承载真实权限判断。
- 已明确 RPA 不允许直连数据库。
- 已明确阶段0不接真实外部平台。

### 审核目录

- 已存在 `docs/00_stage0/review/`。
- 已存在 `docs/00_stage0/review/README.md`。

### RPA文档目录占位

- 已存在 `docs/04_rpa/`。
- 已存在 `docs/04_rpa/examples/`。
- `docs/04_rpa/examples/` 当前仅有 `.gitkeep`。

## 4. 缺失项

### 前端工程结构缺失

以下要求均未满足：

- `frontend/`
- `frontend/package.json`
- `frontend/.env.example`
- `frontend/README.md`
- `frontend/src/`
- `frontend/src/main.js` 或 `frontend/src/main.ts`
- `frontend/src/App.vue`
- `frontend/src/router/`
- `frontend/src/stores/`
- `frontend/src/api/`
- `frontend/src/mock/`
- `frontend/src/layouts/`
- `frontend/src/views/`

无法确认：

- 是否为 Vue3 + Vite 工程。
- 是否配置 Element Plus。
- 是否配置 vue-router。
- 是否配置 pinia。
- 是否配置 axios。
- 是否存在 Mock 模式。
- 是否通过 `VITE_API_BASE_URL` 和 `VITE_USE_MOCK` 控制接口与 Mock。

### 前端目录结构缺失

以下页面目录均不存在：

- `frontend/src/views/dashboard/`
- `frontend/src/views/auth/`
- `frontend/src/views/products/`
- `frontend/src/views/purchasing/`
- `frontend/src/views/suppliers/`
- `frontend/src/views/listings/`
- `frontend/src/views/pricing/`
- `frontend/src/views/rpa/`
- `frontend/src/views/integrations/`
- `frontend/src/views/finance/`
- `frontend/src/views/reports/`
- `frontend/src/views/audit/`

### Layout / 路由 / 菜单缺失

未发现：

- 后台 `MainLayout`
- 左侧菜单
- 顶部栏
- 内容区
- 当前用户信息占位
- 路由配置

未发现至少包含以下菜单的占位：

- 首页
- 新品市调
- 商品主数据
- 采购供应链
- 供应商协同
- 多国家刊登
- 价格中心
- RPA任务
- API同步
- 财务入口
- BI报表
- 日志审计

### 登录与用户状态缺失

未发现：

- `Login.vue`
- auth store
- currentUser mock 数据
- mock 登录流程
- 路由守卫占位

未发现 mock 用户字段占位：

- `user_id`
- `username`
- `user_type`
- `tenant_id`
- `roles`
- `permissions`

### API封装与Mock缺失

未发现：

- `frontend/src/api/request.js` 或 `request.ts`
- `frontend/src/api/auth.js`
- `frontend/src/api/products.js`
- `frontend/src/api/purchasing.js`
- `frontend/src/api/suppliers.js`
- `frontend/src/api/listings.js`
- `frontend/src/api/pricing.js`
- `frontend/src/api/rpa.js`
- `frontend/src/api/integrations.js`
- `frontend/src/api/audit.js`
- `frontend/src/mock/`

未发现统一 Mock 响应结构：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

### MVP页面占位缺失

未发现以下页面或等价页面：

- `ResearchList`
- `ResearchDetail`
- `ProductMasterList`
- `ProductMasterDetail`
- `ProductStatusList`
- `PurchaseOrderList`
- `PurchaseOrderDetail`
- `SupplierTaskList`
- `SupplierTaskDetail`
- `SupplierShipmentList`
- `SupplierShipmentDetail`
- `SiteProfileList`
- `SiteProfileDetail`
- `ListingTemplateList`
- `PriceList`
- `PriceDetail`
- `RPATaskList`
- `RPATaskDetail`
- `APISyncTaskList`
- `APISyncLogList`
- `OperationLogList`
- `FinanceImportList`
- `BasicReportIndex`

### 商品页面字段缺失

未发现市调页面字段占位：

- 市调编号
- 商品名称
- 平台
- 竞品链接
- 预估销量
- 预估毛利
- 风险点
- 附件占位
- 审批状态占位

未发现商品主数据页面字段占位：

- 商品编码
- SPU
- SKU
- 商品名称
- 类目
- 图片
- 尺码
- 材质
- 卖点
- 箱规重量
- 生命周期状态
- 销售状态
- 编码冻结按钮占位

### 采购与供应商页面字段缺失

未发现采购订单页面字段占位：

- 采购单号
- 商品编码
- SKU
- 供应商
- 采购数量
- 单价
- 交期
- 付款方式
- 状态
- 审批状态

未发现供应商任务页面字段占位：

- 任务编号
- 供应商
- 商品编码
- 生产数量
- 已完成数量
- 预计出货日期
- 状态
- 是否逾期
- 回填记录
- 异常说明

未发现供应商出货页面字段占位：

- 出货单号
- 出货数量
- 箱数
- 重量
- 体积
- 箱唛
- 物流单
- 图片附件占位
- 采购确认按钮占位

### 多国家刊登与价格页面缺失

未发现多国家刊登资料字段占位：

- 商品编码
- SKU
- 平台
- 国家
- 店铺
- 标题
- 类目
- 本地关键词
- 描述
- 尺码规则
- 平台差异字段
- 刊登状态
- 页面价格状态
- 生成RPA任务按钮占位

未发现价格页面字段占位：

- 采购成本
- 物流成本
- 平台佣金
- 汇率
- 目标毛利
- 建议价
- 审批价
- 清仓价占位
- 页面价
- 提交价格审批按钮占位

### RPA任务页面缺失

未发现 RPA 任务列表和详情页面字段占位：

- 任务编号
- 任务类型
- 业务类型
- 业务ID
- Agent
- 状态
- 重试次数
- payload JSON展示
- result JSON展示
- 步骤日志
- 截图列表
- 错误原因
- 重试按钮占位
- 人工接管按钮占位

未发现 RPA 状态占位：

- `pending`
- `claimed`
- `running`
- `success`
- `failed`
- `retrying`
- `manual_required`
- `cancelled`

未发现 RPA 任务类型占位：

- `BIGSELLER_CREATE_PRODUCT`
- `BIGSELLER_UPLOAD_IMAGES`
- `BIGSELLER_MULTI_SITE_LISTING`
- `BIGSELLER_UPDATE_PRICE`
- `BIGSELLER_READ_PAGE_PRICE`
- `BIGSELLER_COLLECT_LISTING_STATUS`

### API同步日志与操作日志页面缺失

未发现 `APISyncTaskList` 字段占位：

- 任务编号
- 平台
- 店铺
- 同步类型
- 状态
- 上次同步时间
- 下次同步时间
- 重试次数

未发现 `APISyncLogList` 字段占位：

- 日志编号
- 平台
- 同步类型
- 状态
- 开始时间
- 结束时间
- 错误信息
- 数据质量检查结果

未发现 `OperationLogList` 字段占位：

- 操作人
- 模块
- 动作
- 对象类型
- 对象ID
- IP
- 时间

### rpa-agent目录缺失

以下要求均未满足：

- `rpa-agent/`
- `rpa-agent/agents/`
- `rpa-agent/bigseller/`
- `rpa-agent/bigseller/steps/`
- `rpa-agent/bigseller/selectors/`
- `rpa-agent/bigseller/examples/`
- `rpa-agent/tasks/`
- `rpa-agent/tasks/examples/`
- `rpa-agent/screenshots/`
- `rpa-agent/logs/`
- `rpa-agent/config/`
- `rpa-agent/.env.example`
- `rpa-agent/README.md`

### BigSeller RPA步骤文档缺失

未发现：

- `docs/04_rpa/bigseller_rpa_steps.md`

缺少以下流程文档：

- BigSeller登录检查流程
- 商品建档流程
- 图片上传流程
- 多国家复制/刊登流程
- 页面价格回读流程
- 刊登状态采集流程
- 失败截图规则
- 验证码转人工规则
- 同账号任务串行规则
- RPA结果回写规则

### RPA payload样例缺失

`docs/04_rpa/examples/` 仅有 `.gitkeep`，`rpa-agent/tasks/examples/` 不存在。

缺少：

- `bigseller_create_product_payload.json`
- `bigseller_upload_images_payload.json`
- `bigseller_multi_site_listing_payload.json`
- `bigseller_update_price_payload.json`
- `bigseller_read_page_price_payload.json`
- `bigseller_collect_listing_status_payload.json`
- `rpa_task_success_result.json`
- `rpa_task_failed_result.json`

### 前后端接口对接清单缺失

未发现：

- `docs/00_stage0/frontend_api_mapping.md`

缺少以下页面覆盖：

- 登录页
- 首页
- 新品市调列表
- 新品市调详情
- 商品主数据列表
- 商品主数据详情
- 采购订单列表
- 采购订单详情
- 供应商任务列表
- 供应商任务详情
- 多国家刊登资料列表
- 多国家刊登资料详情
- 价格列表
- RPA任务列表
- RPA任务详情
- API同步任务列表
- API同步日志列表
- 操作日志列表

## 5. 越界项

未发现阶段0越界实现。

说明：

- `frontend/` 不存在，因此未发现真实业务提交、真实审批、真实附件上传、真实财务数据、真实 API 同步、真实权限判断写死在前端。
- `rpa-agent/` 不存在，因此未发现真实浏览器自动化脚本、真实 BigSeller 操作、真实改价脚本、真实 RPA 直连数据库配置。
- `docs/04_rpa/` 仅有 `.gitkeep`，未发现真实选择器、真实账号、真实密码或真实平台 API。

## 6. 安全风险

扫描范围：

- `docs/00_stage0/`
- `docs/04_rpa/`
- `frontend/`，目录不存在
- `rpa-agent/`，目录不存在

扫描关注项：

- 真实 `.env`
- 真实 BigSeller 账号密码
- 真实 Shopee/TK Token
- 真实 API Key / API Secret
- 真实数据库密码
- 真实银行账号或财务数据
- RPA 直连数据库配置
- 前端硬编码真实 Token
- 前端硬编码真实用户账号密码

扫描结果：

- 未发现真实 `.env`。
- 未发现真实 BigSeller 账号密码。
- 未发现真实 Shopee/TK Token。
- 未发现真实 API Key / API Secret。
- 未发现真实数据库密码。
- 未发现真实银行账号或财务数据。
- 未发现 RPA 直连数据库配置。
- 未发现前端硬编码真实 Token。
- 未发现前端硬编码真实用户账号密码。

命中说明：

- `docs/00_stage0/stage0_file_scope.md` 中出现的 BigSeller、Shopee、TK、Token、密码等均为禁止项说明，不是真实凭据。
- `docs/04_rpa/` 仅有 `.gitkeep`，不存在敏感信息。

安全结论：未发现新增敏感信息 P0；但工程与文档缺失导致本次审核整体为 `FAIL`。

## 7. 模块审核明细

| 模块 | 结论 | 说明 |
|---|---|---|
| 前端工程结构 | FAIL | `frontend/` 不存在，无法确认 Vue3 + Vite、Element Plus、vue-router、pinia、axios、Mock 模式。 |
| 前端目录结构 | FAIL | `frontend/src/views/*` 模块目录全部缺失。 |
| Layout / 路由 / 菜单 | FAIL | 未发现 MainLayout、左侧菜单、顶部栏、内容区、当前用户信息、路由配置。 |
| 登录与用户状态 | FAIL | 未发现 Login.vue、auth store、currentUser mock、mock 登录、路由守卫。 |
| API封装与Mock | FAIL | 未发现 request、auth、products、rpa 等 API 封装和 mock 目录。 |
| MVP页面占位 | FAIL | 所有指定 MVP 页面占位均缺失。 |
| 商品页面 | FAIL | 市调和商品主数据字段占位缺失。 |
| 采购与供应商页面 | FAIL | 采购订单、供应商任务、供应商出货字段占位缺失。 |
| 多国家刊登与价格页面 | FAIL | 多国家刊登和价格字段占位缺失。 |
| RPA任务页面 | FAIL | RPA任务列表/详情、状态、任务类型占位缺失。 |
| API同步与日志页面 | FAIL | API同步任务、同步日志、操作日志页面占位缺失。 |
| rpa-agent目录 | FAIL | `rpa-agent/` 及其子目录全部缺失。 |
| BigSeller RPA步骤文档 | FAIL | `docs/04_rpa/bigseller_rpa_steps.md` 不存在。 |
| RPA payload样例 | FAIL | `docs/04_rpa/examples/` 仅 `.gitkeep`，`rpa-agent/tasks/examples/` 不存在。 |
| 前后端接口对接清单 | FAIL | `docs/00_stage0/frontend_api_mapping.md` 不存在。 |

## 8. P0问题

### P0-001 前端工程结构缺失

- 责任人：开发B
- 涉及目录：`frontend/`
- 问题描述：`frontend/` 不存在，无法满足阶段0前端工程结构、Vue3 + Vite、路由、状态、API封装、Mock、页面占位审核要求。
- 整改要求：创建前端阶段0工程或完整目录占位。
- 验收标准：
  - `frontend/` 存在。
  - 存在 `package.json`、`.env.example`、`README.md`、`src/`、`main.js` 或 `main.ts`、`App.vue`。
  - 存在 `router/`、`stores/`、`api/`、`mock/`、`layouts/`、`views/`。
  - README 明确阶段0仅 Mock 和页面占位，不连接真实平台。

### P0-002 前端页面、Layout、路由、菜单缺失

- 责任人：开发B
- 涉及目录：`frontend/src/`
- 问题描述：后台 Layout、路由、菜单、业务页面目录和 MVP 页面占位均缺失。
- 整改要求：补齐 MainLayout、菜单、路由和阶段0页面占位。
- 验收标准：
  - 菜单覆盖：首页、新品市调、商品主数据、采购供应链、供应商协同、多国家刊登、价格中心、RPA任务、API同步、财务入口、BI报表、日志审计。
  - 菜单能进入对应占位页面。
  - 文档明确菜单权限仅为展示占位，真实权限以后端为准。

### P0-003 前端 API 封装与 Mock 缺失

- 责任人：开发B
- 涉及目录：`frontend/src/api/`、`frontend/src/mock/`
- 问题描述：API请求封装、Mock开关、Mock响应结构、各业务模块 API 文件均缺失。
- 整改要求：补齐 request 封装、业务 API 文件和 Mock 数据。
- 验收标准：
  - `baseURL` 通过 `VITE_API_BASE_URL` 读取。
  - 存在 `VITE_USE_MOCK` 或等价 Mock 开关。
  - Mock 响应符合 `{success, code, message, data}`。
  - 未使用真实 Token 或真实平台 API 地址。

### P0-004 rpa-agent 目录缺失

- 责任人：开发B
- 涉及目录：`rpa-agent/`
- 问题描述：`rpa-agent/` 及 agents、bigseller、tasks、screenshots、logs、config 等子目录缺失。
- 整改要求：补齐 RPA Agent 阶段0目录结构和说明。
- 验收标准：
  - `rpa-agent/README.md` 明确 RPA 不得直连 MySQL，只能访问 `/api/rpa/*`。
  - `rpa-agent/.env.example` 只有示例字段。
  - 存在 screenshots、logs、cache/downloads 或等价运行目录占位。
  - 不存在真实浏览器自动化脚本或真实改价脚本。

### P0-005 BigSeller RPA步骤文档缺失

- 责任人：开发B
- 涉及目录：`docs/04_rpa/`
- 问题描述：`docs/04_rpa/bigseller_rpa_steps.md` 不存在。
- 整改要求：补齐 BigSeller RPA 阶段0步骤文档。
- 验收标准：
  - 文档覆盖登录检查、商品建档、图片上传、多国家复制/刊登、页面价格回读、刊登状态采集、失败截图、验证码转人工、同账号串行、结果回写。
  - 每个流程包含流程名称、输入字段、页面步骤、成功判断、失败判断、截图节点、回写字段、人工接管条件。
  - 不包含真实账号、真实密码、真实选择器。

### P0-006 RPA payload样例缺失

- 责任人：开发B
- 涉及目录：`docs/04_rpa/examples/`、`rpa-agent/tasks/examples/`
- 问题描述：RPA payload 和 result 示例 JSON 缺失。
- 整改要求：补齐指定 payload 与 result 示例。
- 验收标准：
  - 指定 8 个 JSON 示例存在且格式有效。
  - 示例数据不包含真实商品、真实店铺、真实账号。
  - result 包含 `status`、`message`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。

### P0-007 前后端接口对接清单缺失

- 责任人：开发B
- 涉及目录：`docs/00_stage0/frontend_api_mapping.md`
- 问题描述：接口对接清单不存在，无法确认页面、API、Mock、负责人、状态和权限边界。
- 整改要求：补齐前后端接口对接清单。
- 验收标准：
  - 覆盖登录页、首页、新品市调、商品主数据、采购订单、供应商任务、多国家刊登、价格、RPA、API同步、操作日志等页面。
  - 未完成接口标记为 `mock` 或 `pending`。
  - 不编造后端已完成。
  - 供应商页面不访问 `/api/internal/*`。
  - RPA 不访问 `/api/finance/*`。
  - 不把 `/admin/` 当业务接口。

## 9. P1问题

无。当前核心交付缺失已按 P0 处理。

## 10. P2问题

### P2-001 docs/04_rpa/examples 仅为空目录占位

- 责任人：开发B
- 涉及目录：`docs/04_rpa/examples/`
- 问题描述：当前仅有 `.gitkeep`。
- 整改要求：完成 P0-006 后补齐可读说明或索引 README。
- 验收标准：examples 目录有 README 或索引说明每个 JSON 样例用途。

## 11. 整改任务建议

| 编号 | 等级 | 问题描述 | 责任人 | 涉及目录 | 整改要求 | 验收标准 |
|---|---|---|---|---|---|---|
| AR0-003-P0-001 | P0 | 前端工程结构缺失 | 开发B | `frontend/` | 创建 Vue3 + Vite 阶段0工程或完整占位结构 | 前端工程结构文件齐全，未接真实后端或平台 |
| AR0-003-P0-002 | P0 | 前端页面、Layout、路由、菜单缺失 | 开发B | `frontend/src/` | 补 MainLayout、菜单、路由、MVP页面占位 | 菜单可进入占位页面，真实权限以后端为准 |
| AR0-003-P0-003 | P0 | 前端 API 封装与 Mock 缺失 | 开发B | `frontend/src/api/`、`frontend/src/mock/` | 补 request、业务 API、Mock 开关和 Mock 数据 | Mock 响应统一结构，无真实 Token/API 地址 |
| AR0-003-P0-004 | P0 | rpa-agent 目录缺失 | 开发B | `rpa-agent/` | 补 Agent 目录、运行目录、README、示例 env | 明确不直连 MySQL，只访问 `/api/rpa/*` |
| AR0-003-P0-005 | P0 | BigSeller RPA步骤文档缺失 | 开发B | `docs/04_rpa/` | 补 `bigseller_rpa_steps.md` | 覆盖指定流程，不含真实账号/密码/选择器 |
| AR0-003-P0-006 | P0 | RPA payload样例缺失 | 开发B | `docs/04_rpa/examples/`、`rpa-agent/tasks/examples/` | 补 8 个指定 JSON 示例 | JSON 有效，示例数据不含真实业务/账号 |
| AR0-003-P0-007 | P0 | 前后端接口对接清单缺失 | 开发B | `docs/00_stage0/frontend_api_mapping.md` | 补页面/API/Mock/负责人/状态清单 | 覆盖指定页面，不编造接口完成状态 |
| AR0-003-P2-001 | P2 | examples 缺少索引说明 | 开发B | `docs/04_rpa/examples/` | 补 README 或索引 | 能说明各示例 JSON 用途 |

## 12. 阶段1准入建议

建议：不允许进入阶段1。

原因：

- 存在 P0 问题。
- 前端工程、页面占位、Mock、API封装缺失。
- RPA Agent 目录、BigSeller步骤文档、payload样例缺失。
- 前后端接口对接清单缺失。

阶段1准入条件：

1. AR0-003 P0 问题全部关闭。
2. 开发B完成 `frontend/`、`rpa-agent/`、`docs/04_rpa/`、`docs/00_stage0/frontend_api_mapping.md` 阶段0交付。
3. 安全复审确认无真实密钥、真实账号、真实 Token、真实 API Key、真实数据库密码。
4. 启动与构建检查可执行，或报告中明确说明不可执行原因。
5. AR0-003-R1 复审结论达到 `PASS`。

## 13. 启动与构建检查

由于 `frontend/` 目录不存在，未执行：

- `npm install`
- `npm run build`
- `npm run dev`

由于 `frontend/` 与 Mock 文件不存在，无法验证 Mock 模式是否可运行。

由于 RPA payload JSON 不存在，无法执行 JSON 格式检查。

本报告未伪造启动、构建或 JSON 校验结果。
