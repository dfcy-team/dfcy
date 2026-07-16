# UI-P1 基础认证与页面骨架测试报告

## 1. 测试范围

- JWT 登录、会话恢复、Bearer 注入、单次 refresh 和会话清理。
- `/api/internal/auth/me/` 的可信角色、权限、租户与 `data_scope`。
- 角色菜单、路由守卫、403 页面和角色工作台。
- loading、empty、error、forbidden、conflict、invalid、partial、offline 状态映射。
- 桌面与窄屏布局。

## 2. 后端结果

| 检查 | 结果 | 证据 |
|---|---|---|
| `python manage.py check` | PASS | System check identified no issues |
| `makemigrations --check --dry-run` | PASS | No changes detected |
| `pytest -q backend/tests/test_auth_api.py` | PASS | 6 passed |
| 全量 `pytest -q --disable-warnings` | PASS | 252 passed |

首次运行时本机虚拟环境漏装仓库 `requirements.txt` 已声明的 `mysqlclient`，导致 MySQL 驱动检查 1 项失败。补装 `mysqlclient 2.2.8` 后重新执行全量测试，结果为 252 passed。

## 3. 前端结果

| 检查 | 结果 | 证据 |
|---|---|---|
| `npm test` | PASS | 3 files，61 tests passed |
| UI-P1 专项测试 | PASS | 28 tests passed |
| `npm run build` | PASS | 1873 modules transformed |
| 第三方 PURE 注释提示 | P2观察 | Rollup 移除无法识别位置的注释，不阻断构建 |

### R1 P1定向整改验证

- 扫描 `router/index.js` 中全部非公开路由，逐条验证均存在 `routeCapabilities` 合同。
- 验证未知路径默认拒绝。
- 验证仅有 `finance.view` 的用户不能访问 `/finance/imports`，具备 `finance.import` 后才可访问。
- 验证 external 供应商用户可访问自己的任务页面，但不能访问内部商品和财务页面。
- 验证 view-only 用户不能使用 `replenishment.review`、`alerts.manage`、`reports.export`、`config.manage`、`config.rollback`、`finance.reconcile` 等动作。
- 验证所有已执行的共享页面动作均声明对应后端权限码，通用组件在展示和点击时进行双重校验。

## 4. 视觉与响应式结果

| 场景 | 结果 | 核验 |
|---|---|---|
| 真实模式登录页，1440x900 | PASS | 登录表单、环境和认证边界完整，无重叠 |
| 登录页窄屏，390x844 | PASS | `scrollWidth=clientWidth=390`，无横向溢出 |
| Mock角色工作台，1440x900 | PASS | 侧栏 248px，主内容起点 248px，角色入口正确 |
| 工作台窄屏，390x844 | PASS | 桌面侧栏隐藏，移动菜单显示，header无溢出 |

视觉检查过程中发现并修复 Element Plus 布局组件按需样式遗漏；修复后重新执行测试和构建均通过。

## 5. 未执行项

- 未在本机执行真实 Pilot 账号登录，因为本地未启动可用的 Pilot 后端与 MySQL 会话环境。
- 未执行浏览器认证态 E2E，因为当前仓库未配置专用 E2E 账号和隔离测试数据。
- 未执行生产 token Cookie/黑名单方案，因为该方案尚待架构复审冻结。

## 6. 测试结论

UI-P1 代码、全量后端测试、前端组件测试、构建和静态视觉验收已完成，具备提交架构复审条件。真实 Pilot 登录仍需在受控部署环境复验。
