# UI-P6-ARCH-R1 P1 整改变更日志

## 1. 整改对象

依据 `ui_p6_arch_r1_recheck.md`，本次定向关闭：

- UI-P6-R1-P1-001：permission-specific `data_scope` 未严格拒绝未知 key 和非法值。
- UI-P6-R1-P1-002：integrations 配置 PATCH 可将资源修改到授权范围外。
- UI-P6-R1-P1-003：前端会将非统一 HTTP 200 响应包装为成功并标记 `connected`。

## 2. 修改文件

- `backend/apps/permissions/ui_p6_scopes.py`
- `backend/apps/integrations/views.py`
- `backend/tests/test_ui_p6_data_scope_validation.py`
- `backend/tests/test_phase2_integrations_secure_config.py`
- `frontend/src/api/request.js`
- `frontend/tests/phase3-contracts.spec.js`
- `frontend/tests/ui-p6-api-analysis.spec.js`

## 3. P1整改情况

| P1编号 | 整改结果 | 实现与证据 | 待复审 |
|---|---|---|---|
| UI-P6-R1-P1-001 | 已整改 | scope 顶层 key 采用 permission/module 白名单；analytics、lifecycle、integrations、finance、reports 对字符串、正整数、ISO 4217 和资源枚举执行严格值校验；未知 key/非法值统一抛出 `403 DATA_SCOPE_INVALID`。新增通用及端点负向测试。 | 独立验证未知 key、空字符串、非法 ID、非法 currency/report type 均不能进入查询或动作。 |
| UI-P6-R1-P1-002 | 已整改 | PATCH 在保存前使用候选 `platform` 和当前 `config_id` 重新执行 `integrations.manage` scope 校验；越权返回 `403 DATA_SCOPE_FORBIDDEN`，对象保持原值。新增 `mock -> other` 回归测试。 | 独立复现越权 PATCH 并确认数据库未变化。 |
| UI-P6-R1-P1-003 | 已整改 | 前端只接受包含合法 `success/code/message/data` 类型的统一 envelope；协议异常返回 `INVALID_API_RESPONSE`，`withApiStatus` 仅对 `success=true` 写入 connected。更新旧合同测试并新增 malformed payload 测试。 | 独立验证 HTTP 200 非统一 payload 不得成为 success/connected。 |

## 4. 验证结果

- `python manage.py check`：通过，0 issues。
- `python manage.py makemigrations --check --dry-run`：通过，无模型变更。
- 后端定向测试：18 passed。
- 后端全量测试：322 passed。
- 前端定向测试：34 passed。
- 前端全量测试：8 files、99 tests passed。
- `npm run build`：通过，1934 modules transformed。
- 非统一 payload 探针：返回 `success=false`、`code=INVALID_API_RESPONSE`、`data=null`，未写入 connected。

## 5. 安全与边界确认

- 未接入真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。
- 未提交真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
- 未放开自动采购、自动清仓、停售、归档、改价、真实 RPA 或资金动作。
- 未修改原 UI-P6-ARCH-R1 审核结论；是否关闭 P1 仍由独立 UI-P6-ARCH-R2 确认。
- 工作区内无关 DOCX 未处理、未纳入本次整改范围。

## 6. 下一步

执行独立 `UI-P6-ARCH-R2`，重点复核三个原始负向场景以及全量回归结果。R2 给出 PASS 前，不进行 UI-P6 正式收尾。
