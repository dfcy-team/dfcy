# UI-P3-ARCH-R1 架构复审提示

你现在在`saas-collab-system`中执行UI-P3架构复审。

任务编号：`UI-P3-ARCH-R1`

任务名称：RPA任务、运行、设备与人工队列基础复审

本次任务只审核、不修复，只允许创建：

- `docs/00_stage0/review/ui_p3_arch_r1_recheck.md`

禁止修改：

- `backend/`
- `frontend/`
- `rpa-agent/`
- `docs/04_rpa/`
- 配置文件、迁移和业务代码

## 1. 复审依据

- `docs/03_api/ui_p3_rpa_task_device_contract.md`
- `docs/03_api/phase2_frontend_api_contract.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/00_stage0/review/ui_p3_rpa_task_device_change_log.md`
- `docs/05_test/ui_p3_rpa_task_device_test_report.md`
- 本分支相对最新`main`的实际代码差异

## 2. 页面与路由合同

检查以下页面是否存在并可达：

- `/rpa/tasks`、`/rpa/tasks/{id}`
- `/rpa/runs`、`/rpa/runs/{id}`
- `/rpa/devices`、`/rpa/devices/{id}`
- `/rpa/manual-queue`
- `/rpa/stability`
- `/rpa/account-locks`
- `/rpa/page-signatures`

确认未登记的非公开路径默认拒绝；`/rpa/attempts*`只作为兼容重定向，不作为正式合同。

## 3. API分区

确认浏览器管理端只调用`/api/internal/rpa/*`，不调用以下Agent执行端点：

- `/api/rpa/tasks/claim/`
- `/api/rpa/tasks/{id}/heartbeat/`
- `/api/rpa/tasks/{id}/logs/`
- `/api/rpa/tasks/{id}/screenshots/`
- `/api/rpa/tasks/{id}/complete/`
- `/api/rpa/tasks/{id}/fail/`

确认internal管理端不模拟Agent Token，不访问`/api/finance/*`或`/admin/`。

## 4. tenant、data_scope与权限

检查：

1. 所有internal RPA查询按tenant过滤。
2. 每个权限使用其自身data_scope，不能借用其他permission scope。
3. `custom.rpa_task_ids`限制任务、运行和人工队列。
4. `custom.rpa_device_ids`限制设备和相关运行。
5. `custom.rpa_platforms`限制页面签名。
6. external和RPA用户不能访问internal管理接口。
7. 查看权限不能执行人工分配、Mock重试或设备dry-run。

权限合同：

- `rpa.tasks.view`
- `rpa.tasks.manage`
- `rpa.devices.view`
- `rpa.devices.dry_run`
- `rpa.stability.view`

## 5. 双状态机

分别核验任务状态和运行状态，不得混用或互相覆盖：

- 任务：`pending/claimed/running/success/failed/retrying/manual_required/cancelled`
- 运行：`claimed/running/success/failed/retrying/manual_required/cancelled`

确认：

1. internal管理动作不能直接把任务改为`success`。
2. 人工分配只允许`manual_required`。
3. Mock重试只允许`failed`或`manual_required`。
4. 状态冲突返回409，业务规则或重试上限返回422。
5. 每次claim生成独立运行记录。

## 6. 设备与dry-run

设备模式只能是：

- `mock`
- `dry_run`
- `production_disabled`

确认dry-run不启动浏览器、不访问真实平台、不执行页面动作；`production_disabled`拒绝dry-run和Agent claim；设备响应不泄露Token、完整指纹或IP白名单。

## 7. 前端状态和动作

检查任务、运行、设备、人工队列、锁和签名页面具备loading/error/empty/list/detail或等价状态，分页按`data.count/next/previous/results`解析。

确认动作按钮同时受路由能力和action permission控制；401/403/404/409/422不得回退Mock；仅实际API成功标记`connected`。

## 8. 测试复核

在环境允许时实际运行并记录：

- Django check
- migration一致性
- UI-P3专项pytest
- 全量pytest
- UI-P3专项Vitest
- 全量Vitest
- npm build
- Docker配置检查
- RPA JSON校验
- API路径和凭据安全扫描

未执行项必须写明原因，不得复制变更日志作为实际执行结果。

## 9. 安全边界

确认无真实平台连接、真实凭据、真实业务数据、真实浏览器自动化，以及自动改价、刊登、清仓、补货或财务操作。

## 10. 报告结构

# UI-P3-ARCH-R1 RPA任务与设备基础复审报告

## 1. 复审对象
## 2. 复审结论
## 3. 页面与路由合同
## 4. API分区
## 5. tenant与data_scope
## 6. 权限与动作
## 7. 任务/运行双状态机
## 8. 设备与dry-run
## 9. 前端完整状态
## 10. 测试与构建
## 11. 安全扫描
## 12. P0
## 13. P1
## 14. P2
## 15. 是否建议UI-P3收尾

结论规则：有P0为FAIL；无P0但有P1为CONDITIONAL_PASS；无P0/P1为PASS。
