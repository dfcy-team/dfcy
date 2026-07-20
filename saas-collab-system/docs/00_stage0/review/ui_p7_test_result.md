# UI-P7 测试验证记录

## 1. 执行时间

2026-07-17，架构设计员电脑，本地 UI-P7 分支。

## 2. 后端

| 检查 | 实际结果 |
|---|---|
| `python manage.py check` | PASS，0 issues |
| `python manage.py makemigrations --check --dry-run` | PASS，No changes detected |
| UI-P7 定向 pytest | PASS，8 passed |
| 后端全量 pytest | PASS，330 passed |

定向测试覆盖：401/403、permission-specific data_scope、未知 scope key、固定 Mock 无业务副作用、幂等冲突、创建审计、状态防绕过、审批职责分离和审计不可变。

合同覆盖核对：37 个唯一 `method + path` 组合均有实现；Django 路由表为 35 条 URL pattern，其中恢复计划和发布计划的集合路径各同时支持 `GET`/`POST`。

## 3. 前端

| 检查 | 实际结果 |
|---|---|
| `npm ci` | PASS，197 packages，0 vulnerabilities |
| `npm test` | PASS，9 files / 105 tests |
| `npm run build` | PASS |

观察项：`npm ci` 报告 `esbuild`、`vue-demi` 的 allow-scripts 提示；Vite 构建报告第三方 `@vueuse/core` PURE 注释位置警告。二者均未阻断构建。

## 4. 系统与安全

| 检查 | 实际结果 |
|---|---|
| `docker compose config -q` | PASS；因未加载真实 `.env`，仅输出空变量提示 |
| RPA JSON 解析 | PASS，16 个 JSON，0 invalid |
| 私钥/常见真实密钥模式扫描 | PASS，0 matches |
| `git diff --check` | PASS |
| `frontend/dist`、`node_modules`、RPA运行目录跟踪检查 | PASS；仅 `.gitkeep` 在跟踪范围 |

## 5. 本地浏览器冒烟

- Vite 本地服务：`http://127.0.0.1:4176/`。
- API合同目录、试点准入和发布记录页面加载成功；菜单、Mock 标识、表格和精确权限动作可见。
- 默认桌面视口与 `390 x 844` 窄屏均未发现页面级横向溢出。
- 浏览器控制台错误：0。

## 6. 未执行项

- 受控试点真实认证浏览器 E2E：未执行。本轮完成代码、Mock/dry-run 和本地自动化，需在独立实现复审中使用受控账号验证 401/403、权限切换、空数据和页面响应式布局。
- 真实双主机网络、恢复和发布演练：未执行。此类操作必须在审批后的受控主机由人工执行，Web API 仅记录证据。
- 真实平台、真实 RPA 和资金动作：按边界禁止执行。

## 7. 结论

本地自动化和静态安全验证通过，无 P0/P1 测试阻断项；允许进入 `UI-P7-ARCH-R1`，但在独立复审和受控浏览器 E2E 通过前不得正式收尾或标记 `connected`。

## 8. R1 P1 整改后验证（2026-07-20）

| 检查 | 实际结果 |
|---|---|
| Django check | PASS，0 issues |
| migration 一致性 | PASS，No changes detected |
| UI-P7 后端专项 pytest | PASS，52 passed |
| 后端全量 pytest | PASS，374 passed |
| UI-P7 前端专项测试 | PASS，11 passed |
| 前端全量测试 | PASS，9 files / 110 passed |
| `npm run build` | PASS |
| Docker Compose 静态解析 | PASS；仅未加载真实环境变量的空变量提示 |
| RPA JSON 校验 | PASS，16 个 JSON，0 invalid |
| 常见真实密钥模式扫描 | PASS，0 matches |
| Git 跟踪运行产物检查 | PASS；RPA运行目录无非 `.gitkeep` 跟踪文件 |

### 8.1 受控真实认证浏览器验证

- 使用本地临时 SQLite、demo tenant 和受控 demo internal superuser 完成真实 JWT 登录；未使用或保存生产账号。
- 直接访问 `/governance/api-contracts/1` 可主动加载后端详情，页面展示冻结字段 `permission`、`scope_keys`、`response_schema_version`、`evidence_status`。
- 访问 `/pilot/readiness` 可展示后端返回的受控环境、门禁、证据、责任人和有效期字段。
- API能力状态保持 `sandbox`；未验证能力没有标记为 `connected`。
- 浏览器控制台 error/warn：0。
- Mock 浏览器链路验证恢复状态 `draft -> review_pending -> approved -> scheduled -> running -> success`，发布及回滚状态 `draft -> review_pending -> approved -> scheduled -> running -> rollback_required -> rolled_back`。

### 8.2 非阻断观察项

- Vite/Rollup 仍报告第三方 `@vueuse/core` PURE 注释位置警告，构建成功。
- Docker Compose 未加载真实 `.env`，因此输出空变量提示；本轮未创建真实环境文件。
- 真实双主机恢复、发布、回滚、真实平台和资金动作继续按安全边界禁止执行。

### 8.3 全量测试日期口径修正

首次全量后端重跑在供应商绩效既有测试中出现 1 个跨日失败。原因是测试使用系统本地 `date.today()`，而 Django `created_at__date` 按项目时区计算。测试已改用 `timezone.localdate()`，未修改业务逻辑；该模块复测 `9 passed`，最终全量 `374 passed`。

本轮证据允许进入独立 `UI-P7-ARCH-R2`，但是否正式收尾必须由 R2 报告决定。

## 9. R2 P1 整改后验证（2026-07-20）

| 检查 | 实际结果 |
|---|---|
| Django check | PASS，0 issues |
| migration 一致性 | PASS，No changes detected |
| 临时 SQLite 全量迁移 | PASS，`pilot.0003` 成功应用 |
| UI-P7 后端专项 pytest | PASS，56 passed |
| 后端全量 pytest | PASS，378 passed |
| UI-P7 真实组件状态测试 | PASS，20 passed |
| 前端全量测试 | PASS，10 files / 130 passed |
| `npm run build` | PASS |
| Docker Compose 静态解析 | PASS，仅有未加载真实环境变量的空值提示 |
| RPA JSON 解析 | PASS，16 files / 0 invalid |
| 高置信密钥模式扫描 | PASS，0 matches |
| `git diff --check` | PASS，仅有行尾转换提示 |

本轮新增验证覆盖容量五态及阈值映射、回滚批准数据库唯一性、受保护模型批量创建拒绝、计划创建失败不可变审计，以及真实 Vue 组件的 loading/empty/401/403/404/409/422/partial/stale/offline 状态。第三方 `@vueuse/core` PURE 注释位置警告仍为非阻断观察项。

本轮证据允许进入独立 `UI-P7-ARCH-R3`，但 R3 通过前不得正式收尾或标记真实能力为 `connected`。
