# SC-F2-2 本地 API、权限、DataScope 与原子幂等 P1 整改复核

## 1. 复核结论

结论：`PASS_FOR_SC_F2_2_FINAL_LOCAL_API_AUDIT`

`SC-F2-2-R2-P1-001` 至 `SC-F2-2-R2-P1-005` 均已关闭。整改提交已消除 API 幂等层数据库冲突泄漏、同 key 跨 scope 并发双提交、供应商存量混单能力误判、请求严格性缺口和 items 规范化不一致。

本轮没有发现新的 P0/P1。`SC-F2-2-R2-P2-001` 已关闭；`SC-F2-2-R2-P2-002` 的书面延期和客户端前置门禁可接受，不阻断本次 P1 复核，但继续阻断中文标签客户验收和客户端标签融合。

## 2. 独立复核基线

| 项目 | 值 |
| --- | --- |
| 复核日期 | 2026-07-29 |
| 分支 | `codex/scm-f2-packing-local` |
| 原代码审核提交 | `045a280` |
| 被复核整改提交 | `2282f0b` |
| 被复核整改报告 | `docs/00_stage0/review/scm_f2_2_r2_p1_remediation_report.md` |
| 冻结 API 契约 | `docs/03_api/supply_chain_f2_packing_api_contract.md` |
| 执行环境 | 架构员主机本地隔离环境 |
| 生产连接、真实数据或发布 | 无 |

整改提交范围为 9 个文件：

- 5 个 packing 实现文件；
- 1 个 packing migration；
- 2 个 SC-F2-2 测试文件；
- 1 份整改报告。

未修改 frontend、miniapp、SC-F1 状态或 F3/物流实现。工作区其他既有修改和未跟踪文件不属于本次复核输入。

## 3. P1 逐项复核

### SC-F2-2-R2-P1-001：API 幂等层 MySQL 1205/1213

复核结果：`PASS`

证据：

1. `api_idempotency.py` 的数据库冲突转换上下文包裹 JSON 和 label 的完整首次执行及唯一冲突恢复路径。
2. 错误码从异常本体或底层 cause 提取，只把 1205/1213 转换为 `StateConflict`。
3. 首次读取、API 记录插入和唯一冲突后重读均有故障注入。
4. 插入故障后批次、事件和日志随最外层事务回滚。
5. 非 1205/1213 的 `OperationalError` 保持原样，不被误报为业务冲突。

关闭理由：契约第 10.4 节和第 11 节要求的 `409 STATE_CONFLICT`、同 key 重试及非目标错误透传均可判定和可测试。

### SC-F2-2-R2-P1-002：同 key 跨资源并发首次请求

复核结果：`PASS`

证据：

1. 原冻结 `(tenant_id, scope_key, idempotency_key)` 唯一约束继续存在。
2. migration 0003 新增 `(tenant_id, idempotency_key)` 唯一约束，作为 tenant 内 key 身份的原子声明。
3. actor、channel、action、scope、resource 和 request hash 仍不进入唯一键，命中后由 `_assert_identity()` 逐项比较。
4. 真实 MySQL 8 中，两个不同批次以同 key 并发新增箱固定得到一个 201 和一个
   `409 IDEMPOTENCY_CONFLICT`。
5. 两个批次合计只有一个箱、一条冻结 API 记录；失败竞争事务没有残留领域写入。

关闭理由：串行和并发首次使用均满足“同 key 不同身份只能有一个胜出身份”，且没有删除或替代契约冻结的 scope 唯一键。

### SC-F2-2-R2-P1-003：供应商存量多订单批次能力边界

复核结果：`PASS`

证据：

1. `mixed_orders=true` 只保留在多采购单批次创建路径。
2. 存量箱动作、完成和变更提交统一只调用 self-pack 能力检查。
3. Web 创建合法混单批次后关闭 mix、保留 self-pack，Web 新增箱和 miniapp 替换箱均成功。
4. 供应商绑定、活动供应商主档和 `can_self_pack` 仍在每次写动作前重新校验。

关闭理由：与冻结端点能力矩阵一致，且未放宽跨供应商、停用供应商或 self-pack 关闭边界。

### SC-F2-2-R2-P1-004：请求严格性

复核结果：`PASS`

证据：

1. F2 POST、PUT 和 PDF action 在读取 serializer 前要求 `application/json`。
2. 无查询参数的详情、标准和 action 使用空白名单；列表使用逐端点白名单。
3. 供应商 Web/miniapp 批次列表只接受合同登记的过滤字段，不接受内部日期字段。
4. weight/volume 只接受 ASCII 普通 Decimal 字符串或 null；JSON number、boolean、符号、科学计数法、超精度和超范围均不能通过。
5. 未知 body 字段仍由严格 serializer 拒绝。

关闭理由：契约第 3.3 节、第 5.2 节、第 6 节和第 8 节的 Content-Type、query、DTO 类型与精度规则已统一。

### SC-F2-2-R2-P1-005：规范化负载

复核结果：`PASS`

证据：

1. 新增/替换箱 serializer 在 API hash 前按 `order_line_id` 排序 items。
2. proposed boxes 中每个箱的 items 使用相同排序，箱数组布局顺序保持不变。
3. items 重排后的同 key 请求返回相同 201 冻结响应和 `Idempotency-Replayed: true`。
4. 重放只产生一个 `ADD_BOX` 事件。
5. 两个 proposed payload 的 items 顺序不同但规范 hash 相同。

关闭理由：API 身份和领域规范化语义一致，不再把无业务含义的 items 输入顺序误判为幂等冲突。

## 4. Permission、DataScope 与防枚举回归

整改没有改写 permission 或 DataScope 算法。完整回归重新确认：

- internal、supplier Web、miniapp 通道继续隔离；
- 5 个 exact `supply.packing.*` permission 边界不混用；
- ALL、OWN、CUSTOM 多维交集、多 scope 并集和非法 scope 安全失败保持；
- 既有批次按全部历史订单关联授权，不按 `active_guard` 过滤；
- 创建按 supplier 和全部 order ID 独立检查 create scope；
- 跨 tenant、scope 和供应商详情/动作继续使用授权 QuerySet 隐藏为 404；
- 供应商能力撤销优先于历史幂等响应重放；
- remove POST action 和旧 DELETE 不可达保持。

## 5. P2 处理复核

### SC-F2-2-R2-P2-001

状态：`CLOSED`

当前标准端点和批次创建复用相同的 `packing-v1` 最新活动版本选择函数；多活动 code 测试证明不会按全表 code 字典序误选标准。

### SC-F2-2-R2-P2-002

状态：`ACCEPTED_DEFERRED_WITH_PRE_CLIENT_GATE`

延期决定具备明确范围、理由和关闭条件：

- 当前 Helvetica 标签版本保持历史字节重放稳定；
- 新中文字体必须冻结许可证、二进制、真实摘要、嵌入和缺字策略；
- 必须使用新布局/渲染/字体版本，不能改变旧 key；
- 中文、符号、长文本和缺字测试必须在客户标签验收前完成。

该项继续阻断客户端标签融合、中文标签验收和标签生产可用声明。

## 6. 独立验证记录

| 验证 | 结果 |
| --- | --- |
| 独立 SC-F2-2 API SQLite 定向 | `22 passed` |
| 独立临时 MySQL 8 并发文件 | `8 passed` |
| 独立后端完整 SQLite 回归 | `464 passed, 11 skipped` |
| Django system check | 通过 |
| `makemigrations --check --dry-run` | `No changes detected` |
| 整改提交 whitespace/diff 检查 | 通过 |

11 项 SQLite skip 均明确依赖真实 MySQL 行锁或唯一键语义；本轮独立 MySQL 并发文件已全部通过。临时 MySQL 8 容器只绑定 `127.0.0.1`、不挂载持久化卷，复核后已停止并自动删除。本地复核 SQLite 临时文件也已清理。

## 7. 风险统计与下一步

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 0 | 无生产、真实数据或安全越界 |
| P1 | 0 | R2 五项 P1 均关闭 |
| P2 | 1 | 中文字体延期，具备客户端前置强门禁 |

允许的下一步：

`SC-F2-2 提交后基线确认与最终本地 API 审核归档`

在最终本地审核完成前，仍禁止网页端和小程序端业务融合、正式线上连接、真实数据同步、双写、切流、通知和生产部署。中文字体专项关闭前，额外禁止客户端标签融合和中文标签客户验收。
