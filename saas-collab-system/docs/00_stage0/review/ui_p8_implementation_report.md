# UI-P8 生产试点运维与专项安全准入实施报告

## 1. 实施对象

- 分支：`feature/ui-p8-production-pilot-security-readiness`
- 基线：UI-P7 合并后的 `main`，提交 `30ba8d8554461d5d0d5b831406f1d12f399d4e8d`
- 范围：生产试点控制台、安全评审、受控验证、性能验证、准入决策、权限、data_scope、状态机、审计、Mock 和测试。

## 2. 后端实施

- 在 `pilot` app 中新增安全评审、受控验证、性能验证和准入决策模型及迁移。
- 新增控制台和四类资源的列表、创建、详情、PATCH、提交、审批、拒绝、结果记录和取消端点。
- 新增 17 个 UI-P8 exact permission 及权限迁移。
- 新增 permission-specific data_scope 校验，覆盖未知 key、非法模式、空值、重复值、未登记环境、跨 tenant 资源和越 scope action。
- PATCH 环境变更同时检查原环境、目标环境和资源 ID scope；`owner_id` 由服务端固定且不可通过通用 PATCH 转移。
- 财务边界安全评审同时要求对应 pilot 权限和 `finance.view`，只保存平台及币种编码，不返回财务明细。
- 安全评审 PATCH 会重新校验财务 scope、目标环境、受控 target alias 和 evidence reference；受控引用必须预先登记在当前 tenant 与环境下。
- 状态迁移、职责分离、版本冲突和幂等冲突均由服务层控制；终态、批量更新和删除受到保护。
- 模型实例首次创建也只能通过状态机服务执行，直接 `save()`、`objects.create()`、批量写入均不能绕过状态机。
- 准入提交由后端生成证据快照和哈希；批准时重新读取并核对证据版本、状态、摘要和有效期，控制台与准入结论只反映证据状态，不执行部署或生产动作。
- 已认证请求的 403、422、409 失败尝试会写入脱敏且不可变的失败审计，错误码统一映射到接口合同。
- 过期状态由服务端惰性处理并写入系统审计事件。

## 3. 前端实施

- 新增生产试点控制台、安全评审、受控验证、性能验证和准入决策五个工作台。
- 新增对应菜单、列表和详情路由，并按 exact view permission 控制访问。
- action 按钮按 plan、review、record、cancel 等精确权限显示。
- 页面提供 loading、empty、error 和无效详情 404 状态；详情支持直接 URL 加载。
- 列表支持服务端分页及环境/状态筛选，草稿通过真实 PATCH 合同编辑；组件测试覆盖 loading、empty、401、403、404、409、422 和 offline。
- API 统一使用 `/api/internal/pilot/*`，不调用 RPA Agent、财务、管理后台或部署执行接口。
- UI-P8 真实 API 在浏览器联调前保持 `pending`；Mock 保持 `mock`，不会因 HTTP 200 自动标记为 `connected`。

## 4. Mock 与受控边界

- Mock 仅使用 demo、synthetic、masked 和 placeholder 数据。
- Mock 支持列表、详情、创建和状态动作，用于页面状态及权限验证，不连接真实平台。
- 未提供真实 URL、凭据、命令输入、Web Shell、部署、恢复、回滚、流量切换或资金操作入口。
- 未启用自动采购、供应商通知、改库存、刊登、改价、清仓、停售、归档或真实 RPA。

## 5. 测试与检查结果

2026-07-20 在本地最终代码上实际执行：

| 检查 | 结果 |
|---|---|
| Django system check | 通过，`0 silenced` |
| migration 一致性 | 通过，`No changes detected` |
| 临时测试数据库迁移 | 通过，由 pytest 创建测试数据库并应用迁移 |
| UI-P8 后端专项测试 | 通过，`19 passed` |
| 后端全量 pytest | 通过，`397 passed` |
| `npm ci` | 通过，安装 249 个包，`0 vulnerabilities` |
| UI-P8 前端专项测试 | 通过，`23 passed`，包含真实组件挂载状态矩阵、逐 action 权限、成功 action 重载、筛选、分页和 PATCH |
| 前端全量测试 | 通过，`11` 个文件、`153 passed` |
| 前端生产构建 | 通过，1955 modules transformed |
| Docker Compose 配置 | 通过；未提供本地真实环境变量，因此仅出现空变量提示 |
| RPA JSON 校验 | 通过，两个示例目录共 16 个 JSON |
| 构建与运行产物 | `dist`、`node_modules` 和 RPA 运行缓存保持忽略 |
| 高置信密钥扫描 | 未发现私钥、AWS key、GitHub token 或 `sk-` 密钥签名 |
| 真实平台和命令调用扫描 | UI-P8 实现中未发现外部 HTTP、RPA Agent、finance、admin、Shell、Docker 或 SSH 调用 |
| 受限角色 JWT 浏览器 E2E | 通过；`VITE_USE_MOCK=false` 下完成真实 login/me、受保护页面 GET、POST 创建和 PATCH 更新，版本由 1 更新为 2，浏览器无 error/warn |
| 远端 CI | 待当前分支提交并创建 PR 后验证，不以本地结果替代 |

## 6. 非阻断观察项

- `npm ci` 提示 `esbuild` 和 `vue-demi` 的 install script 尚未加入 allow-scripts 清单。
- Vite 构建出现第三方 VueUse PURE 注释位置警告，未阻断构建。
- 远端 CI 尚未执行，必须在当前分支提交并创建 PR 后记录实际结果；本地结果不得替代远端门禁。

## 7. 安全确认

- 未提交真实 `.env`、账号、密码、Token、Cookie、Session、API Key、API Secret、私钥或数据库密码。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行、支付、AI provider 或对象存储。
- 未提交真实订单、供应商、财务、银行或生产环境数据。
- 未修改 `rpa-agent/` 真实执行代码和 `docs/04_rpa/` 协议。
- UI-P8 的 `go` 仅为人工准入评审结论，不代表部署、连接或生产发布。

## 8. 实施结论

UI-P8 实现、Mock、页面和自动化测试已完成，允许进入独立 `UI-P8-ARCH-R1` 实现复审。该结论不是复审 PASS，不允许据此直接正式收尾、接入真实平台、生产发布或启用高风险自动化。
