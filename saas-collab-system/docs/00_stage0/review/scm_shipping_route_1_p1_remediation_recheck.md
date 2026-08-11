# SC-SHIP-ROUTE-1 P1 整改复核

## 1. 复核结论

| 项目 | 结论 |
| --- | --- |
| 原审核 | `SC-SHIP-ROUTE-1-R1` |
| 整改提交 | `178dc294f4f871fed04b0b08099ba99bdf392ef4` |
| P0 | 0 |
| P1 | 0；原 P1-001、P1-002 均关闭 |
| P2 | 0；原 P2-001、P2-002 均关闭 |
| 复核结论 | `SC_SHIP_ROUTE_1_P1_REMEDIATION_APPROVED` |
| 下一门禁 | 提交后基线确认与最终本地审核归档 |
| 线上系统授权 | 无 |

整改提交满足原审核的关闭条件，未发现能够通过普通 ORM 伪造采购单完工状态或通过直接领域服务调用绕过路线权限与 DataScope 的路径。散货/柜货路线仍只允许在生产完工后由采购权限主体决定，未扩大到 SC-F3 后续物流动作。

## 2. 审核边界

固定审核对象只包含 5 个文件：

- `backend/apps/purchasing/models.py`；
- `backend/apps/purchasing/supply_services.py`；
- `backend/apps/purchasing/views_supply.py`；
- `backend/tests/test_supply_chain_shipping_route.py`；
- `docs/00_stage0/review/scm_shipping_route_1_p1_remediation_report.md`。

整改提交后上述文件无未提交漂移。工作树中产品开发、刊登、前端、试点部署及其他并行内容没有进入整改提交，也不属于本轮复核对象。

## 3. P1 关闭复核

### 3.1 SC-SHIP-ROUTE-1-R1-P1-001：关闭

模型新建入口在非领域动作上下文中强制以下规范初值：

- `pending + undecided`；
- 完成数量为 0、版本为 1；
- 接单、开工、完工时间为空；
- 路线决定人和决定时间为空。

该判断位于模型 `save()`，覆盖 `objects.create()`、实例 `save()` 和 admin 最终保存入口；伪造 `_action_service_write` 实例属性不会创建 ContextVar 授权上下文。既有 QuerySet update、bulk update、bulk create 和事件追加写入防护保持有效。

独立负向复测覆盖伪完工状态、伪完成数量、伪完工时间、伪版本以及路线字段和事件 ORM 绕过。SQLite 相关负向矩阵通过，MySQL 新建受控状态 4 项负向测试全部通过。

### 3.2 SC-SHIP-ROUTE-1-R1-P1-002：关闭

路线领域服务在读取订单、幂等事件和响应快照前，统一执行：

1. `supply.purchase_order.assign_shipping_route` 权限检查；
2. 至少一个有效 DataScope 检查；
3. 基于相同权限的租户与订单 DataScope 过滤；
4. 范围外对象稳定按 404 隐藏。

API 路线动作不再维护重复授权分支，直接复用领域服务边界。独立复测确认：

- 无角色、角色无权限、权限存在但无 DataScope 均为 403；
- CUSTOM 空范围和跨租户均为 404；
- ALL、OWN、CUSTOM supplier、CUSTOM order 正常工作；
- 已存在相同幂等记录时，无当前权限的主体仍先被拒绝，不能取得重放快照。

## 4. P2 关闭复核

### 4.1 SC-SHIP-ROUTE-1-R1-P2-001：关闭维持

本轮在新的仓库外临时 MySQL 库中独立重跑：

- `purchasing 0004 → 0005`；
- `permissions 0018 → 0019`；
- 历史采购单和事件的 `undecided` 默认补值；
- 路线决定人外键及 `supply_po_route_decision_consistent` CHECK；
- 非法已决定路线与空决定元数据组合拒绝；
- 反向迁移移除字段及权限；
- 再次前进恢复默认值及唯一权限。

结果：`SC_SHIP_ROUTE_RECHECK_MYSQL_MIGRATION PASS`。临时库随后删除，MySQL 容器停止。

门禁决定维持：MySQL 并发测试的 `--no-migrations` 只能证明当前模型行锁语义；路线迁移准入必须同时保留定向真实迁移实证。

### 4.2 SC-SHIP-ROUTE-1-R1-P2-002：关闭维持

领域服务已独立校验 action、幂等 key、正整数版本、路线枚举和 2,000 字符 reason 合同。非字符串 key、布尔/零版本、非字符串 reason、超长 reason 均返回稳定业务校验错误，不再依赖 HTTP serializer 或触发 Python 类型异常。

## 5. 独立复测结果

| 验证 | 结果 |
| --- | --- |
| P1/P2 关键负向与授权矩阵 | 13 passed |
| MySQL 新建受控状态 ORM 负向测试 | 4 passed |
| SC-F1 + SC-F2 + shipping route SQLite 回归 | 67 passed |
| MySQL 定向迁移、约束、回退与重放 | PASS |
| Django system check | 0 issues |
| `makemigrations --check --dry-run` | No changes detected |
| Python 编译 | PASS |

整改报告中记录的 F1/F2/路线 MySQL 并发回归为 12 passed，本轮代码审核未发现使该并发结论失效的变更。

## 6. 最终决定

`SC-SHIP-ROUTE-1 P1 整改复核`通过。允许进入提交后基线确认与最终本地审核归档；不代表允许连接、迁移或发布至供应链正式线上系统。
