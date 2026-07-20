# UI-P8-ARCH-R1 独立实现复审提示

只审核，不修复。审核对象为 `feature/ui-p8-production-pilot-security-readiness`，对比最新 `main`。

## 1. 必查依据

- `docs/01_architecture/ui_p8_production_pilot_security_scope.md`
- `docs/03_api/ui_p8_production_pilot_security_contract.md`
- `docs/05_test/ui_p8_production_pilot_security_acceptance.md`
- `docs/00_stage0/review/ui_p8_contract_freeze_report.md`
- `docs/00_stage0/review/ui_p8_arch_contract_r3_recheck.md`
- `docs/00_stage0/review/ui_p8_implementation_report.md`
- `backend/apps/pilot/`、`backend/apps/permissions/ui_p8_scopes.py`
- `backend/tests/test_ui_p8_production_pilot_security.py`
- `frontend/src/api/pilot.js`、`frontend/src/mock/pilot.js`
- `frontend/src/views/pilot/`、`frontend/tests/ui-p8-production-pilot-security.spec.js`

## 2. 复审重点

1. 五个工作台及冻结 API 是否完整，是否存在重复路径、缺失端点或错误的 connected 标记。
2. 17 个 exact permission、internal 用户边界和 action permission 是否逐端点执行。
3. permission-specific data_scope 是否拒绝缺失、未知、非法、空、重复、未登记和越界值；ALL 是否仅覆盖当前 tenant。
4. 创建授权、存量资源 ID scope、PATCH 原/目标环境、owner 只读和跨资源证据授权是否闭合。
5. 财务边界创建、修改、提交和评审是否同时要求 pilot 权限与 `finance.view`，是否只返回脱敏范围。
6. 安全评审、验证、性能和准入状态机是否只能走专用服务；实例保存、QuerySet update/delete、bulk 操作和通用 PATCH 是否无法绕过。
7. 职责分离、版本、幂等、取消、过期、结果语义及并发冲突是否按合同返回 409。
8. 成功、拒绝、越 scope、422、409 和系统过期审计是否完整且不可修改、不可删除、不可因 tenant 删除级联消失。
9. 准入证据快照、哈希、时效和来源权限是否由后端确认；stale 或 restricted 是否不产生 ready/go。
10. 前端路由、菜单、详情 URL、loading/empty/error/404 和 action 可见性是否与后端权限一致。
11. 页面是否不存在真实 URL、凭据、Web Shell、命令输入、平台连接、部署、恢复、回滚、真实 RPA 或资金动作。
12. 实际复跑 Django check、迁移一致性、专项/全量 pytest、npm ci、专项/全量前端测试、build、Compose、RPA JSON、安全和路径扫描。
13. 在受限角色下执行真实 JWT 浏览器 E2E；如环境不允许，必须明确记录“未执行”及原因，不得伪造 connected。
14. 检查工作区范围，排除无关 DOCX、`docs/00_stage0/architecture/` 和 `docs/04_rpa/协同开发下发/`。

## 3. 输出

创建：

`docs/00_stage0/review/ui_p8_arch_r1_recheck.md`

报告至少包含：

- 审核对象与基线
- 后端模型、API、权限、scope、状态机及审计
- 前端页面、路由、权限、状态组件和 Mock/pending 状态
- 测试、构建、Docker、RPA JSON、浏览器 E2E 和安全扫描实际结果
- P0/P1/P2
- 是否允许 UI-P8 正式收尾

结论仅允许：

- 有 P0：`FAIL`
- 无 P0 但有 P1：`CONDITIONAL_PASS`
- 无 P0/P1：`PASS`

即使 PASS，也不代表允许真实平台接入、生产发布或高风险自动化；这些动作仍需独立专项评审。
