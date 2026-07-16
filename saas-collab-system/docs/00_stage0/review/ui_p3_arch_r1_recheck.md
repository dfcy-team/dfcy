# UI-P3-ARCH-R1 RPA任务与设备基础复审报告

## 1. 复审对象

- 项目：`saas-collab-system/`
- 分支：`feature/ui-p3-rpa-task-device-foundation`
- 当前HEAD：`ffdffed`
- 复审日期：2026-07-16
- 复审方式：基于当前工作树的独立静态审核、自动化测试、构建、系统扫描和本地Mock页面实测
- 复审依据：UI-P3合同、前端接口映射、变更日志和测试报告，以及本分支相对`main`的实际差异

当前UI-P3实现尚未形成独立提交，因此本报告记录的是`ffdffed`之上的当前工作树快照；创建PR前仍需以整改后的提交HEAD执行R2复审。

## 2. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：2项。
- P2：4项。

任务、运行、设备、人工队列、稳定性、账号锁和页面签名的页面与internal管理API已建立；tenant基础过滤、权限分区、动作权限、统一响应、设备脱敏和Mock/dry-run边界总体成立。当前仍存在组合自定义data_scope可能放宽运行记录范围，以及稳定性Mock未遵守双状态机合同的问题，暂不建议UI-P3正式收尾。

## 3. 页面与路由合同

结论：**通过**。

- `/rpa/tasks`、`/rpa/runs`、`/rpa/devices`、`/rpa/manual-queue`、`/rpa/stability`、`/rpa/account-locks`、`/rpa/page-signatures`均已登记路由和能力合同。
- 列表对应的任务、运行和设备详情路径已登记；`/rpa/attempts*`仅重定向到canonical run路径。
- `canAccessPath()`对未登记非公开路径默认返回拒绝。
- external和RPA用户不能通过UI-P3路由能力进入internal管理页面。
- 本地Vite Mock实测7个页面均成功渲染，无请求错误和页面级横向溢出。

## 4. API分区

结论：**通过**。

- internal管理端使用`/api/internal/rpa/*`。
- 前端源码扫描未发现claim、heartbeat、logs、screenshots、complete或fail等Agent执行请求。
- 管理前端未模拟Agent Token，未访问`/api/finance/*`或`/admin/`。
- 后端internal端点使用`DeclaredApplicationPermission`；Agent端继续使用`IsRPAAgent`。
- internal管理动作只执行人工分配、Mock重试和本地dry-run检查，不完成Agent任务。

## 5. tenant与data_scope

结论：**存在P1**。

已通过项：

- 所有internal查询先按`request.user.tenant`过滤。
- 权限校验要求当前permission存在有效data_scope。
- 任务、设备、账号锁和页面签名分别读取当前端点声明的permission scope。
- `rpa_task_ids`、`rpa_device_ids`和`rpa_platforms`已建立专用过滤字段。

问题：`backend/apps/rpa/internal_scope.py`中的`filter_rpa_runs()`先跨scope合并任务ID和设备ID，再以`task_id in ... OR agent_id in ...`过滤运行记录。当同一custom scope同时声明任务和设备限制时，任一维度命中即可返回记录，会出现以下放宽：

- 任务不在授权任务集，但Agent在授权设备集的运行记录可见。
- Agent不在授权设备集，但任务在授权任务集的运行记录可见。

这不构成跨tenant泄漏，但违反合同中两类自定义维度均“限制运行”的要求，属于tenant内data_scope越权风险。

整改验收标准：

1. 单个custom scope内，已配置的任务维度和设备维度必须同时满足。
2. 多个授权角色/scope之间可以按既定权限模型取并集，但不能先跨scope展平后扩大组合。
3. 增加任务允许/设备拒绝、任务拒绝/设备允许、两者均允许、多个角色并集四类测试。

## 6. 权限与动作

结论：**通过**。

- 查看权限与动作权限已拆分为`rpa.tasks.view/manage`和`rpa.devices.view/dry_run`。
- 任务列表和人工队列无manage权限时不显示写动作；详情页动作会禁用。
- 后端以写权限再次校验人工分配、Mock重试和设备dry-run，不能依赖前端展示权限绕过。
- artificial assignment和Mock retry写入操作审计。
- external/RPA用户访问internal管理接口返回403。

## 7. 任务/运行双状态机

结论：**真实API模型通过，Mock合同存在P1**。

已通过项：

- `RPATask`和`RPATaskAttempt`使用独立状态字段。
- 每次claim创建独立attempt，已有阶段2测试覆盖连续attempt编号。
- internal管理端不能把任务直接改成success。
- 人工分配仅允许`manual_required`。
- Mock重试仅允许`failed/manual_required`；非法状态返回409，超过重试上限返回422。
- 运行页面没有任务重试动作。

问题：`frontend/src/mock/rpaStability.js`的稳定性Mock使用`retry_wait`，该值不属于冻结的任务状态；同时Mock仅返回`items`，没有`run_states`，导致稳定性页面的运行状态机在Mock/dry-run验收中为空。当前前端专项测试没有校验状态值集合和任务/运行两组数据的完整性。

整改验收标准：

1. 将`retry_wait`统一为合同状态`retrying`。
2. Mock稳定性响应与后端一致，显式提供`task_states`、`run_states`和`manual_required`。
3. 增加测试，拒绝任何合同外任务或运行状态，并验证两组状态不会混用。

## 8. 设备与dry-run

结论：**通过**。

- 设备模式限制为`mock/dry_run/production_disabled`。
- dry-run仅返回绑定、执行模式、`platform_connection=not_attempted`和`browser_automation=not_attempted`。
- dry-run写入审计，不启动浏览器、不访问平台。
- `production_disabled`拒绝dry-run和Agent claim。
- 设备响应不包含`token_hash`、`ip_whitelist`或完整`device_fingerprint`。
- 未新增真实浏览器自动化脚本或真实选择器。

## 9. 前端完整状态

结论：**通过，保留观察项**。

- 任务、运行、设备、人工队列、账号锁和页面签名具备loading/error/empty/list状态；任务、运行和设备具备详情页。
- 分页解析使用`data.count/next/previous/results`。
- API成功由request层注入`api_status=connected`；Mock为`mock`，网络失败回退为`fallback/degraded`。
- 401/403/404/409/422有HTTP状态时不回退Mock。
- 动作按钮受action permission和业务状态双重控制。

浏览器实测使用本地Mock模式，未执行真实认证态API联调；该项列为P2观察。

## 10. 测试与构建

| 检查 | 独立执行结果 | 备注 |
|---|---|---|
| Django check | PASS | System check identified no issues |
| migration一致性 | PASS | No changes detected |
| UI-P3专项pytest | PASS | 10 passed in 10.21s |
| 全量pytest | PASS | 281 passed in 26.70s |
| UI-P3专项Vitest | PASS | 1 file，8 tests passed |
| 全量Vitest | PASS | 5 files，77 tests passed |
| `npm run build` | PASS | 1909 modules transformed，4.89s |
| Docker配置 | PASS | 配置可解析；未注入本地DB和Secret变量，存在缺省值警告 |
| RPA JSON | PASS | 16个JSON文件有效 |
| 七个UI-P3页面 | PASS | Mock模式均可达，无请求错误和页面级横向溢出 |

补充的组合scope运行时探针未执行成功，原因是本地开发SQLite尚未迁移、无业务表；该问题由静态查询条件直接确认。未创建临时测试文件，也未修改开发数据库。

## 11. 安全扫描

结论：**通过**。

- 未发现被跟踪的真实`.env`、私钥、证书或SQLite文件。
- 未发现前端Agent执行路径。
- 未发现真实BigSeller、Shopee、TikTok/TK连接。
- 未发现真实账号、Token、Cookie、Session、API Key或API Secret。
- 未发现真实自动改价、刊登、清仓、补货或财务操作。
- `frontend/dist`、`node_modules`及RPA运行产物未被跟踪；cache/downloads中仅有允许的`.gitkeep`。

## 12. P0

无。

## 13. P1

| 编号 | 问题 | 责任范围 | 验收标准 |
|---|---|---|---|
| UI-P3-R1-P1-001 | 运行记录同时配置任务与设备custom scope时使用OR，存在tenant内范围放宽 | 后端`internal_scope`与专项测试 | 单scope内按已配置维度取交集，多scope按权限模型组合；补齐四类组合越权测试 |
| UI-P3-R1-P1-002 | 稳定性Mock含非法`retry_wait`且缺少`run_states`，双状态机Mock合同不完整 | 前端Mock与专项测试 | 使用`retrying`并返回独立`task_states/run_states/manual_required`；测试拒绝合同外状态 |

## 14. P2

1. 当前成果尚未形成可复现提交HEAD，R2应绑定整改后的提交。
2. UI-P3专项后端测试尚未直接覆盖设备custom scope、平台custom scope、无scope拒绝及404结构；部分能力由其他全量测试间接覆盖。
3. 浏览器真实认证态API E2E尚未执行，应使用受控Pilot账号和隔离数据补充，不使用生产凭据。
4. 前端构建存在第三方`@vueuse/core` PURE注释位置提示；不影响本次构建。

## 15. 是否建议UI-P3收尾

**暂不建议。**

UI-P3具备良好的页面、API、权限和Mock/dry-run基础，且未发现P0；但两项P1尚未关闭。建议只定向修改data_scope组合逻辑、稳定性Mock和相应测试，完成后执行`UI-P3-ARCH-R2`独立复审。整改期间继续禁止真实平台接入、真实Agent自动化和高风险业务动作。
