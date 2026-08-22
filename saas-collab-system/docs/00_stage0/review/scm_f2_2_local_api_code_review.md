# SC-F2-2 本地 API、权限、DataScope 与原子幂等代码审核

## 1. 审核结论

结论：`REQUIRES_SC_F2_2_LOCAL_API_REMEDIATION`

实现提交 `c15f411f5d926fdcce1c6a808d185cc46d34cfc6` 已建立三通道 API、exact permission、permission-specific DataScope、供应商绑定、确定性标签和 API 幂等记录的主体结构，但仍有 5 项 P1 和 2 项 P2。P1 关闭前不得进入网页端或小程序端融合实现，不得连接、同步、双写、切流或部署到供应链正式线上系统。

本轮仅审核并归档，不修改业务实现。

## 2. 审核基线与隔离边界

| 项目 | 值 |
| --- | --- |
| 审核日期 | 2026-07-29 |
| 分支 | `codex/scm-f2-packing-local` |
| 契约整改复核提交 | `79aceab` |
| 被审核实现提交 | `c15f411f5d926fdcce1c6a808d185cc46d34cfc6` |
| 冻结 API 契约 | `docs/03_api/supply_chain_f2_packing_api_contract.md` |
| 执行环境 | 架构员主机本地隔离环境 |
| 生产连接、真实数据或发布 | 无 |
| 网页端、小程序端实现 | 本轮未修改 |

工作区存在本阶段以外的既有文档修改和未跟踪文件，均未纳入审核提交，也未被修改。

## 3. P1 审核发现

### SC-F2-2-R2-P1-001：API 幂等层的 MySQL 1205/1213 未统一映射

证据：

- `backend/apps/packing/api_idempotency.py:4,107-137,162-190` 只捕获 `IntegrityError` 和 Django `ValidationError`。
- `backend/apps/packing/services.py:40,58-70` 只在领域服务装饰器内把 MySQL 1205/1213 转换为 `StateConflict`。
- API 幂等记录的查询、`select_for_update()`、插入和冲突后重读位于该领域装饰器之外。
- 独立故障注入令 `_find_record()` 抛出 `OperationalError(1205, ...)`，实际结果仍为未转换的 `OperationalError`，不是 `409 STATE_CONFLICT`。

影响：

幂等表自身发生锁等待超时或死锁时可能返回 500，违反契约第 10.4 节和第 11 节；客户端也无法按合同使用同一 key 安全重试。

关闭条件：

1. 在 API 最外层统一识别 MySQL 1205/1213，并转换为 `409 STATE_CONFLICT`。
2. 不得吞掉其他数据库错误。
3. 增加幂等记录查询、首次插入、冲突后重读和标签路径的 1205/1213 定向测试。

### SC-F2-2-R2-P1-002：同 key 跨资源并发首次请求可双提交

证据：

- `backend/apps/packing/api_idempotency.py:73-78` 在执行前按 `(tenant, idempotency_key)` 查找已有记录。
- `backend/apps/packing/models.py:487-503` 数据库唯一约束仅为 `(tenant, scope_key, idempotency_key)`。
- 两个并发首次请求若使用相同 key 但不同 `scope_key`，二者都可能在首次查询时看不到记录；由于 scope 不同，数据库唯一约束也不会形成竞争，两个领域动作和两条 API 记录均可提交。
- `backend/tests/test_supply_chain_f2_packing_mysql_concurrency.py:133-162` 只覆盖同 tenant、同 scope、同 key 的并发创建，没有覆盖同 key 跨批次、跨箱或跨动作的并发首次使用。

影响：

违反契约第 10.4 节“同 key 的资源或动作不同返回 `409 IDEMPOTENCY_CONFLICT`”；当前语义只对串行请求成立，并发窗口可产生双业务结果。

关闭条件：

1. 增加能够原子声明 tenant + key 身份的竞争控制，同时保留冻结的 `(tenant, scope_key, key)` 唯一约束。
2. 同 key 跨 scope、资源、动作、actor 和 channel 的并发首次请求只能有一个成功身份，其余返回 `IDEMPOTENCY_CONFLICT`。
3. 在真实 MySQL 8 中增加跨批次、跨箱和 JSON/PDF 交叉并发测试。

### SC-F2-2-R2-P1-003：供应商存量多订单批次写入错误依赖混单能力

证据：

- 契约第 6 节只要求“创建多订单批次”具备 `can_mix_order_packing=true`；新增箱、替换箱、移除箱、完成和提交变更只要求 `can_self_pack=true`。
- `backend/apps/packing/views.py:206-211` 的 `_require_supplier_write()` 对存量批次按订单数再次要求混单能力。
- 该 helper 被 `views.py:319-397,537-584` 的箱动作、完成和变更提交共同调用。

影响：

供应商已合法创建多订单批次后，如果 `can_mix_order_packing` 被关闭但 `can_self_pack` 仍开启，合同允许继续处理存量批次，当前实现却统一返回 403，导致批次无法完成或提交更正。

关闭条件：

1. `can_mix_order_packing` 只在多订单批次创建时校验。
2. 存量写动作只重新校验有效绑定、活动供应商和 `can_self_pack`。
3. 增加“关闭 mix、保留 self-pack”的 Web 和 miniapp 存量多订单批次写入回归测试。

### SC-F2-2-R2-P1-004：请求严格性未完整实现

证据：

- 契约第 3.3 节要求 JSON 写请求只能使用 `application/json`，且请求体和查询参数拒绝未知字段。
- `backend/config/settings/base.py:132-135` 全局仍允许 FormParser 和 MultiPartParser，F2 view 未执行 Content-Type 门禁。
- `backend/apps/packing/views.py:97-100` 定义了查询白名单，但仅在批次列表、变更列表和审核列表调用；详情、当前标准和 action 端点会静默忽略未知查询参数。
- `backend/apps/packing/views.py:140-188` 对供应商/小程序批次列表也允许 `created_at_from/created_at_to`，但契约第 6 节只允许 `search/status/order_id/page/page_size`。
- `backend/apps/packing/serializers.py:37-89` 使用普通 DRF `DecimalField`。独立 serializer 探针证明 JSON number `2.5/0.125` 被接受并转换成 Decimal，而契约要求 weight/volume 为 Decimal 字符串。

影响：

不同客户端传输格式和未登记参数会得到不一致解释；供应商通道暴露了未冻结过滤能力；数值型 Decimal 失去“字符串精度合同”的严格性。

关闭条件：

1. 所有 F2 写动作统一拒绝非 `application/json` 请求。
2. 所有端点显式使用查询参数白名单；无查询参数端点的白名单为空。
3. 供应商 Web/miniapp 批次列表移除日期过滤。
4. weight/volume 只接受 JSON string 或 null，并增加 number、boolean、科学计数法和精度负向测试。

### SC-F2-2-R2-P1-005：规范化负载未固定箱明细顺序

证据：

- `backend/apps/packing/api_idempotency.py:15-23,97-105` 直接对 serializer 输出计算 API request hash。
- `backend/apps/packing/serializers.py:56-60,85-89` 只拒绝重复 `order_line_id`，不对 `items` 排序。
- 领域服务 `backend/apps/packing/services.py:300-314` 会把箱明细规范化，说明明细数组的输入顺序不是领域语义。
- 独立探针中，两份字段和值相同、仅 items 顺序不同的有效负载得到不同 API hash。

影响：

同一业务负载只因明细数组顺序变化就返回 `409 IDEMPOTENCY_CONFLICT`，不符合“规范化负载进入幂等身份”的冻结要求；API 幂等身份与领域请求身份也不一致。

关闭条件：

1. 在计算 API hash 前按 `order_line_id` 固定排序 items。
2. `proposed_boxes` 中每个箱的 items 同样规范化；箱数组自身保持合同定义的布局顺序。
3. 增加 items 重排同 key 重放测试，并验证实际业务结果和冻结响应完全一致。

## 4. P2 审核发现

### SC-F2-2-R2-P2-001：当前标准端点可能与新批次实际标准不一致

`backend/apps/packing/services.py:136-142` 创建批次固定选择 `DEFAULT_STANDARD_CODE = "packing-v1"` 的最新活动版本，但 `backend/apps/packing/views.py:694-704` 按所有活动标准的 code 排序后取第一条。存在多个活动 code 时，`GET standards/current/` 可能返回与新批次实际冻结标准不同的记录。

关闭条件：当前标准查询与批次创建复用同一选择函数，并增加多活动 code 测试。

### SC-F2-2-R2-P2-002：标签字体包不能证明中文业务文本可渲染

`backend/apps/packing/labels.py:23,206-226` 只使用 Helvetica/Helvetica-Bold，标签内容包含供应商、SKU 和商品名称等业务文本。当前测试只验证字节确定性，没有验证中文、特殊字符和缺字行为。

关闭条件：冻结并嵌入支持目标字符集的字体资产，计算真实字体文件摘要，并增加中文商品名/供应商名的渲染与文本可见性测试。

## 5. 已通过项目

- 三类 URL 前缀和 miniapp/Web 通道方向已分离。
- 内部列表、详情和动作从授权 QuerySet 读取，跨 tenant/scope/供应商目标统一隐藏为 404 的主体路径成立。
- permission-specific DataScope 支持 ALL、OWN、CUSTOM 多维交集和多 scope 并集；历史订单关联未使用 `active_guard` 过滤。
- 创建批次按独立 `supply.packing.create` scope 校验 supplier 和全部 order。
- API 外层事务覆盖领域写入、事件、日志、响应序列化和幂等记录保存；故障注入回滚测试存在。
- remove 使用 POST action，旧 DELETE 路由不可用。
- 标签快照、PDF ETag 和重放的确定性主体实现已建立。
- F2 未修改 SC-F1 `production_completed`，未创建 F3 或物流动作。

上述通过项不能抵消第 3 节 P1。

## 6. 验证记录

| 验证 | 结果 |
| --- | --- |
| SC-F2-2 API 定向 SQLite 测试 | `11 passed` |
| serializer 严格性探针 | number Decimal 被接受；items 重排 hash 不一致 |
| API 幂等 1205 故障注入 | 未转换的 `OperationalError(1205)` |
| 实现提交记录的 SQLite 全回归 | `453 passed, 10 skipped`，作为被审核提交证据引用 |
| 实现提交记录的临时 MySQL 8 套件 | `18 passed`，但未覆盖本报告第 P1-001、P1-002 的竞争路径 |
| 生产系统连接或数据 | 未使用 |

定向测试首次运行受本机 `.env` 中已停止的临时 MySQL 主机名影响而无法建库；显式切换到隔离 SQLite 审核库后通过。该环境失败未计为业务缺陷。

## 7. 风险统计与下一步门禁

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 0 | 未发现生产连接、真实数据或发布越界 |
| P1 | 5 | 必须整改并独立复核 |
| P2 | 2 | 应在 SC-F2-2 关闭前一并处理或形成书面延期 |

下一步只允许执行：

`修复 SC-F2-2-R2-P1-001 至 SC-F2-2-R2-P1-005，并补充 P2 处理决定`

整改后必须执行：

`SC-F2-2 本地 API、权限、DataScope 与原子幂等 P1 整改复核`

复核至少要包含真实 MySQL 8 的同 scope 同 key、跨 scope 同 key、API 幂等表 1205/1213、供应商混单能力撤销、严格 Content-Type/查询/Decimal 以及 items 规范化重放测试。复核通过前，继续禁止网页端和小程序端业务融合、线上连接、数据同步、双写、切流和生产部署。
