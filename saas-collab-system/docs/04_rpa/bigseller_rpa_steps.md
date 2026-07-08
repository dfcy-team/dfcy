# BigSeller RPA 阶段0操作步骤说明

本文档仅描述阶段0 RPA 操作步骤占位，不实现真实 RPA 脚本，不包含真实 BigSeller 账号、真实 BigSeller 密码或真实页面选择器。选择器统一使用 `selector.*` 占位名称。

## 1. BigSeller登录检查流程

- 流程名称：BigSeller登录检查流程。
- 输入字段：`task_id`、`agent_name`、`store_code`、`account_alias`、`login_url`。
- 页面步骤：打开 `login_url` 示例地址；检查 `selector.login_status_area`；检查 `selector.current_store_label`；确认是否需要人工登录。
- 成功判断：`selector.login_status_area` 显示已登录占位状态，且 `selector.current_store_label` 与 `store_code` 示例值匹配。
- 失败判断：出现 `selector.login_form`、`selector.captcha_panel`、`selector.risk_warning_panel`、页面超时或店铺上下文不匹配。
- 截图节点：登录状态检查页、验证码页、风控提示页、店铺不匹配页。
- 回写字段：`task_id`、`status`、`message`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：需要输入账号密码、出现验证码、出现二次验证、出现风控提示、账号或店铺状态异常。

## 2. 商品建档流程

- 流程名称：商品建档流程。
- 输入字段：`task_id`、`store_code`、`product_code`、`spu`、`sku`、`title`、`category`、`description`、`attributes`、`images`。
- 页面步骤：进入 `selector.product_menu`；点击 `selector.product_create_button`；填写 `selector.product_title_input`、`selector.product_sku_input`、`selector.product_category_picker`、`selector.product_description_editor`；点击 `selector.product_save_draft_button`。
- 成功判断：页面出现 `selector.product_save_success_message`，或页面快照中存在示例远程商品编号。
- 失败判断：必填项校验失败、类目无法选择、页面保存失败、页面超时、出现平台规则提示。
- 截图节点：进入建档页、字段填写完成页、保存结果页、失败提示页。
- 回写字段：`task_id`、`status`、`message`、`remote_product_id`、`remote_status`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：类目映射无法确认、平台规则冲突、字段含义不明确、页面结构变化。

## 3. 图片上传流程

- 流程名称：图片上传流程。
- 输入字段：`task_id`、`store_code`、`product_code`、`sku`、`image_urls`、`image_type`。
- 页面步骤：进入 `selector.product_image_tab`；点击 `selector.image_upload_button`；选择示例图片来源；等待 `selector.image_upload_progress` 完成；检查 `selector.image_list_area`。
- 成功判断：`selector.image_list_area` 显示所有示例图片上传完成，且无失败提示。
- 失败判断：图片下载失败、图片格式不支持、上传超时、平台返回图片合规提示。
- 截图节点：图片上传前、上传进度页、上传完成页、上传失败页。
- 回写字段：`task_id`、`status`、`message`、`uploaded_images`、`failed_images`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：图片合规提示、图片重复异常、图片无法识别、平台审核提示。

## 4. 多国家复制/刊登流程

- 流程名称：多国家复制/刊登流程。
- 输入字段：`task_id`、`store_code`、`source_site`、`target_sites`、`sku`、`title`、`local_keywords`、`site_attributes`。
- 页面步骤：进入 `selector.listing_menu`；选择 `selector.source_site_selector`；点击 `selector.copy_listing_button`；选择 `selector.target_site_selector`；填写 `selector.site_attribute_form`；点击 `selector.listing_save_draft_button`。
- 成功判断：每个目标国家生成草稿或待刊登占位状态，`selector.target_site_result_table` 显示成功结果。
- 失败判断：目标国家不可用、站点字段缺失、类目差异无法自动映射、保存失败。
- 截图节点：源站点选择页、目标国家选择页、差异字段填写页、保存结果页、失败提示页。
- 回写字段：`task_id`、`status`、`message`、`target_site_results`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：站点规则冲突、类目差异无法自动处理、本地化字段缺失、平台限制提示。

## 5. 页面价格回读流程

- 流程名称：页面价格回读流程。
- 输入字段：`task_id`、`store_code`、`sku`、`page_url`、`currency`。
- 页面步骤：打开示例 `page_url`；使用 `selector.price_search_input` 查询 SKU；读取 `selector.page_price_value`、`selector.currency_label`、`selector.price_updated_at`；读取刊登状态和页面快照。
- 成功判断：读取到页面价、币种和更新时间，且 SKU 与输入字段匹配。
- 失败判断：SKU 查无记录、页面价为空、币种不匹配、页面加载失败、页面结构变化。
- 截图节点：价格搜索页、价格结果页、读取失败页。
- 回写字段：`task_id`、`status`、`message`、`sku`、`page_price`、`currency`、`read_at`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：多币种冲突、价格异常提示、页面结构变化、页面权限不足、页面出现保存/提交确认弹窗。

只读边界：

- `BIGSELLER_READ_PAGE_PRICE` 是只读采集任务。
- RPA 只读取页面价格、刊登状态、页面快照。
- 不允许点击保存按钮。
- 不允许点击提交按钮。
- 不允许修改页面价格。
- 不允许触发平台刊登、价格更新、清仓或促销动作。
- 如果页面出现价格编辑弹窗、保存确认、权限异常，应截图并转人工。

## 6. 刊登状态采集流程

- 流程名称：刊登状态采集流程。
- 输入字段：`task_id`、`store_code`、`sku`、`page_url`、`platform`、`country`。
- 页面步骤：打开示例 `page_url`；使用 `selector.listing_search_input` 查询 SKU；读取 `selector.listing_status_label`、`selector.remote_product_id_label`、`selector.listing_error_message`。
- 成功判断：采集到刊登状态、远程商品编号或明确的平台状态说明。
- 失败判断：查无记录、状态无法识别、页面超时、店铺或国家上下文不匹配。
- 截图节点：刊登列表页、查询结果页、状态详情页、失败提示页。
- 回写字段：`task_id`、`status`、`message`、`listing_status`、`remote_product_id`、`status_message`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：状态未识别、平台审核异常、店铺权限异常、页面结构变化。

## 7. 失败截图规则

- 流程名称：失败截图规则。
- 输入字段：`task_id`、`step_name`、`error_code`、`error_message`、`page_url`。
- 页面步骤：在失败发生时保持当前页面；捕获 `selector.current_page_area` 截图；记录 `selector.error_message_area` 占位内容；生成失败截图文件名。
- 成功判断：截图文件已生成，文件名包含 `task_id`、`step_name` 和时间戳占位。
- 失败判断：截图生成失败、截图路径不可写、页面已关闭、截图内容为空。
- 截图节点：失败发生页面、错误提示区域、必要时包含当前页面顶部状态区。
- 回写字段：`task_id`、`status`、`message`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：截图失败、错误信息无法识别、页面包含需要人工判断的提示。

## 8. 验证码转人工规则

- 流程名称：验证码转人工规则。
- 输入字段：`task_id`、`step_name`、`page_url`、`detected_reason`。
- 页面步骤：检查 `selector.captcha_panel`、`selector.two_factor_panel`、`selector.risk_warning_panel`；停止自动步骤；生成截图；准备人工接管回写。
- 成功判断：任务状态被标记为 `manual_required`，并记录验证码或风控提示截图。
- 失败判断：未能识别验证码区域、页面继续跳转、截图失败、回写失败。
- 截图节点：验证码页面、二次验证页面、风控提示页面。
- 回写字段：`task_id`、`status`、`message`、`manual_required_reason`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 人工接管条件：出现验证码、二次验证、人机校验、风控提示、登录状态异常。

## 9. 同账号任务串行规则

- 流程名称：同账号任务串行规则。
- 输入字段：`task_id`、`agent_name`、`store_code`、`account_alias`、`task_type`、`queue_key`。
- 页面步骤：领取任务前检查 `queue_key`；同一 `account_alias` 或 `store_code` 存在运行任务时等待；仅在前序任务结束后进入对应页面步骤。
- 成功判断：同一账号同一时间只有一个任务处于 `running` 占位状态。
- 失败判断：同账号并发领取、浏览器会话被其他任务污染、队列锁超时、任务状态不一致。
- 截图节点：任务开始页、任务结束页、队列冲突提示页。
- 回写字段：`task_id`、`status`、`message`、`queue_key`、`agent_name`、`screenshots`、`error_code`、`error_message`.
- 人工接管条件：队列锁异常、账号会话混乱、同账号任务长时间阻塞。

## 10. RPA结果回写规则

- 流程名称：RPA结果回写规则。
- 输入字段：`task_id`、`status`、`message`、`result`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`。
- 页面步骤：完成任务后汇总页面快照和步骤日志；通过 `/api/rpa/*` 回写结果；不访问数据库；不访问非 RPA 业务接口。
- 成功判断：后端返回统一成功响应，任务状态更新为 `success`、`failed` 或 `manual_required`。
- 失败判断：回写接口失败、响应结构异常、任务状态不允许回写、网络超时。
- 截图节点：最终结果页、失败结果页、人工接管提示页。
- 回写字段：`task_id`、`status`、`message`、`result`、`screenshots`、`page_url`、`page_snapshot`、`error_code`、`error_message`、`finished_at`。
- 人工接管条件：连续回写失败、结果字段无法确认、状态冲突、需要人工确认平台页面结果。

后端回写接口边界：

| 端点 | 用途 | 触发时机 | 回写字段 | 状态变化 | 失败处理 |
|---|---|---|---|---|---|
| `/api/rpa/tasks/claim/` | Agent 领取任务 | Agent 空闲并请求新任务时 | `agent_name`、`agent_version`、`capabilities`、`queue_key` | `pending` -> `claimed` | 无任务则返回空任务占位；鉴权失败则拒绝 |
| `/api/rpa/tasks/{id}/heartbeat/` | 上报执行心跳 | 任务执行中按间隔上报 | `task_id`、`agent_name`、`current_step`、`progress`、`message` | 保持 `running` | 连续失败需记录日志，后端可超时转 `failed` 或 `retrying` |
| `/api/rpa/tasks/{id}/logs/` | 上传步骤日志 | 每个关键步骤完成或失败时 | `task_id`、`level`、`step_name`、`message`、`occurred_at` | 不改变业务状态 | 上传失败可重试，不得直接写业务状态 |
| `/api/rpa/tasks/{id}/screenshots/` | 提交截图 | 失败、人工接管或关键节点留证时 | `task_id`、`step_name`、`screenshot_ref`、`message`、`occurred_at` | 不改变业务状态 | 如阶段1暂未实现，可通过 logs/result 中的 `screenshot_url` 或 `screenshots` 占位 |
| `/api/rpa/tasks/{id}/complete/` | 回写任务成功 | RPA 执行成功并完成留证后 | `task_id`、`status=success`、`message`、`result`、`screenshots`、`page_url`、`page_snapshot` | `running` -> `success` | 回写失败可重试，多次失败转人工核查 |
| `/api/rpa/tasks/{id}/fail/` | 回写任务失败或人工接管 | 任务失败、验证码、登录异常、页面变化或权限异常时 | `task_id`、`status`、`message`、`error_code`、`error_message`、`manual_required`、`manual_reason`、`last_success_step`、`failed_step`、`screenshots`、`page_url`、`page_snapshot` | `running` -> `failed`、`manual_required` 或 `retrying` | 必须截图留证；不得继续执行高风险动作 |

## 11. RPA后端执行接口契约

本节为阶段0接口契约说明，不实现后端接口代码，不实现 RPA 浏览器自动化脚本。

### 11.1 领取任务

- 接口：`POST /api/rpa/tasks/claim/`
- 用途：Agent 领取一个可执行任务。
- 请求字段：`agent_name`、`agent_version`、`capabilities`、`queue_key`。
- 返回字段：`task_id`、`task_type`、`business_type`、`business_id`、`payload`、`queue_key`、`status`。
- 状态流转：`pending` -> `claimed`。

### 11.2 任务心跳

- 接口：`POST /api/rpa/tasks/{id}/heartbeat/`
- 用途：Agent 上报任务仍在执行，供后端判断超时。
- 请求字段：`agent_name`、`current_step`、`progress`、`message`。
- 返回字段：`task_id`、`status`、`server_time`、`continue_running`。
- 状态流转：保持 `running`，如后端要求停止则转人工或失败。

### 11.3 日志上传

- 接口：`POST /api/rpa/tasks/{id}/logs/`
- 用途：上传步骤日志，不写业务状态。
- 请求字段：`level`、`step_name`、`message`、`occurred_at`。
- 返回字段：`task_id`、`log_id`、`status`。

### 11.4 截图提交

- 接口：`POST /api/rpa/tasks/{id}/screenshots/`
- 用途：提交失败截图或关键节点截图。
- 请求字段：`step_name`、`screenshot_ref`、`message`、`occurred_at`。
- 返回字段：`task_id`、`screenshot_id`、`screenshot_url`、`status`。
- 说明：如阶段1暂未实现独立截图接口，必须通过日志或 result 携带 `screenshot_url` 或 `screenshots` 占位字段。

### 11.5 任务完成

- 接口：`POST /api/rpa/tasks/{id}/complete/`
- 用途：回写执行成功结果。
- 请求字段：`task_id`、`status=success`、`message`、`result`、`screenshots`、`page_url`、`page_snapshot`。
- 返回字段：`task_id`、`status`、`finished_at`。
- 状态流转：`running` -> `success`。

### 11.6 任务失败

- 接口：`POST /api/rpa/tasks/{id}/fail/`
- 用途：回写执行失败结果或人工接管原因。
- 请求字段：`task_id`、`status`、`message`、`error_code`、`error_message`、`screenshots`、`page_url`、`page_snapshot`。
- 返回字段：`task_id`、`status`、`finished_at`。
- 状态流转：`running` -> `failed` 或 `manual_required`。

### 11.7 禁止访问范围

- RPA Agent 只能访问 `/api/rpa/*`。
- RPA Agent 不得访问 `/api/finance/*`、`/api/internal/finance/*`、`/admin/`。
- RPA Agent 不得直连 MySQL、Redis 或任何数据层。
- RPA result 只回写执行结果，不做业务判断。
- RPA 不决定清仓、不决定补货、不决定是否上架。
- RPA 改价任务只能执行后端已审批通过的任务，必须携带审批凭证字段。
