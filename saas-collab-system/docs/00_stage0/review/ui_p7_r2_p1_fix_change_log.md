# UI-P7 R2 P1 定向整改日志

## 1. 整改目标

本次整改用于关闭 `UI-P7-ARCH-R2` 发现的 3 项 P1。整改范围限于 UI-P7 容量合同、恢复/发布计划约束与审计、前端应用状态和自动化测试，不增加真实基础设施执行、真实平台接入或高风险自动化能力。

## 2. P1 关闭情况

| P1 | 整改结果 | 主要证据 | 待独立复审 |
|---|---|---|---|
| 容量 `critical` 状态及阈值映射不完整 | 已整改 | `backend/apps/pilot/models.py`、`serializers.py`、`views.py`、`migrations/0003_capacity_status_and_rollback_approval_unique.py`、`backend/tests/test_ui_p7_governance_pilot.py` | 核验五态精确筛选及阈值映射 |
| 回滚批准唯一性、批量创建防绕过及计划创建失败审计未闭合 | 已整改 | `backend/apps/pilot/models.py`、`services.py`、`views.py`、迁移 `0003`、UI-P7 后端专项测试 | 核验数据库唯一约束、`bulk_create` 拒绝和失败审计不可变性 |
| 缺少真实组件状态矩阵测试，无效详情 URL 未显示 404 | 已整改 | `frontend/src/components/AppState.vue`、`frontend/src/utils/uiState.js`、`frontend/src/views/governance/GovernanceCatalog.vue`、`frontend/tests/ui-p7-component-states.spec.js` | 核验真实组件挂载状态矩阵和直达详情 404 |

## 3. 后端整改

- 容量状态冻结为 `normal`、`warning`、`critical`、`unknown`、`stale`；列表按状态精确过滤。
- `normal/warning` 返回 warning 阈值，`critical` 返回 critical 阈值，`unknown/stale` 不返回阈值。
- `rollback_approval_ref` 增加数据库唯一约束并允许未批准记录使用 `NULL`，避免空字符串参与唯一性冲突。
- 恢复计划和发布计划继续禁止受保护字段的 `bulk_create` 绕过。
- 计划创建的字段校验、data_scope、幂等键和数据库冲突失败均写入不可变失败审计；缺少幂等键时使用仅供审计关联的随机占位摘要，不写入真实凭据。

## 4. 前端整改

- 应用状态增加 `unauthenticated`、`not_found`、`stale` 的可见组件状态。
- HTTP 404 不再折叠为空数据，而是显示资源不存在状态。
- 治理详情直达无效 URL 时显示可见 404；列表内详情失败显示受控错误，不伪造成功或 `connected`。
- 新增真实 Vue 组件挂载测试，覆盖 loading、empty、401、403、404、409、422、partial、stale、offline 和无效详情 URL。
- 测试环境关闭 Element Plus 自动样式注入；生产构建继续按组件导入样式。

## 5. 验证结果

| 检查 | 结果 |
|---|---|
| Django check | PASS，0 issues |
| migration 一致性 | PASS，No changes detected |
| 临时数据库全量迁移 | PASS，`pilot.0003` 成功应用 |
| UI-P7 后端专项 pytest | PASS，56 passed |
| 后端全量 pytest | PASS，378 passed |
| 前端真实组件状态矩阵 | PASS，20 passed |
| 前端全量测试 | PASS，10 files / 130 passed |
| `npm run build` | PASS |
| Docker Compose 静态解析 | PASS，仅有未加载真实环境变量的空值提示 |
| RPA JSON 解析 | PASS，16 files / 0 invalid |
| 高置信密钥模式扫描 | PASS，0 matches |
| `git diff --check` | PASS，仅有行尾转换提示 |

## 6. 安全确认

- 未提交真实 `.env`、账号、密码、Token、Cookie、Session、API Key、API Secret、证书或私钥。
- 未接入真实 BigSeller、Shopee、TikTok/TK、银行、支付或 AI provider。
- 未执行真实部署、恢复、回滚、RPA、自动采购、改价、清仓、停售、归档或资金动作。
- 未修改 `rpa-agent/` 真实执行代码或 `docs/04_rpa/` 协议。
- `frontend/dist`、`node_modules` 和 RPA 运行产物未进入跟踪范围。

## 7. 待复审事项

本日志只记录整改与本地验证结果，不替代独立架构复审。下一步应执行 `UI-P7-ARCH-R3`，逐项复核上述 3 项 P1；R3 通过前不得正式收尾或开放真实平台、真实基础设施及高风险动作。
