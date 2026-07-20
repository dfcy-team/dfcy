# UI-P8-ARCH-R2 独立整改复审提示

只审核，不修复。审核对象为 `feature/ui-p8-production-pilot-security-readiness`，对比最新 `main`。

## 1. 复审依据

- `docs/00_stage0/review/ui_p8_arch_r1_recheck.md`
- `docs/00_stage0/review/ui_p8_r1_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p8_jwt_e2e_result.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/03_api/ui_p8_production_pilot_security_contract.md`
- `docs/05_test/ui_p8_production_pilot_security_acceptance.md`
- UI-P8 后端、前端、迁移和测试代码

## 2. 六项 P1 复审

1. 财务安全评审 PATCH 是否重新校验 `finance.view`、财务 scope、原/目标环境及受控 target/evidence 引用，跨 tenant、跨环境或未登记引用是否拒绝。
2. 准入批准是否重新读取全部证据并校验 ID、类型、版本、状态、摘要、有效期、tenant、environment 和权限；stale/restricted 是否返回 409 且不生成有效 go。
3. 已认证的 403、422、409 是否产生脱敏、不可变、不可删除且 tenant 删除保护的失败审计，并保持原错误响应。
4. 是否无法通过实例 `save()`、`objects.create()`、QuerySet update/delete、bulk_create/bulk_update 绕过状态机；服务层正常创建仍可执行。
5. 前端是否按后端执行分页、筛选和 PATCH，且 loading、empty、401、403、404、409、422、offline 均有真实组件挂载测试；无效详情 URL 显示 404。
6. 接口映射是否与实现一致；真实 JWT 浏览器 E2E 是否实际验证 login/me、GET、POST、PATCH；远端 CI 是否基于复审 HEAD 全部成功。

## 3. 实际执行

必须实际运行并记录：Django check、migration 一致性、UI-P8 专项与全量 pytest、`npm ci`、UI-P8 专项与全量前端测试、build、真实 JWT 浏览器 E2E、Docker Compose 配置、RPA JSON、路径/密钥/真实平台扫描和远端 CI。未执行项必须写明原因，不得伪造。

## 4. 输出

创建 `docs/00_stage0/review/ui_p8_arch_r2_recheck.md`，逐项列出原 P1 是否关闭、证据、新增 P0/P1/P2、测试与安全结果及是否允许 UI-P8 正式收尾。

结论规则：有 P0 为 `FAIL`；无 P0 但仍有 P1 为 `CONDITIONAL_PASS`；无 P0/P1 为 `PASS`。远端 CI 未成功时不得判定 UI-P8 正式收尾门禁完成。即使 PASS，也不允许直接接入真实平台、生产发布或启用高风险自动化。
