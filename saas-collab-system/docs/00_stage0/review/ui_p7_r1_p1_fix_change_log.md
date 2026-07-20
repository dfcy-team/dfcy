# UI-P7 R1 P1 定向整改日志

## 1. 整改目标

本次整改用于定向关闭 `UI-P7-ARCH-R1` 发现的 5 项 P1。整改仅完善冻结合同、权限与 data_scope、恢复/发布记录型工作流、前端动作链和测试证据，不增加真实基础设施执行、真实平台接入或高风险自动化能力。

## 2. P1 关闭情况

| 原P1编号 | 整改结果 | 主要证据 | 待R2确认 |
|---|---|---|---|
| UI-P7-R1-P1-001 | 已整改 | `backend/apps/governance/serializers.py`、`backend/apps/pilot/serializers.py`、`backend/apps/pilot/views.py`、`backend/apps/common/exceptions.py`、`frontend/src/mock/governance.js`、`frontend/src/mock/pilot.js` | 公共字段、枚举、分页和 400/401/403/404/409/422 是否逐项符合冻结合同 |
| UI-P7-R1-P1-002 | 已整改 | `backend/apps/pilot/models.py`、`backend/apps/pilot/services.py`、`backend/apps/pilot/migrations/0002_pilotauditevent_outcome_error_code.py`、`backend/tests/test_ui_p7_governance_pilot.py` | 关键字段防绕过、回滚引用唯一、过期/冲突/职责分离失败审计是否不可变 |
| UI-P7-R1-P1-003 | 已整改 | `backend/apps/permissions/ui_p7_scopes.py`、`backend/apps/pilot/views.py`、`backend/tests/test_ui_p7_governance_pilot.py` | 登记值、数量、去重、ALL受控范围、创建与 action exact permission scope 是否严格执行 |
| UI-P7-R1-P1-004 | 已整改 | `frontend/src/views/pilot/PilotWorkflow.vue`、`frontend/src/views/governance/GovernanceCatalog.vue`、`frontend/src/api/pilot.js` | 排期、开始、结果、恢复、取消、独立回滚批准/记录动作及详情直达是否按权限可用且仅记录受控外部操作 |
| UI-P7-R1-P1-005 | 已整改 | `backend/tests/test_ui_p7_governance_pilot.py`、`frontend/tests/ui-p7-governance-pilot.spec.js`、`docs/00_stage0/review/ui_p7_test_result.md` | 自动化覆盖和受控 JWT sandbox 浏览器证据是否足以关闭原缺口 |

## 3. 关键整改说明

### 3.1 响应与错误合同

- 治理、准入、拓扑和容量响应字段已按冻结合同统一。
- 列表保持 `count/next/previous/results` 分页外壳。
- 未知字段、非法分页、字段校验、幂等冲突、门禁失败、职责分离和回滚批准错误使用精确错误码，失败响应保持 `data=null`。
- 非法查询枚举、日期和排序不再静默返回空列表。

### 3.2 状态机与审计

- 恢复和发布关键字段禁止通过实例 `save()`、QuerySet `update/delete` 或批量接口绕过专用服务。
- 回滚批准引用跨计划唯一，批准有效期、引用匹配和职责分离均由服务校验。
- 成功和失败动作均写入不可变审计；失败审计包含脱敏后的错误码和原因。
- 所有页面动作仍是计划、审批和外部受控结果记录，不执行部署、恢复、回滚、SQL、Shell 或主机命令。

### 3.3 permission-specific data_scope

- 未知 key、非法值、重复值、空数组和超限数组均拒绝。
- ID、环境和枚举值必须来自受控登记范围。
- `ALL` 仅覆盖受控登记资源，不扩展到任意新增环境。
- 创建、详情和每个 action 按对应 permission 独立求值；external、RPA、跨 tenant 和超 scope 请求均拒绝。

### 3.4 前端动作与详情

- 恢复/发布工作台补齐创建、提交、审批/拒绝、排期、开始记录、结果、恢复、取消及独立回滚批准和结果记录。
- plan、review、record、rollback 权限分别控制动作显示和调用。
- API 合同和助手详情路由可按 `:id` 直接加载，不依赖先点击列表行。
- Mock/dry-run 使用有状态双状态机；真实 API 成功仍保持 `sandbox`，未验证能力不标记 `connected`。

## 4. 验证结果

| 检查 | 结果 |
|---|---|
| Django check | PASS，0 issues |
| migration 一致性 | PASS，No changes detected |
| UI-P7 后端专项 pytest | PASS，52 passed |
| 后端全量 pytest | PASS，374 passed |
| UI-P7 前端专项测试 | PASS，11 passed |
| 前端全量测试 | PASS，9 files / 110 passed |
| `npm run build` | PASS |
| Docker Compose 静态解析 | PASS；仅因未加载真实环境变量产生空变量提示 |
| RPA JSON | PASS，16 个文件，0 invalid |
| 常见真实密钥模式扫描 | PASS，0 matches |
| 受控 JWT sandbox 浏览器 E2E | PASS；登录、详情直达、试点准入及精确字段已验证，控制台 error/warn 为 0 |

补充说明：全量后端测试曾因既有供应商绩效测试使用系统本地 `date.today()`，在 Django 时区跨日窗口产生 1 个失败；已将测试日期改为 `timezone.localdate()`，未修改业务逻辑。修正后该模块 `9 passed`，全量 `374 passed`。

## 5. 安全确认

- 未接入真实 BigSeller、Shopee、TikTok/TK、AI provider、银行或支付平台。
- 未提交真实 `.env`、账号、密码、Token、Cookie、Session、API Key、API Secret、证书或私钥。
- 未执行真实部署、恢复、回滚、RPA、自动采购、改价、清仓、停售、归档或资金动作。
- 未修改 `rpa-agent/` 真实执行代码和 `docs/04_rpa/` 协议。
- 受控浏览器数据仅为本地 demo/sandbox，未标记 `connected`。

## 6. 待R2复审事项

1. 独立复核 5 项原 P1 的代码与测试证据，不采用本日志结论替代实际检查。
2. 复核失败审计、关键字段防绕过、回滚批准失效及双状态机终态。
3. 复核 external/RPA/tenant/system/ALL、详情 404、请求体 403 和各 action 独立 scope。
4. 复核真实 JWT 会话下的 sandbox 状态、详情直达和页面动作权限。
5. R2 通过前不得正式收尾、不得标记 `connected`，不得开放真实平台或真实基础设施操作。
