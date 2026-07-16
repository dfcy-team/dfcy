# UI-P2-ARCH-R1 架构复审提示

请执行 `UI-P2-ARCH-R1`，只审核 UI-P2 系统治理与基础档案成果，不修复业务代码。

## 1. 复审对象

- `backend/apps/accounts/system_serializers.py`
- `backend/apps/accounts/system_views.py`
- `backend/apps/masterdata/`
- `backend/apps/permissions/`
- `backend/tests/test_ui_p2_system_masterdata.py`
- `frontend/src/api/systemAdmin.js`
- `frontend/src/api/masterData.js`
- `frontend/src/components/AdminResourcePage.vue`
- `frontend/src/views/system/`
- `frontend/src/views/masterdata/`
- `frontend/src/router/`
- `frontend/tests/ui-p2-system-masterdata.spec.js`
- `docs/03_api/ui_p2_system_masterdata_contract.md`
- `docs/05_test/ui_p2_system_masterdata_test_report.md`
- `docs/00_stage0/review/ui_p2_system_masterdata_change_log.md`

## 2. 系统治理复审

1. 组织、用户、角色和安全运维查询是否始终按当前 tenant 过滤。
2. external 和 RPA 用户是否被内部治理接口拒绝。
3. 读取和写入是否分别使用 `view` 与 `manage` action permission。
4. 用户邮箱和手机号是否仅脱敏返回，初始密码是否只写且不记录日志。
5. 六层权限 Tenant、用户类型、角色、Permission、Data scope、字段与流程是否明确。
6. 用户角色和角色权限/data scope 更新是否写审计日志。
7. 安全运维是否只返回凭据别名、指纹、版本、状态和验证时间。

## 3. 基础档案复审

1. 平台、店铺、仓库和供应商模型是否具备 tenant。
2. 列表、详情、更新和状态变更是否按 tenant 过滤。
3. code 是否在 tenant 内唯一，跨 tenant 同 code 是否允许。
4. 店铺引用的平台是否必须属于同一 tenant。
5. 启停是否有确认、审计和引用保护。
6. 供应商联系方式是否只脱敏回显。
7. 是否未写入真实供应商、店铺、平台或凭据数据。

## 4. 前端权限与状态复审

1. 8 条 UI-P2 非公开路由是否全部登记 capability，未登记路径是否默认拒绝。
2. 创建、启停、角色与权限配置是否使用后端 action permission。
3. 动作是否在展示和 API 调用前双重校验。
4. 页面是否具备 loading、empty、error、列表、分页和详情状态。
5. `VITE_USE_MOCK=true` 是否只使用 Mock，`false` 是否按冻结合同调用后端。
6. Mock 或待 Pilot 联调的接口是否未误标为生产 connected。

## 5. 安全与高风险边界

- 扫描真实 `.env`、账号、密码、Token、Cookie、Session、API Key、API Secret 和证书。
- 确认无真实 BigSeller、Shopee、TikTok/TK、银行或支付连接。
- 确认无自动采购、改价、清仓、停售、归档、真实 RPA 或资金操作。
- 确认前端权限不替代后端 tenant、data scope 和 Permission 校验。

## 6. 必须执行

- `python manage.py check`
- `python manage.py makemigrations --check --dry-run`
- `pytest -q backend/tests/test_ui_p2_system_masterdata.py`
- 全量后端 pytest
- `npm test -- --run tests/ui-p2-system-masterdata.spec.js`
- 全量前端 Vitest
- `npm run build`
- 路由与 action permission 静态扫描
- 敏感凭据和真实平台连接扫描
- Git 文件范围检查

未执行项必须写明原因，不得使用变更日志代替实际执行证据。

## 7. 输出

创建 `docs/00_stage0/review/ui_p2_arch_recheck_report.md`，结论只能为 `PASS`、`CONDITIONAL_PASS` 或 `FAIL`。

- 有 P0：`FAIL`。
- 无 P0 但有未关闭 P1：`CONDITIONAL_PASS`。
- 无 P0/P1：`PASS`。

报告末尾必须明确是否允许 UI-P2 正式收尾，以及是否允许进入下一阶段界面设计。
