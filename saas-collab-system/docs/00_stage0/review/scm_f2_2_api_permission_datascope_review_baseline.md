# SC-F2-2 API、权限与 DataScope 审核基线

## 1. 审核对象

主契约：

`docs/03_api/supply_chain_f2_packing_api_contract.md`

审核基线：

| 项目 | 值 |
| --- | --- |
| 工作包 | `SC-F2-2` |
| 父基线 | `71341fb5e85307bdb0ed505ef65c1df2d7a901b9` |
| 分支 | `codex/scm-f2-packing-local` |
| 状态 | `FROZEN_FOR_LOCAL_REVIEW` |
| 实现授权 | 无 |
| 生产授权 | 无 |

## 2. 冻结决策

| 编号 | 决策 | 冻结结论 |
| --- | --- | --- |
| F2-2-D01 | 身份底座 | 复用现有 internal/external 用户、JWT 和 miniapp channel，不建第二套身份 |
| F2-2-D02 | 内部授权 | 每个端点使用 exact `supply.packing.*` permission 和该 permission 的 scope |
| F2-2-D03 | CUSTOM 组合 | 同一 scope 的多个配置维度使用交集；多个有效 scope 使用并集 |
| F2-2-D04 | OWN 创建 | OWN 只覆盖当前用户创建的既有批次，不能单独授权创建 |
| F2-2-D05 | 创建范围 | CUSTOM 创建必须同时覆盖目标供应商和全部采购单 |
| F2-2-D06 | 供应商通道 | 只信任有效 ExternalUserProfile 绑定；写动作另受能力开关控制 |
| F2-2-D07 | 幂等响应 | 首次与重放使用相同状态和冻结业务响应；重放标识仅放响应头 |
| F2-2-D08 | 标签端点 | 将 F2-0 的 GET 草案细化为幂等 POST action，避免带审计写入的 GET |
| F2-2-D09 | 能力配置 API | 本阶段不开放，待乐观锁和持久化幂等合同独立冻结 |
| F2-2-D10 | 错误 | 统一冻结 400/401/403/404/409/422 及精确错误码 |
| F2-2-D11 | 数据库 | MySQL 8 为目标可信存储，不复制 Supabase RLS/RPC |
| F2-2-D12 | 生产保护 | 无线上连接、真实数据、客户端发布、双写、同步或部署授权 |

F2-2-D08 只替换 SC-F2-0 中标签 API 的方法草案，不改变标签属于 F2、PDF 即时生成、不连接打印机的业务决策。

## 3. 审核检查表

### 3.1 范围与通道

- [ ] 三类 API 前缀唯一且互不重叠。
- [ ] miniapp Token 不能访问 Web API，Web Token 不能访问 miniapp API。
- [ ] internal、external、RPA 用户类型矩阵完整。
- [ ] 供应商和小程序不接受客户端 `supplier_id`。
- [ ] 供应商能力配置 API 明确排除。
- [ ] F3、照片、视频、对象存储和物流动作明确排除。

### 3.2 Permission

- [ ] 每个内部端点只引用 5 个已冻结权限之一。
- [ ] GET、创建、箱管理、完成、变更审核的权限边界不混用。
- [ ] 审核队列和审核详情使用 change.review 自身 scope，不依赖 view 权限借权。
- [ ] 权限缺失与 scope 缺失使用不同错误码。
- [ ] superuser 仍受 Tenant 和通道限制。
- [ ] 供应商通道不继承内部 permission。

### 3.3 DataScope

- [ ] 只读取授予当前 exact permission 的活动角色 scope。
- [ ] ALL、OWN、CUSTOM 语义唯一。
- [ ] DEPARTMENT 明确拒绝。
- [ ] CUSTOM 未知键、空值、重复、非法类型和超限安全失败。
- [ ] 同一 CUSTOM 多维交集、多个 scope 并集规则明确。
- [ ] OWN 不授权创建。
- [ ] CUSTOM 创建同时要求 supplier 和所有 order ID 命中。
- [ ] 列表过滤、详情 404 和创建 403 语义明确。
- [ ] 批准/驳回使用 review permission 的批次 scope。

### 3.4 DTO 与字段最小化

- [ ] 所有写请求字段、类型、长度、数量和 nullable 已定义。
- [ ] 未知字段和禁止字段拒绝，不静默丢弃。
- [ ] 内部 DTO 与供应商安全 DTO 差异明确。
- [ ] 不返回 tenant、幂等键、请求哈希、来源哈希、响应快照或内部日志。
- [ ] Decimal 使用字符串，时间使用 UTC ISO-8601。
- [ ] 分页、过滤、排序和越界页规则明确。
- [ ] PDF 成功响应是统一 JSON 信封的唯一例外。

### 3.5 幂等与并发

- [ ] 所有 POST/PUT/DELETE/PDF action 要求 Idempotency-Key。
- [ ] actor、channel、action、资源和规范化负载进入幂等身份。
- [ ] 首次与重放状态码和业务响应一致。
- [ ] 重放前重新执行当前授权和供应商能力校验。
- [ ] 删除或版本变化后仍返回首次冻结响应。
- [ ] MySQL 1205/1213 使用相同 key 重试。
- [ ] 同 key 不同身份、通道、动作、资源或负载返回 409。
- [ ] 标签快照可重建原版本 PDF，不读取后续活动布局。

### 3.6 错误与防枚举

- [ ] 400、401、403、404、409、422 场景无重叠歧义。
- [ ] permission 检查先于对象查询。
- [ ] 跨 Tenant、scope、供应商的详情和动作统一 404。
- [ ] 创建引用超 scope 使用 403，不泄露其他租户详情。
- [ ] 错误消息不含 SQL、堆栈、密钥或对象存在性。

### 3.7 审计与边界

- [ ] 成功写动作的事件、日志和业务变更处于同一事务。
- [ ] 重放不产生重复事件或日志。
- [ ] 标签事件不保存 PDF 二进制或敏感二维码。
- [ ] 变更申请人不能审核本人申请。
- [ ] F2 不修改 SC-F1 `production_completed`。
- [ ] F2 不产生 F3 状态或物流记录。
- [ ] 没有生产连接、真实数据、真实通知或客户端发布授权。

## 4. 后续实现验收矩阵

| 类别 | 最低自动化要求 |
| --- | --- |
| 内部权限 | 5 个 permission 的允许/拒绝、无 scope、非法 scope |
| DataScope | ALL、OWN、CUSTOM 单维/多维、多个角色、跨租户、跨供应商 |
| 供应商 Web | 有效/无效绑定、能力开关、历史只读、跨供应商 404 |
| 小程序 | miniapp Token 正向、Web Token/RPA/internal 负向、跨通道刷新 Token |
| DTO | 未知字段、禁止字段、长度、Decimal、数量、分页、敏感字段缺失 |
| 幂等 | 首次/重放一致、键冲突、删除后重放、变更后重放、授权撤销 |
| MySQL | 并发创建、并发箱动作、完成竞争、审批竞争、死锁/锁超时 |
| PDF | 批次/箱标签、冻结版本、ETag、文件名、二维码、重放一致 |
| 边界 | SC-F1 状态保持、F3 路由不可达、无真实外部调用 |

## 5. 本轮审核出口

本轮只能产生以下结论之一：

- `PASS_FOR_SC_F2_2_LOCAL_API_IMPLEMENTATION`
- `REQUIRES_SC_F2_2_CONTRACT_REMEDIATION`

在独立审核给出第一项结论前，不允许创建 F2 view、serializer、URL、前端 API 方法或小程序页面。
