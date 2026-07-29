# SC-F2-2 提交后基线确认与最终本地 API 审核归档

## 1. 最终结论

结论：`SC_F2_2_FINAL_LOCAL_API_AUDIT_ARCHIVED`

SC-F2-2 本地 API、权限、DataScope 与原子幂等实现已经完成提交后基线确认和最终本地审核归档：

- 冻结契约、实现提交、独立代码审核、R2 整改和独立整改复核链完整；
- `SC-F2-2-R2-P1-001` 至 `P1-005` 已关闭；
- 当前基线无未关闭 P0/P1；
- packing 实现树和测试树自整改提交后未再变化；
- frontend 和 miniapp 自 SC-F2-2 实现提交起未发生业务代码变化；
- 本地 SQLite、真实 MySQL 8、migration、Django check 和编译证据完整；
- 未发生供应链正式线上连接、真实数据处理、同步、双写、切流、通知或部署。

唯一未关闭项为中文标签字体 `SC-F2-2-R2-P2-002`。该项具有客户端前置强门禁，不阻断 SC-F2-2 本地 API 归档，但继续阻断客户端标签融合、中文标签客户验收和标签生产可用声明。

## 2. 归档环境与边界

| 项目 | 值 |
| --- | --- |
| 归档日期 | 2026-07-29 |
| 分支 | `codex/scm-f2-packing-local` |
| 归档前 HEAD | `cd64e3591065d75263a5bf2635ddbec2afa5058f` |
| 执行环境 | 架构员主机本地隔离环境 |
| 生产连接、真实数据或发布 | 无 |
| 网页端、小程序端融合 | 未进入 |

工作区存在本阶段以外的既有文档修改和未跟踪文件。它们未被修改、暂存或纳入 SC-F2-2 归档提交。

## 3. 冻结提交链

| 阶段 | 提交 |
| --- | --- |
| SC-F2-2 契约与审核基线 | `b8d701f3e56e4828a5950da6ca4b9b7685a2a63b` |
| 契约 P1 整改复核通过 | `79aceabd65a88658e45f345156bf3a91b7795eac` |
| 本地 API 实现 | `c15f411f5d926fdcce1c6a808d185cc46d34cfc6` |
| 实现独立代码审核 | `045a2803947b0cb7b69af518fff418f90ee00345` |
| R2 P1 代码整改 | `2282f0b3a096c8ff3830b2c7b01ef348fb198a9b` |
| R2 P1 独立整改复核 | `cd64e3591065d75263a5bf2635ddbec2afa5058f` |

提交关系线性，R2 整改复核提交相对整改提交只新增一份复核报告，没有修改 packing 实现、migration 或测试。

## 4. 关键归档文件 SHA-256

| 文件 | SHA-256 |
| --- | --- |
| `docs/03_api/supply_chain_f2_packing_api_contract.md` | `1bc31671f79908859b5204c9c25bb61431cfb2db0da2e1efaff37daf22391cfe` |
| `docs/00_stage0/review/scm_f2_2_local_api_implementation_report.md` | `ab0fa9b1c0a769f2d0a4785c2818f11ed0d002e0e79d38c1487a8edaf250585e` |
| `docs/00_stage0/review/scm_f2_2_local_api_code_review.md` | `8c003e7fc6e9c7d5c994271724740e4025ca9c58de70a3decd610d9f5aab5f62` |
| `docs/00_stage0/review/scm_f2_2_r2_p1_remediation_report.md` | `df93b8eb4627a1bc619193f6afc1b2125cefbb9e8573ef7a21fa0bd3747fc33a` |
| `docs/00_stage0/review/scm_f2_2_r2_p1_remediation_recheck.md` | `208d11413e762aac21ea66493a0cf82b080a09029e3ac625331f991bc050397b` |

## 5. 提交后代码树确认

### 5.1 packing 实现与测试

| Git tree | 整改提交 `2282f0b` | 复核提交 `cd64e35` | 结论 |
| --- | --- | --- | --- |
| `backend/apps/packing` | `cd76feed37939b7dd9994a07f80f6fcba7498773` | `cd76feed37939b7dd9994a07f80f6fcba7498773` | 一致 |
| `backend/tests` | `c20923b49f0db6aaa27b8b5154ed78e5e7bb77ce` | `c20923b49f0db6aaa27b8b5154ed78e5e7bb77ce` | 一致 |

因此独立复核所验证的代码就是最终归档实现，没有“复核后再改代码”的漂移。

### 5.2 客户端边界

| Git tree | API 实现提交 `c15f411` | 复核提交 `cd64e35` | 结论 |
| --- | --- | --- | --- |
| `frontend` | `c0a12f165a187cd0bc9e88e53bbb0d555c4b135f` | `c0a12f165a187cd0bc9e88e53bbb0d555c4b135f` | 未变 |
| `miniapp` | `a8b4a2c28f0ad9b1ae7fcc28d114301a06f2cda4` | `a8b4a2c28f0ad9b1ae7fcc28d114301a06f2cda4` | 未变 |

SC-F2-2 没有提前进入网页端或小程序端业务融合。

## 6. 最终功能与安全基线

最终归档基线包含：

- internal、supplier Web、miniapp 三通道隔离；
- 5 个 exact `supply.packing.*` permission；
- permission-specific ALL、OWN、CUSTOM DataScope；
- 历史订单关联授权、创建 supplier/order scope 和 404 防枚举；
- 供应商绑定、活动主档、self-pack 与仅创建时 mix 能力门禁；
- 严格 JSON Content-Type、逐端点 query 白名单、严格 body DTO；
- Decimal 字符串、版本门禁、POST remove action 和旧 DELETE 不可达；
- `PackingApiIdempotencyRecord` 冻结 JSON/PDF 结果；
- `(tenant, scope, key)` 和 `(tenant, key)` 双重唯一约束；
- MySQL 1205/1213 到 `409 STATE_CONFLICT` 的完整 API 路径转换；
- 同 key 跨资源并发身份冲突、同 key 重放和事务失败全量回滚；
- items 规范化 request hash；
- 确定性标签快照、QR、PDF 字节和 ETag；
- F2 不推进 SC-F1 状态，不产生 F3 或物流动作。

## 7. 自动化与完整性证据

| 验证 | 最终证据 |
| --- | --- |
| 后端完整 SQLite 回归 | `464 passed, 11 skipped` |
| 独立真实 MySQL 8 并发复核 | `8 passed` |
| 整改阶段三份 F2 文件 MySQL 8 | `45 passed` |
| 最终归档 API 定向复验 | `22 passed` |
| Django system check | 通过 |
| `makemigrations --check --dry-run` | `No changes detected` |
| packing/test compileall | 通过 |
| Git diff whitespace | 通过 |
| Git fsck | 无 error、fatal 或 missing |

11 项 SQLite skip 均为真实 MySQL 专项；对应并发文件已在独立临时 MySQL 8 中全部通过。所有临时 MySQL 容器均只绑定本机回环地址、不挂持久化卷，执行后已停止并自动删除；最终归档临时 SQLite 文件也已清理。

## 8. 未决 P2 门禁

`SC-F2-2-R2-P2-002` 状态：

`ACCEPTED_DEFERRED_WITH_PRE_CLIENT_GATE`

在关闭该项前：

1. 不得声明中文标签生产可用；
2. 不得进入客户端标签融合或中文标签客户验收；
3. 必须冻结可分发中文字体文件、许可证、真实 SHA-256、嵌入和缺字策略；
4. 必须使用新的布局/渲染/字体版本，保持历史 key PDF 字节不变；
5. 必须覆盖中文、英文、数字、常用符号、超长文本和缺字测试。

## 9. 风险统计

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 0 | 无生产或数据安全越界 |
| P1 | 0 | SC-F2-2 R2 五项均关闭 |
| P2 | 1 | 中文字体带强门禁延期 |

## 10. 后续准入

SC-F2-2 本地 API 阶段可以正式收尾。

允许的后续动作仅为：

- 基于本归档准备下一阶段立项、范围和契约审核；
- 单独启动中文标签字体资产专项。

本归档不自动授权网页端或小程序端开发、真实数据迁移、正式线上数据库 migration、外部通知、双写、同步、切流、客户试点或生产部署。下一阶段必须重新冻结范围、权限、DataScope、客户端契约、测试门禁和生产隔离要求后方可进入开发。
