# P1-B-004 Change Log

## Task

RPA任务页面阶段1接口联调。

## Preconditions

- 当前分支：`feature/phase1-b-frontend-api-integration`
- 当前 HEAD 未在 `feature/ar0-001-stage0-file-scope` 分支上开发。
- 本次变更未修改 `backend/`、`rpa-agent/`、`docs/04_rpa/`。
- 未新增真实 RPA 脚本。
- 未连接真实 BigSeller。
- 未写入真实 BigSeller 账号、密码、Cookie、Session 或真实选择器。

## Input Documents

- 已读取：`docs/04_rpa/rpa_api_protocol.md`
- 已读取：`docs/00_stage0/frontend_api_mapping.md`
- 缺失：`docs/03_api/rpa_task_api_contract.md`

## Changes

- `frontend/src/api/rpa.js`
  - 保持管理后台使用 `/api/internal/rpa/tasks/` 与 `/api/internal/rpa/tasks/{id}/`。
  - 继续保留 Mock fallback。
  - 保留注释说明：Agent 执行接口 `/api/rpa/*` 需要后端 Agent 身份，不由前端管理页调用。

- `frontend/src/mock/rpa.js`
  - 补充 `task_id`、`task_type`、`business_type`、`business_id`、`status`、`agent`、`retry_count`、`payload`、`result`、`screenshots`、`logs`、`error_message`、`manual_required`。
  - 截图使用 demo URL，占位页面快照使用示例文本。
  - 未包含真实截图、真实页面快照、真实账号、密码、Cookie、Session 或真实选择器。

- `frontend/src/views/rpa/RPATaskList.vue`
  - 展示 RPA 任务列表、状态标签、loading、error、empty、fallback 提示。
  - 查看详情、人工接管操作仅为占位。

- `frontend/src/views/rpa/RPATaskDetail.vue`
  - 展示任务基础信息、payload JSON、result JSON、步骤日志、截图列表和错误原因。
  - 重试按钮、人工接管按钮仅为占位。

- `frontend/README.md`
  - 增加阶段1 RPA页面联调说明。

## Boundary Notes

- 管理后台查看 RPA任务使用 `/api/internal/rpa/*` 占位联调。
- RPA Agent 执行接口 `/api/rpa/*` 未被前端管理页调用。
- 前端管理页面未模拟 RPA Agent token。
- 前端管理页面未访问 `/api/finance/*`。
- 前端未调用 `/admin/`。
- 前端未执行真实 RPA。
- 前端未连接真实 BigSeller。
- 未提交真实截图或真实页面快照。

## Validation

- `rg "requestWithMockFallback\(\{[^\n]+url: [\`']\/api\/rpa|url: [\`']\/api\/finance|url: [\`']\/admin" frontend/src/api/rpa.js frontend/src/views/rpa`：无结果。
- `rg "RPA_AGENT_TOKEN|Authorization|Cookie|Session|BIGSELLER_PASSWORD|BIGSELLER_COOKIE|BIGSELLER_SESSION|真实账号|真实密码" frontend/src/api/rpa.js frontend/src/mock/rpa.js frontend/src/views/rpa`：无结果。
- `git diff --name-only -- backend rpa-agent docs/04_rpa`：无结果。
- 已执行：`cd frontend && npm run build`
- 结果：构建通过。
- 观察项：
  - Rollup 移除了 `@vueuse/core` 中位置不合规的 `/* #__PURE__ */` 注释。
  - 仍存在 Vite chunk size warning：`dist/assets/index-BRmpsQMS.js` 约 `1,148.81 kB`，gzip 后约 `372.45 kB`。
  - 阶段1不强制拆包，继续作为性能优化观察项跟踪。
