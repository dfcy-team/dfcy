# UI-P2-ARCH-R2 架构复审提示

请执行 `UI-P2-ARCH-R2`，只审核 UI-P2 四项 P1 整改，不修改业务代码。

## 1. 复审依据

- `docs/00_stage0/review/ui_p2_arch_recheck_report.md`
- `docs/00_stage0/review/ui_p2_p1_fix_change_log.md`
- `docs/03_api/ui_p2_system_masterdata_contract.md`
- `docs/05_test/ui_p2_system_masterdata_test_report.md`

## 2. UI-P2-P1-001 Data scope

确认：

1. permission 与 Data scope 来自同一启用角色授权链。
2. 只有 permission、缺少对应 scope 时返回 `403`。
3. 用户、部门和角色查询执行 `all/department/own/custom`。
4. 基础档案执行 `platform_ids/store_ids/warehouse_ids/supplier_ids` 自定义范围。
5. 列表、详情、更新、启停和创建执行一致范围。
6. 安全运维和全量治理动作要求 `all` scope。
7. 跨 tenant、跨用户、跨部门和跨自定义对象不能访问。

## 3. UI-P2-P1-002 角色动作权限流程

确认：

1. 新建角色在展示和请求前均校验 `system.roles.manage`。
2. 用户目录提供角色绑定入口，展示和请求前均校验 `system.users.manage`。
3. 可分配角色使用 `/api/internal/system/user-role-options/`，不因缺少 `system.roles.view` 导致流程中断。
4. 后端同时校验目标用户范围和可分配 `role_ids`，直接调用 API 不能绕过。
5. 用户角色和角色 permission/Data scope 变更均写审计，审计包含变更前后范围。

## 4. UI-P2-P1-003 角色分页

确认：

1. 前端消费 `count/page/page_size`。
2. 存在分页控件并支持翻页加载。
3. 超过 20 条角色时可访问第二页和最后一页。
4. 空页或数据变化后仍可返回有效页。

## 5. UI-P2-P1-004 连接状态

确认：

1. 初始状态为 `useMock ? mock : pending`。
2. Mock 不标记为 connected。
3. 仅真实 API 成功响应标记 connected。
4. 网络 fallback 标记 degraded。
5. 401/403/404/409/422 等 HTTP 失败不得保留 connected。

## 6. 必须执行

- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `pytest -q tests/test_ui_p2_system_masterdata.py`
- 后端全量 pytest
- `npm test -- --run tests/ui-p2-system-masterdata.spec.js`
- 前端全量 Vitest
- `npm run build`
- 权限、路径、状态、真实凭据和真实平台连接扫描
- `git diff --check` 与文件范围检查

未执行项必须记录原因，不得直接引用整改日志代替独立执行结果。

## 7. 输出

创建 `docs/00_stage0/review/ui_p2_arch_r2_recheck_report.md`，结论只能为：

- 存在 P0：`FAIL`
- 无 P0 但仍有 P1：`CONDITIONAL_PASS`
- 无 P0/P1：`PASS`

报告必须逐项给出四个原 P1 的关闭证据，并明确是否允许 UI-P2 正式收尾及进入下一阶段界面设计。
