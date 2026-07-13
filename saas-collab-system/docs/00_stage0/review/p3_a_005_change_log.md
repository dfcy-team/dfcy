# P3-A-005 经营预警规则引擎变更日志

## 交付

- 新增 `BusinessAlertRule`、`BusinessAlert` 与不可变 `BusinessAlertActionLog`。
- 支持销量下降、滞销、对账差异、供应商逾期、RPA失败、页面签名变化、同步失败和数据陈旧预警。
- 条件引擎仅支持受限数值操作符，不执行表达式或动态代码；仅允许当前已生效的最新启用规则版本。
- 支持 tenant 级去重、静默、重新触发、人工分配、关闭、DataScope 和审计。
- 新增 business 预警列表、详情、Mock 评估、分配、静默和关闭接口。

## 安全边界

- 预警仅提示和分配处理，不调用真实平台、不触发 RPA、不改变商品状态、不执行财务动作。
- 输入详情、标题和操作说明在落库前脱敏。
- 只允许授权 internal 用户访问；external 与 RPA 拒绝。

## 验证

- P3-A-005 定向测试：`15 passed`。
- 全量 pytest：`218 passed`。
- Django check：通过，`0 issues`。
- 迁移一致性：通过，`No changes detected`。
- 全新临时数据库迁移与权限目录检查：通过，`Permission catalog is complete`。
- 安全文件扫描、Docker Compose 配置与 `git diff --check`：通过。
