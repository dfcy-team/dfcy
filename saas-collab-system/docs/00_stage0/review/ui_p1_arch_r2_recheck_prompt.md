# UI-P1-ARCH-R2 架构复审提示

请执行 `UI-P1-ARCH-R2`，只审核本次两项P1定向整改，不修复业务代码。

## 复审依据

- `docs/00_stage0/review/ui_p1_arch_recheck_report.md`
- `docs/00_stage0/review/ui_p1_p1_fix_change_log.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/05_test/ui_p1_foundation_test_report.md`

## 复审项一：非公开路由合同

1. `router/index.js` 中每条非公开路由是否均有明确route capability。
2. 未登记路径是否默认拒绝。
3. 详情路径是否继承正确资源权限。
4. `finance.view` 是否不能访问 `/finance/imports`。
5. `finance.import` 是否仅获得导入页面能力，不自动获得其他财务查询能力。
6. external供应商页面是否不能进入internal或finance页面。
7. internal用户是否不能进入external供应商任务页面。
8. 是否有全路由覆盖和直接URL越权测试。

## 复审项二：动作权限

1. 通用动作组件是否实际调用认证store的 `hasPermission()`。
2. 无权动作是否隐藏或禁用并说明原因。
3. 点击处理器是否在调用API前再次校验。
4. view-only用户是否看不到review、manage、export、rollback、reconcile和confirm动作。
5. replenishment、lifecycle、alerts、reports、config、finance、integrations和product status动作是否使用后端现有权限码。
6. 是否仍由后端tenant、data_scope和权限校验作为最终安全边界。

## 必须执行

- `npm test -- --run tests/ui-p1-foundation.spec.js`
- `npm test -- --run`
- `npm run build`
- 路由路径静态扫描
- 动作权限码静态扫描
- 安全扫描

## 输出

创建 `docs/00_stage0/review/ui_p1_arch_r2_recheck_report.md`，结论只能为 `PASS`、`CONDITIONAL_PASS` 或 `FAIL`。

- 有P0：FAIL。
- 无P0但原P1未全部关闭或新增P1：CONDITIONAL_PASS。
- 两项原P1均关闭且无新增P0/P1：PASS。

报告末尾必须明确是否允许UI-P1正式收尾，以及是否允许进入UI-P2。
