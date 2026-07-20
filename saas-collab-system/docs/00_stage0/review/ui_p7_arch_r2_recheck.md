# UI-P7-ARCH-R2 独立整改复审报告

## 1. 复审对象与基线

- 任务编号：`UI-P7-ARCH-R2`
- 复审分支：`feature/ui-p7-governance-pilot-readiness`
- 工作树 HEAD：`17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`
- 对比基线：`origin/main@17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`
- 原结论：`CONDITIONAL_PASS`
- 原问题：`UI-P7-R1-P1-001` 至 `UI-P7-R1-P1-005`
- 复审日期：2026-07-20
- 复审方式：独立静态审查、实际命令验证、受控本地 JWT 浏览器验证；未直接采信整改日志中的自报结论。
- 复审性质：只审核，不修复；本次仅创建本报告，未修改业务代码。

当前 UI-P7 实现仍位于未提交工作树中，因此本报告审核的是当前工作树快照，不构成已提交分支成果证明。

## 2. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：3 项尚未关闭。
- P2：2 项非阻断观察项。
- 原 P1-003、P1-004 已关闭；原 P1-001、P1-002、P1-005 仍存在未满足的关闭条件。
- 当前不允许 UI-P7 正式收尾、提交合并或标记 `connected`；允许继续定向整改后执行 R3。

## 3. 五项原 P1 关闭情况

| 原P1编号 | 问题 | 是否关闭 | 独立证据 | 备注 |
|---|---|---|---|---|
| UI-P7-R1-P1-001 | 公共响应模型、枚举和错误合同未统一 | 否 | `CapacityObservation` 合同允许 `critical`，模型仅有 `partial`；序列化与筛选均把 `warning/critical` 合并为 `partial` | 其他响应、分页及错误壳已明显补齐，但容量合同仍不精确 |
| UI-P7-R1-P1-002 | 状态防绕过、回滚批准失效和失败审计不完整 | 否 | 回滚批准引用仅由服务层 `exists()` 检查；数据库无唯一约束；创建失败未进入失败审计；受保护模型仍存在批量创建绕过面 | 关键字段保护、成功/失败 action 审计和终态回归已大幅完善 |
| UI-P7-R1-P1-003 | permission-specific data_scope 严格性不足 | 是 | 未知 key、非法值、重复值、空数组、超限数组及未登记值均拒绝；ALL 限定受控资源；创建/详情/action 使用对应 permission scope；越权矩阵有测试 | 满足 R2 关闭标准 |
| UI-P7-R1-P1-004 | 恢复、发布和回滚页面动作链未完成 | 是 | 页面已提供创建、提交、批准/拒绝、排期、开始、结果记录、人工恢复、取消、回滚批准、回滚恢复、回滚结果；按 plan/review/record/rollback 权限显示；详情 URL 可直达 | 页面仍只记录受控外部结果，不执行基础设施命令 |
| UI-P7-R1-P1-005 | 自动化与受控 E2E 证据不足 | 否 | 后端与前端命令均通过，并完成受控 JWT 冒烟；但前端专项测试仍以源码字符串扫描为主，未挂载组件覆盖状态矩阵；无效详情 URL 未显示 404 | 需补组件测试及权限/错误/响应式受控 E2E |

## 4. 响应与错误合同

### 已通过

- 成功响应统一使用 `success/code/message/data`。
- 列表响应使用 `count/next/previous/results` 分页结构。
- 失败响应由统一异常处理器输出 `success=false`、`data=null`。
- 未知字段、分页、字段校验、幂等冲突、状态冲突、门禁失败、职责分离和回滚批准均有明确 HTTP/code 测试。
- 非法枚举、日期和排序参数不会静默返回空列表。
- governance、assistant、readiness、topology 的字段与前端 Mock 已基本对齐冻结合同。

### 未关闭问题

冻结合同要求容量状态为 `normal/warning/critical/unknown/stale`，但当前模型状态为 `valid/partial/missing/stale`。`CapacityObservationSerializer` 将 `partial` 固定映射为 `warning`，容量查询又把 `warning` 和 `critical` 都映射为 `partial`，导致：

1. 后端无法稳定表达 `critical`。
2. `status=warning` 与 `status=critical` 的筛选语义相同。
3. 同时存在 warning/critical 阈值时，单一 `threshold` 输出会丢失其中一档语义。
4. 前端测试只扫描 `status: 'normal'`，没有验证 critical 映射和筛选。

## 5. 状态机与不可变审计

### 已通过

- 恢复/发布状态修改集中在事务服务中，并使用行锁、版本号和幂等控制。
- 已批准关键字段、批准字段和状态受到实例保存、QuerySet update/delete 与 bulk_update 保护。
- 成功与 action 失败路径可写不可变审计；审计记录禁止 update/delete，tenant 和关联对象使用保护语义。
- 恢复与发布的终态、`manual_required`、`cancelled`、`rollback_required`、`rolled_back` 已增加回归覆盖。
- API 只记录外部受控操作结果，没有 Docker、Shell、SQL、SSH、恢复或发布执行能力。

### 未关闭问题

1. `rollback_approval_ref` 的跨计划唯一性仍依赖服务层先查询再写入，数据库没有唯一约束；并发批准存在竞态，直接 ORM/bulk 路径也不能由数据库兜底。
2. 受保护 QuerySet 阻止 update/delete/bulk_update，但仍允许业务对象通过 bulk_create 带入受保护状态或批准字段，防绕过边界没有在模型/数据库层闭合。
3. 恢复计划和发布计划集合创建只在成功后写审计；请求字段、data_scope、幂等或其他创建校验失败时没有失败审计。R2 要求所有关键失败动作均保留不可变失败记录，当前只覆盖 action/result 视图。

## 6. permission-specific data_scope

结论：**通过**。

- 未知 key、非法值、重复值、空数组、数组超限均明确拒绝。
- ID、环境和枚举值必须属于受控登记集合。
- `ALL` 仅覆盖已登记的受控试点资源。
- 创建、详情和每个 action 均按对应 permission 的完整 scope 求值。
- 已覆盖 external、RPA、跨 tenant、system、合法超 scope 空分页、详情 404、请求体 403 和 action 403。
- 未发现前端扩大 tenant 或 data_scope 的逻辑。

## 7. 前端动作、详情与状态

### 已通过

- 恢复/发布页面动作链完整，并以 plan/review/record/rollback 权限分别控制显示。
- API 合同和助手治理详情路由可根据 `route.params.id` 主动加载；受控浏览器实测 `/governance/api-contracts/1` 可直达详情。
- 试点准入页通过真实 API 展示 `sandbox`，没有把 HTTP 200 自动标记为 `connected`。
- 页面未提供 WebShell、SQL、Docker、SSH、真实部署、真实恢复、真实回滚或平台连接能力。

### 未关闭问题

- 直接访问不存在的 `/governance/api-contracts/999999` 后，页面没有显示 404、资源不存在或统一错误状态；详情加载失败只设置 `errorMessage`，主页面仍保持 ready，错误没有进入可见 `AppState`。
- 前端专项测试没有挂载组件，未对 loading、empty、401、403、404、409、422、stale/offline、分页和动作权限矩阵进行真实渲染断言。

## 8. 测试、构建与受控 E2E

| 检查 | R2实际结果 | 备注 |
|---|---|---|
| Django check | PASS | `System check identified no issues` |
| migration 一致性 | PASS | `No changes detected` |
| UI-P7 后端专项 pytest | PASS | `52 passed in 5.85s` |
| 后端全量 pytest | PASS | `374 passed in 35.17s` |
| UI-P7 前端专项测试 | PASS | `11 passed`；主要为源码扫描，不等同于组件测试 |
| 前端全量测试 | PASS | 9 files / 110 passed |
| `npm run build` | PASS | 构建成功；保留第三方 PURE 注释警告 |
| Docker Compose 静态解析 | PASS | exit 0；未加载真实环境变量，仅有空变量提示 |
| RPA JSON 校验 | PASS | 16 files，0 invalid |
| 安全扫描 | PASS | 真实密钥模式 0，禁止执行入口 0，RPA运行产物 0 |
| 受控 JWT 登录 | PASS | 本地临时 SQLite 与受控 demo 账号；未记录凭据 |
| API 合同详情直达 | PASS | `/governance/api-contracts/1` 可直接展示详情，能力状态为 `sandbox` |
| 试点准入真实 API | PASS | `/pilot/readiness` 返回并展示受控环境，状态为 `sandbox`/blocked |
| 无效详情 404 展示 | FAIL | `/governance/api-contracts/999999` 未显示 404 或资源不存在 |
| 受限角色、完整错误矩阵和响应式 E2E | 未执行 | 当前浏览器冒烟仅使用 superuser；现有前端测试不能替代该矩阵 |

受控 E2E 使用临时本地数据库和本地端口，不连接真实双主机、真实平台或生产数据。验证结束后已关闭临时浏览器会话和服务。

## 9. 安全扫描

- 未发现真实 `.env`、私钥、证书、Token、Cookie、Session、API Key/API Secret。
- 未发现真实平台、真实 AI provider、真实银行/支付连接或真实业务/财务数据。
- 未发现 UI-P7 调用 `/api/rpa/*`、`/api/finance/*`、`/admin/` 或执行 Docker/Shell/SQL/SSH 的入口。
- 未发现自动采购、改价、清仓、停售、归档、付款、转账或提现。
- `frontend/dist`、`node_modules` 和 RPA 运行目录产物未被 Git 跟踪。
- 当前所有能力继续保持 `mock`、`sandbox` 或受控记录语义；禁止标记未验证接口为 `connected`。

## 10. P0问题

无。

## 11. P1问题

| 编号 | 问题 | 证据 | 关闭标准 |
|---|---|---|---|
| UI-P7-R2-P1-001 | 容量状态与阈值合同仍有损映射 | `backend/apps/pilot/models.py`、`serializers.py`、`views.py` 与冻结 `CapacityObservation` 合同 | 模型或适配层可无歧义表达 normal/warning/critical/unknown/stale；warning/critical 筛选不同；阈值语义完整；补契约与前端字段测试 |
| UI-P7-R2-P1-002 | 回滚批准唯一性、受保护对象批量创建及计划创建失败审计仍可绕过 | `ReleasePlan` 仅有 tenant+idempotency 唯一约束；服务先查后写；计划 collection 仅成功审计 | 数据库保证回滚批准引用跨计划唯一；阻止 bulk_create 带入受保护状态/批准字段；所有关键创建失败写不可变审计；补并发与绕过回归测试 |
| UI-P7-R2-P1-003 | 前端状态矩阵缺少组件/E2E证据，详情 404 不可见 | `frontend/tests/ui-p7-governance-pilot.spec.js` 主要读取源码；`GovernanceCatalog.vue` 详情失败不切换状态；受控浏览器实测无效详情无错误提示 | 增加组件挂载测试和受限角色 E2E，覆盖 loading/empty/401/403/404/409/422/stale/offline/分页/权限；详情失败必须呈现统一错误状态 |

## 12. P2问题

1. `npm ci` 的 `esbuild`、`vue-demi` allow-scripts 提示继续作为供应链观察项。
2. Vite/Rollup 对第三方 `@vueuse/core` PURE 注释位置给出非阻断警告。

## 13. 是否允许 UI-P7 正式收尾

**不允许。**

当前无 P0，但仍有 3 项 P1。应定向关闭容量合同、审计并发/绕过边界、前端组件与受限角色 E2E 三类问题后执行独立 `UI-P7-ARCH-R3`。本结论不允许真实平台接入、生产发布、真实恢复/回滚、真实 RPA 或任何资金动作。
