# UI-P7-ARCH-R2 独立复审提示

你现在在 GitHub 项目 `saas-collab-system` 中执行 UI-P7 R1 P1 整改后的独立 R2 复审。

## 1. 任务信息

- 任务编号：`UI-P7-ARCH-R2`
- 审核对象：`feature/ui-p7-governance-pilot-readiness`
- 对比基线：最新 `origin/main`
- 原结论：`CONDITIONAL_PASS`
- 原问题：`UI-P7-R1-P1-001` 至 `UI-P7-R1-P1-005`
- 整改日志：`docs/00_stage0/review/ui_p7_r1_p1_fix_change_log.md`

本次只审核，不修复。不得修改 `backend/`、`frontend/`、`rpa-agent/`、`docs/04_rpa/` 或配置代码。只允许创建：

`docs/00_stage0/review/ui_p7_arch_r2_recheck.md`

## 2. P1-001 响应与错误合同复审

逐项确认：

1. governance、assistant、readiness、topology、capacity 字段和枚举与冻结合同一致。
2. 列表返回 `count/next/previous/results`。
3. 失败响应保持 `success=false` 且 `data=null`。
4. 未知字段、非法分页、字段校验、幂等冲突、门禁失败、职责分离和回滚批准错误返回冻结 HTTP/code。
5. 非法枚举、日期、排序参数返回明确错误，不静默为空列表。
6. 后端、前端 Mock 和页面字段一致。

## 3. P1-002 状态机与审计复审

确认：

1. 恢复/发布关键字段不能通过实例 save、QuerySet update/delete 或批量接口绕过。
2. 回滚批准引用跨计划唯一。
3. 回滚批准过期、引用不匹配、版本冲突、非法状态、门禁失败和职责分离失败均产生不可变失败审计。
4. 审计记录本身不可 update/delete，tenant 和关联对象采用保护语义。
5. 恢复和发布双状态机的终态、manual_required、cancelled、rollback_required 和 rolled_back 回归测试完整。
6. API 只记录外部受控结果，不执行真实基础设施命令。

## 4. P1-003 data_scope 复审

确认：

1. 未知 key、非法值、重复、空数组和超限数组拒绝。
2. ID、环境和枚举必须为受控登记值。
3. `ALL` 只覆盖受控资源。
4. 创建、详情和每个 action 使用对应 permission 的完整 scope。
5. 覆盖 external、RPA、跨 tenant、system、合法超 scope 空列表、详情 404、请求体 403 和 action 403。

## 5. P1-004 前端动作和详情复审

确认：

1. 恢复/发布页面具备创建、提交、批准/拒绝、排期、开始、结果、恢复、取消、回滚批准和回滚结果记录。
2. plan/review/record/rollback 权限分别控制动作显示。
3. API合同和助手详情 URL 可直接加载详情。
4. 页面处理 loading、empty、401、403、404、409、422 和 stale/offline 状态。
5. 页面不提供 Shell、SQL、Docker、真实部署、真实恢复、真实回滚或平台连接能力。

## 6. P1-005 测试与受控E2E复审

实际运行并记录：

- Django check。
- migration 一致性。
- UI-P7 后端专项 pytest。
- 后端全量 pytest。
- UI-P7 前端专项测试。
- 前端全量测试。
- `npm run build`。
- Docker Compose 静态解析。
- RPA JSON 校验。
- 安全扫描和运行产物检查。

使用本地受控 demo 账号验证真实 JWT 登录、详情直达和试点准入真实 API。必须确认响应能力状态为 `sandbox`，不得将未验证接口标为 `connected`。不得使用或记录真实生产凭据。

## 7. 安全边界

确认无真实平台、真实 AI provider、真实密钥、真实业务/财务数据、真实 RPA、自动采购、改价、清仓、停售、归档、付款、转账或提现。不得连接真实双主机或执行恢复/发布演练。

## 8. 输出结构

报告标题：

`# UI-P7-ARCH-R2 独立整改复审报告`

至少包含：

1. 复审对象与基线。
2. 复审结论。
3. 五项原 P1 关闭表。
4. 响应与错误合同。
5. 状态机与不可变审计。
6. permission-specific data_scope。
7. 前端动作、详情和状态。
8. 测试、构建和受控 E2E。
9. 安全扫描。
10. P0/P1/P2。
11. 是否允许 UI-P7 正式收尾。

结论规则：

- 存在 P0：`FAIL`。
- 无 P0 但存在未关闭 P1：`CONDITIONAL_PASS`。
- 无 P0/P1：`PASS`。

即使结论为 PASS，也不代表允许真实平台接入、生产发布、真实恢复/回滚、真实 RPA 或资金动作。
