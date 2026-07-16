# UI-P1 架构复审任务提示

## 任务编号

`UI-P1-ARCH-R1`

## 任务名称

真实登录会话、角色菜单、统一页面骨架、完整状态组件和角色工作台复审

## 复审性质

只审核，不修复。不得修改 `backend/`、`frontend/`、`rpa-agent/` 业务代码，只生成复审报告。

## 允许输出

- `docs/00_stage0/review/ui_p1_arch_recheck_report.md`

## 复审依据

- `docs/00_stage0/review/ui_p0_current_state_contract_review.md`
- `docs/00_stage0/review/ui_p1_foundation_change_log.md`
- `docs/03_api/ui_api_interaction_contract.md`
- `docs/05_test/ui_p1_foundation_test_report.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `backend/apps/accounts/`
- `backend/apps/permissions/`
- `backend/tests/test_auth_api.py`
- `frontend/src/api/`
- `frontend/src/stores/`
- `frontend/src/router/`
- `frontend/src/layouts/`
- `frontend/src/components/AppPage.vue`
- `frontend/src/components/AppState.vue`
- `frontend/src/views/auth/`
- `frontend/src/views/dashboard/`
- `frontend/tests/ui-p1-foundation.spec.js`

## 必须复审

1. `VITE_USE_MOCK=false` 时 login、refresh、me 是否只调用真实后端，不静默回退 Mock。
2. Bearer token 注入、单次 refresh、失败清理和登录跳转是否形成闭环。
3. `/auth/me/` 是否返回可信 `tenant_id`、roles、permissions、`data_scope`、`is_superuser`。
4. 菜单和路由是否按后端权限收敛，是否仍明确“前端不是安全边界”。
5. external、RPA、普通 internal 和 finance 权限是否不会互相越界。
6. 页面骨架是否统一，桌面/窄屏是否无重叠和横向溢出。
7. loading、empty、error、403、409、422、partial、offline 状态是否可复用且映射明确。
8. 角色工作台是否只展示可信角色入口，是否避免虚构业务数字。
9. 是否存在真实账号、密码、Token、Cookie、Session、API Key、真实平台或真实业务数据。
10. 仓库声明的 MySQL 驱动、全量后端测试与 Pilot/Docker 运行环境是否保持一致。
11. refresh token 使用 `sessionStorage` 是否仅可作为 Pilot 方案，生产前是否必须迁移 HttpOnly Cookie。
12. 客户端退出是否需要补充服务端 refresh token 撤销或黑名单。

## 建议实际执行

```text
backend: python manage.py check
backend: python manage.py makemigrations --check --dry-run
backend: pytest -q
frontend: npm test
frontend: npm run build
browser: 真实Pilot账号登录、刷新、过期、退出、角色菜单、403、桌面与窄屏检查
```

任何未执行命令必须记录为“未执行”并说明原因，不得复制本变更日志结论代替实际复审结果。

## 结论规则

- 存在 P0：`FAIL`
- 无 P0 但存在 P1：`CONDITIONAL_PASS`
- 无 P0/P1，仅有 P2：`PASS`

## 报告结构

```text
# UI-P1-ARCH-R1 架构复审报告
## 1. 复审对象
## 2. 复审结论
## 3. 认证与会话
## 4. 可信用户合同
## 5. 角色菜单与路由
## 6. 页面骨架与状态组件
## 7. 角色工作台
## 8. tenant、data_scope与权限边界
## 9. 测试、构建与视觉证据
## 10. 安全扫描
## 11. P0
## 12. P1
## 13. P2
## 14. 是否允许UI-P1收尾
## 15. 是否允许进入UI-P2
```
