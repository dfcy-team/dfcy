# UI-P3 RPA任务与设备基础变更日志

## 1. 目标

冻结并实现 RPA 任务、运行、设备、人工队列、账号锁和页面签名 internal 管理合同，同时保持 Agent 执行接口和真实平台边界不变。

## 2. 后端

- 新增 `/api/internal/rpa/*` 管理 API、分页、脱敏和统一错误响应。
- 新增 `rpa.tasks.*`、`rpa.devices.*`、`rpa.stability.view` 权限。
- 增加 permission-specific data_scope 过滤。
- 设备增加 `mock/dry_run/production_disabled` 模式。
- 任务增加人工负责人、原因和分配时间。
- 人工分配、Mock 重试和设备 dry-run 写入操作审计。

## 3. 前端

- 建设任务、运行、设备、人工队列、稳定性、账号锁和页面签名页面。
- 任务与运行状态分开显示。
- action permission 控制人工分配、Mock重试和设备 dry-run。
- 保留 Mock/API 切换；只有实际 API 成功标记 connected。

## 4. 安全边界

- 未接入真实 BigSeller、Shopee、TikTok/TK。
- 未提交真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未新增真实浏览器自动化脚本。
- 未允许自动改价、刊登、清仓、补货或财务动作。
- RPA 管理前端未调用 Agent 执行接口。

## 5. 待复审

完成自动化测试、构建和安全扫描后，由架构员按 UI-P3 复审提示执行独立复审。

## 6. 验证结果

- Django check：PASS。
- migration一致性：PASS，无遗漏迁移。
- UI-P3专项后端测试：10 passed。
- 全量后端测试：281 passed。
- UI-P3专项前端测试：8 passed。
- 全量前端测试：77 passed。
- 前端生产构建：PASS，1909 modules transformed。
- Docker配置、16个RPA JSON、Agent执行路径和凭据形态扫描：PASS。
- `/rpa/tasks`、`/rpa/devices`、`/rpa/manual-queue`已完成本地Mock模式页面实测。

详细证据见`docs/05_test/ui_p3_rpa_task_device_test_report.md`。下一步由架构员依据`docs/00_stage0/review/ui_p3_arch_recheck_prompt.md`执行独立R1复审。

## 7. R1整改

- `UI-P3-R1-P1-001`：运行记录custom scope改为单scope内按已配置任务/设备维度取交集，多角色scope之间取并集；新增交叉组合越权和多角色并集测试。
- `UI-P3-R1-P1-002`：稳定性Mock删除非法`retry_wait`，使用`retrying`，并显式返回`task_states`、`run_states`、`manual_required`和只读边界；新增状态集合合同测试。
- 整改后UI-P3后端专项12 passed、全量283 passed；前端专项9 passed、全量78 passed；生产构建通过。
