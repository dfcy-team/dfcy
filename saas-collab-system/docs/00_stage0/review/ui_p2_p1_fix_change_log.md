# UI-P2 P1 整改变更日志

## 1. 整改对象

依据 `ui_p2_arch_recheck_report.md`，定向关闭后端 Data scope、角色动作权限流程、角色分页和连接状态误标四项 P1。R1 报告保持原始结论，不以本日志替代 R2 独立复审。

## 2. P1 关闭情况

| 编号 | 整改结果 | 主要证据 |
|---|---|---|
| UI-P2-P1-001 | 已整改 | `api_permissions.py`、`ui_p2_scopes.py`、`system_views.py`、`masterdata/views.py`、`test_ui_p2_system_masterdata.py` |
| UI-P2-P1-002 | 已整改 | `UserDirectory.vue`、`RolePermissionMatrix.vue`、`systemAdmin.js`、`system/user-role-options/` 与角色绑定审计测试 |
| UI-P2-P1-003 | 已整改 | `RolePermissionMatrix.vue` 的 `count/page/page_size` 与分页控件；后端第二页回归测试 |
| UI-P2-P1-004 | 已整改 | `AdminResourcePage.vue`、`RolePermissionMatrix.vue`、`SecurityOperations.vue` 的 `mock/pending/connected/degraded` 状态合同测试 |

## 3. Data scope 规则

- permission 与 Data scope 必须来自同一有效角色授权链；缺少对应 scope 返回 `403`。
- 用户、部门、角色和基础档案列表及对象写操作执行一致范围。
- 用户角色绑定同时限制目标用户和可分配角色；`custom` 使用 `user_ids` 与 `role_ids`，避免角色提权。
- 安全运维、角色权限维护和全量创建类动作要求 `all` scope。

## 4. 动作与状态

- 新建角色、用户启停、用户角色绑定和角色权限保存均进行展示前与请求前二次权限校验。
- 角色目录分页可访问超过首 20 条的数据，且空页仍保留返回有效页的入口。
- 未完成真实请求时不显示 connected；Mock、待接入、网络降级和真实连接状态分别标记。

## 5. 实际验证

- `python manage.py check`：PASS。
- `python manage.py makemigrations --check --dry-run`：PASS，`No changes detected`。
- UI-P2 后端专项：`19 passed in 14.22s`。
- 后端全量：`271 passed in 20.17s`。
- UI-P2 前端专项：`8 passed`。
- 前端全量：`4 files / 69 passed`。
- `npm run build`：PASS，`1903 modules transformed`。
- `@vueuse/core` PURE 注释提示为第三方非阻断观察项。

## 6. 安全确认

- 未新增真实 `.env`、账号、密码、Token、Cookie、Session、API Key、API Secret 或证书。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未启用自动采购、改价、清仓、停售、归档、真实 RPA 或资金操作。
- 前端权限只控制呈现，后端 tenant、permission、Data scope 和对象范围仍为最终安全边界。

## 7. 待复审

执行 `UI-P2-ARCH-R2`，独立复核四项 P1 的代码、测试和状态合同后再决定是否允许 UI-P2 正式收尾。
