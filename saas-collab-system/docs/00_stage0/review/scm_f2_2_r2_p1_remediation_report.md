# SC-F2-2 R2 P1 整改报告

## 1. 整改结论

`SC-F2-2-R2-P1-001` 至 `SC-F2-2-R2-P1-005` 已完成本地代码整改和自动化验证，状态为：

`REMEDIATED_PENDING_INDEPENDENT_RECHECK`

本轮同时完成两项 P2 的处理决定：

- `SC-F2-2-R2-P2-001`：本轮修复。
- `SC-F2-2-R2-P2-002`：书面延期至中文标签资产专项，设为客户端融合前强制门禁。

本报告不替代独立整改复核结论。

## 2. 基线与隔离

| 项目 | 值 |
| --- | --- |
| 整改日期 | 2026-07-29 |
| 分支 | `codex/scm-f2-packing-local` |
| 审核提交 | `045a280` |
| 被整改实现提交 | `c15f411` |
| 执行环境 | 架构员主机本地隔离环境 |
| 生产连接、真实数据、同步、双写、切流或部署 | 无 |
| 网页端、小程序端业务实现 | 未进入 |

工作区中其他既有文档修改和未跟踪文件不属于本轮整改，未被修改或纳入提交。

## 3. P1 逐项整改

### SC-F2-2-R2-P1-001：API 幂等层 MySQL 1205/1213

已整改：

1. API 幂等最外层增加统一数据库冲突转换。
2. 幂等记录首次查询、加锁、插入、唯一冲突后重读以及 JSON/标签完整路径均受该转换层覆盖。
3. 只转换 MySQL 1205 和 1213；其他 `OperationalError` 保持原样抛出。
4. API 记录插入失败仍处于领域写入、事件、日志和冻结响应的同一外层事务，失败后全量回滚。

验证：

- 1205/1213 首次读取故障注入均返回 `409 STATE_CONFLICT`。
- 1205/1213 API 记录插入故障注入均返回 `409 STATE_CONFLICT`，业务和事件为零。
- 唯一冲突后重读发生 1213 时返回 `409 STATE_CONFLICT`。
- 非重试数据库错误不被隐藏。

### SC-F2-2-R2-P1-002：同 key 跨资源并发首次请求

已整改：

1. 保留冻结的 `(tenant_id, scope_key, idempotency_key)` 唯一约束。
2. 新增 `(tenant_id, idempotency_key)` 原子身份声明约束和 migration
   `0003_packingapiidempotencyrecord_tenant_key.py`。
3. 同 tenant、同 key 的不同 scope 并发首次请求由数据库唯一键串行化；竞争事务回滚领域动作后读取胜出记录并比较 actor、channel、action、resource 和 payload。
4. 身份不同的竞争请求返回 `409 IDEMPOTENCY_CONFLICT`。

真实 MySQL 8 验证：

- 两个不同批次同时使用相同 key 新增箱，结果固定为一个 201、一个 409。
- 409 错误码为 `IDEMPOTENCY_CONFLICT`。
- 两个批次合计只产生一个箱和一条 API 幂等记录。

### SC-F2-2-R2-P1-003：供应商存量多订单批次能力边界

已整改：

1. `can_mix_order_packing` 只在多订单批次创建时校验。
2. 存量箱动作、完成和变更提交只重新校验有效供应商绑定、活动供应商主档和 `can_self_pack`。
3. 增加供应商 Web 创建多订单批次、关闭 mix 但保留 self-pack 后继续 Web 新增箱和 miniapp 替换箱的回归测试。

### SC-F2-2-R2-P1-004：请求严格性

已整改：

1. 所有 F2 POST、PUT 和 PDF action 统一要求 `Content-Type: application/json`。
2. 详情、当前标准和所有 action 使用空查询白名单；列表使用逐端点白名单。
3. 供应商 Web 和 miniapp 批次列表不再接受内部日期过滤参数。
4. weight/volume 使用纯 Decimal 字符串字段，只允许 ASCII 数字和普通小数点格式；拒绝 JSON number、boolean、符号和科学计数法。
5. 保留原有未知 body 字段、精度、范围和 null 校验。

验证覆盖非 JSON 请求、无参数端点未知 query、供应商日期 query、数值 Decimal 和科学计数法。

### SC-F2-2-R2-P1-005：规范化负载

已整改：

1. 新增/替换箱在 API request hash 前按 `order_line_id` 排序 items。
2. 每个 proposed box 的 items 使用相同规范化；proposed box 数组自身顺序保持不变。
3. items 顺序不同但语义相同的同 key 请求返回首次冻结响应，不产生第二个事件。
4. 变更申请 serializer 的 proposed items 重排得到相同规范 hash。

## 4. P2 处理决定

### SC-F2-2-R2-P2-001：当前标准选择

决定：`FIXED_IN_THIS_REMEDIATION`

当前标准端点和新批次创建现在复用相同的 `packing-v1` 最新活动版本选择函数。增加多个活动标准 code 的测试，确认字典序更靠前的其他标准不会被 `standards/current/` 错误返回。

### SC-F2-2-R2-P2-002：中文标签字体

决定：`DEFERRED_WITH_PRE_CLIENT_GATE`

理由：

- 当前冻结标签版本使用 Helvetica/Helvetica-Bold 摘要，修改字体资产会形成新的布局/渲染兼容版本，不应在 P1 原子幂等整改中临时替换。
- 当前阶段仍禁止网页端、小程序端和客户环境融合，没有真实标签发布授权。
- 字体选择需要同时冻结可分发许可证、字体二进制、真实文件 SHA-256、PDF 嵌入策略、缺字策略和历史版本重建能力。

强制门禁：

1. 在任何包含中文商品名、供应商名或 SKU 的客户标签验收前完成中文字体资产专项。
2. 新字体必须使用新的 `layout_version`、`renderer_version` 或字体摘要，不得改变旧 key 的 PDF 重放字节。
3. 必须增加中文、英文、数字、常用符号、超长文本和缺字负向测试。
4. 该项未关闭前，不得把标签功能标记为中文生产可用，也不得进入客户试点发布。

该延期不阻断 SC-F2-2 API 原子幂等 P1 整改复核，但继续阻断客户端标签融合和中文标签验收。

## 5. 自动化验证

| 验证 | 结果 |
| --- | --- |
| SC-F2-2 API SQLite 定向 | `22 passed` |
| 三份 F2 测试文件真实 MySQL 8 | `45 passed` |
| 后端完整 SQLite 回归 | `464 passed, 11 skipped` |
| Django system check | 通过 |
| `makemigrations --check --dry-run` | `No changes detected` |
| Python compileall | 通过 |

SQLite 完整回归中的 11 项 skip 均为要求真实 MySQL 行锁/唯一键语义的专项测试；这些测试已在临时 MySQL 8 容器中执行。

临时 MySQL 8 容器仅绑定 `127.0.0.1`，无持久化卷。首次测试因普通临时用户没有创建 Django `test_*` 数据库的权限而在建库前失败；改用同一临时容器 root 账户后 `45 passed`。容器在测试后已停止并自动删除。

## 6. 下一步门禁

下一步只允许执行：

`SC-F2-2 本地 API、权限、DataScope 与原子幂等 P1 整改复核`

独立复核通过前，继续禁止网页端和小程序端业务融合、正式线上连接、真实数据同步、双写、切流、通知和生产部署。
