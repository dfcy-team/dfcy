# UI-P3 RPA任务与设备基础测试报告

## 1. 测试范围

- RPA任务、运行记录、设备、人工队列、账号串行锁、页面签名和稳定性看板。
- 任务状态与运行状态双状态机。
- internal管理接口与Agent执行接口分区。
- tenant、permission-specific data_scope和动作权限。
- Mock/dry-run执行边界、敏感字段脱敏和统一响应结构。
- 前端Mock/API切换、分页、错误状态和权限动作收敛。

## 2. 后端测试结果

| 检查 | 结果 | 证据 |
|---|---|---|
| `python manage.py check` | PASS | System check identified no issues |
| `makemigrations --check --dry-run` | PASS | No changes detected |
| UI-P3专项pytest | PASS | 12 passed in 9.90s |
| 全量后端pytest | PASS | 283 passed in 27.19s |

专项测试覆盖：internal用户类型限制、tenant隔离、自定义任务和设备data_scope、任务与运行分页、设备字段脱敏、人工分配权限、Mock重试状态冲突与重试上限、production-disabled设备拒绝dry-run、external/RPA用户越权拒绝以及统一错误结构。

## 3. 前端测试结果

| 检查 | 结果 | 证据 |
|---|---|---|
| UI-P3专项Vitest | PASS | 1 file，9 tests passed |
| 全量前端Vitest | PASS | 5 files，78 tests passed |
| `npm run build` | PASS | 1909 modules transformed |
| 第三方PURE注释提示 | P2观察 | 来自`@vueuse/core`，不阻断构建 |

专项测试覆盖：canonical run路径、legacy attempt重定向、任务/设备/稳定性路由权限、internal管理API路径、禁止管理前端调用Agent执行端点、分页响应解析、动作权限和Mock/dry-run边界。

R1整改回归新增覆盖：单custom scope内任务与设备维度取交集、多角色scope授权取并集、合同外状态拒绝、Mock任务/运行双状态组完整性。

## 4. 系统检查

| 检查 | 结果 | 说明 |
|---|---|---|
| `docker compose config --quiet` | PASS | 配置可解析；本机未注入Pilot环境变量，输出缺省变量提示 |
| RPA JSON校验 | PASS | 16个JSON文件均可解析 |
| `git diff --check` | PASS | 无空白错误，仅有Windows LF/CRLF提示 |
| 运行产物检查 | PASS | 未跟踪`frontend/dist`、`node_modules`、RPA cache/downloads运行文件 |
| 禁止文件扫描 | PASS | 未发现被跟踪的真实`.env`、私钥、证书或SQLite文件 |
| 凭据形态扫描 | PASS | 未发现真实Token、Cookie、Session、API Key或API Secret |
| Agent执行路径扫描 | PASS | 管理前端无claim/heartbeat/logs/screenshots/complete/fail请求 |

## 5. Mock与dry-run验证

- Mock模式保留示例任务、运行、设备、人工队列、账号锁和页面签名数据。
- API模式使用`/api/internal/rpa/*`，仅实际响应成功时标记`connected`。
- 设备dry-run只验证设备绑定和执行模式并写入审计，不启动浏览器、不连接平台。
- `production_disabled`设备不能执行dry-run，也不能被Agent领取任务。
- 401/403/404/409/422不回退Mock，前端展示真实错误。

## 6. 页面实测

| 页面 | 结果 | 核验内容 |
|---|---|---|
| `/rpa/tasks` | PASS | 菜单、筛选、任务分页表格、详情、人工分配和Mock重试动作正常渲染 |
| `/rpa/devices` | PASS | 脱敏指纹、执行模式、在线状态、详情和dry-run动作正常渲染 |
| `/rpa/manual-queue` | PASS | `manual_required`任务、接管原因、分配和Mock重试动作正常渲染 |
| 桌面视口 | PASS | 侧栏、顶栏、筛选区和表格无重叠或横向页面溢出 |

页面实测使用本地Vite Mock模式，不连接真实后端、真实Agent或真实平台。

## 7. 安全边界验证

- 未接入真实BigSeller、Shopee或TikTok/TK。
- 未新增真实浏览器自动化脚本或选择器。
- 未提交真实账号、密码、Token、Cookie、Session或平台密钥。
- 未开放自动改价、刊登、清仓、补货或财务动作。
- internal管理页面不持有或模拟RPA Agent Token。
- external和RPA用户不能访问`/api/internal/rpa/*`。

## 8. 当前结论

UI-P3页面、API、权限、双状态机及Mock/dry-run实现已完成专项和全量自动化验证，具备进入独立架构R1复审的条件。浏览器真实认证态联调仍应在受控Pilot账号和隔离测试数据下执行，不使用生产凭据。
