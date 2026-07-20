# UI-P8 生产试点运维与专项安全准入验收清单

## 1. 合同与范围

- [ ] 分支基于 UI-P7 merge commit `30ba8d8554461d5d0d5b831406f1d12f399d4e8d`。
- [ ] 页面、API、permission、data_scope、状态机、错误、审计和 capability 状态与冻结合同一致。
- [ ] 新端点在实际联调前保持 `pending`，Mock 保持 `mock`，未误标 `connected`。
- [ ] 复用 UI-P7 拓扑、容量、恢复和发布页面，无同义资源。

## 2. tenant、权限与 data_scope

- [ ] internal、external、RPA、finance 用户边界分别验证。
- [ ] 所有资源按 tenant 过滤，跨 tenant 列表不可见、详情 404、请求体引用 403。
- [ ] view、plan、review、record 使用各自 permission-specific scope。
- [ ] 缺失 scope、未知 key、非法枚举、空/重复/未登记/超限值返回 `403 DATA_SCOPE_INVALID`。
- [ ] `all` 只覆盖当前 tenant 已登记受控资源。
- [ ] 创建人不能审批自己的评审、验证、性能计划或准入决策。
- [ ] 创建使用 exact plan permission 的 `pilot_environments` scope，不以尚未产生的资源 ID 授权。
- [ ] 存量资源的详情和 action 使用 exact permission 的资源 ID scope，不继承 view scope。
- [ ] PATCH 修改 environment 时同时校验原环境、目标环境和资源 ID scope；目标越 scope 返回 403 且不写入。
- [ ] owner_id 由服务端固定为创建 actor，POST/PATCH 提交 owner_id 返回 422，不存在 owner 转移入口。
- [ ] 准入决策引用安全评审、验证、性能、恢复和发布证据时，逐类校验 view permission、scope、tenant 和 environment。
- [x] `finance_boundary` 的创建、修改、提交、批准和拒绝同时要求 `finance.view`，其脱敏 `finance_scope.platforms/currencies` 逐值命中财务 scope；非财务评审拒绝 finance_scope。

## 3. 状态机与防绕过

- [ ] 安全评审只允许 `draft -> submitted -> approved/rejected` 以及 `draft/submitted/approved -> expired`。
- [ ] 验证与性能记录只允许冻结迁移，`record-result` 仅作用于已批准计划。
- [ ] 准入决策只允许 `draft -> submitted -> approved/rejected` 以及 `draft/submitted/approved -> expired`。
- [x] 终态实例、直接实例创建、`objects.create()`、QuerySet update/delete、bulk_update/bulk_create 和通用 PATCH 均不能绕过状态机。
- [ ] 版本冲突、重复审批、过期证据、过期批准和职责分离冲突返回 409。
- [ ] 创建及 action 幂等键重复/冲突测试通过。
- [ ] `draft/submitted/approved` 的安全评审和准入决策按 `expires_at` 进入 expired，定时与惰性过期结果一致且可审计。
- [ ] 读请求触发 draft 过期后返回 200 expired/stale；PATCH/submit 等写动作先写 system 过期审计再返回 409，后续详情显示 expired。
- [ ] cancel 只使用专用 `pilot.verification.cancel` / `pilot.performance.cancel`，不能由 plan/review/record 替代；submitted/approved 拒绝创建人单方取消。
- [ ] 过期、取消和人工 action 并发时仅一个事务成功，另一请求返回 409。

## 4. 证据与审计

- [ ] 提交准入决策时生成不可变证据快照、哈希和合同版本。
- [x] 成功、失败、权限拒绝、data_scope 拒绝、422、409 均有不可变审计，且失败审计错误码与 API 响应一致。
- [ ] 结果证据禁止修改、删除和 tenant 级联删除。
- [ ] 证据引用不含认证信息、明文凭据、真实业务数据或完整内部地址。
- [x] 准入批准重新读取并核对证据版本、状态、摘要和有效期；到期和 stale 证据不能产生 `ready` 或有效 `go`。

## 5. 前端页面与组件

- [ ] 五个 UI-P8 页面均有路由、菜单、面包屑、精确 permission 和 capability 合同。
- [x] loading、empty、401、403、404、409、422、offline、筛选、分页和 PATCH 有挂载组件测试；stale 由后端证据复验专项测试覆盖。
- [ ] 无效详情 URL 显示可见 404。
- [ ] 操作按钮按 action permission 隐藏，后端拒绝能正确显示。
- [ ] 准入 `go` 显示为评审结论，不显示为已部署或已连接。
- [ ] 无 Web shell、命令输入、真实 URL、明文凭据、真实连接或生产发布按钮。
- [ ] 桌面和窄屏无重叠、横向破坏或不可见操作。

## 6. API 与错误合同

- [ ] 成功、分页和空数据结构符合统一合同。
- [x] page 无错误固定上限，page_size 限制为 1 至 100。
- [ ] 400/401/403/404/409/422 实际响应和页面展示一致。
- [ ] 非统一 HTTP 200 不被前端包装为成功。
- [x] 详情、分页、环境/状态筛选、日期和枚举校验逐端点验证；未声明通用排序能力。
- [ ] 每个 POST、PATCH、submit、approve、reject、record-result 和 cancel 按合同验证必填、可选、禁止字段及成功详情响应。
- [ ] 未知字段和禁止字段返回 422；action 的 reason、version、幂等键及职责分离规则均可独立构造测试。
- [ ] success_criteria 数量、结果摘要长度、错误字段格式、性能指标范围和 p50/p95 关系均按合同返回唯一 422。
- [ ] entry decision expires_at 只允许未来 30 天，安全评审只允许未来 180 天；创建和 PATCH 使用同一校验。

## 7. 安全边界

- [ ] 无真实 BigSeller、Shopee、TikTok/TK、AI、银行或支付连接。
- [ ] 无真实 `.env`、密码、Token、Cookie、Session、API Key/API Secret、私钥或备份密钥。
- [ ] API 不执行 Shell、Docker、SSH、SQL、Redis、部署、恢复、回滚、流量或网络命令。
- [ ] 预警、容量、分析、智能体和准入结论不触发真实 RPA。
- [ ] 无自动采购、供应商通知、改库存、刊登、改价、清仓、停售、归档或资金动作。

## 8. 实际命令与证据

- [x] Django check。
- [x] migration 一致性与临时数据库迁移。
- [x] UI-P8 后端专项 pytest 和全量 pytest。
- [x] `npm ci`、UI-P8 组件测试、前端全量测试和 build。
- [x] 受限角色 JWT 浏览器 E2E。
- [x] Docker Compose 配置、RPA JSON、API 路径和真实密钥扫描。
- [ ] 远端 CI 全部成功，审核 HEAD 未变化。

## 9. 放行规则

- 存在 P0：FAIL。
- 无 P0 但存在 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS，可完成 UI-P8 收尾。
- UI-P8 PASS 不自动允许真实平台接入、生产发布或高风险自动化。
