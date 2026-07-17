# UI-P6-ARCH-R1 API接入与分析复盘独立复审报告

## 1. 复审对象

- 任务：UI-P6-ARCH-R1 独立架构复审。
- 分支：`feature/ui-p6-api-analytics-review`。
- 审核基线：`8c05228c77c262a9041e0f4c78d467819ba6efb2`（与审核时 `origin/main` 一致）。
- 复审范围：UI-P6 合同、后端 analytics/finance/integrations/lifecycle/workflow/reports 权限与接口实现、前端 API 与页面、自动化测试、构建、Docker/RPA JSON 及安全边界。
- 本报告为独立复审结果；未修改 `backend/`、`frontend/`、`rpa-agent/` 或业务配置，未处理工作区内无关 DOCX。

## 2. 复审结论

**CONDITIONAL_PASS**

未发现 P0；发现 3 项未关闭 P1：permission-specific `data_scope` 配置校验不完整、integrations PATCH 可将资源修改到授权范围外、前端会把非统一响应包装为成功并标记 `connected`。因此当前不允许 UI-P6 正式收尾，需整改后执行 UI-P6-ARCH-R2。

## 3. API合同一致性

- analytics、finance analytics、integrations、lifecycle、workflow、reports 的主要路径与 `ui_p6_api_analysis_contract.md` 一致。
- integrations 配置修改唯一使用 `PATCH /api/internal/integrations/configs/{id}/`，未发现集合级 PATCH。
- 成功、分页和错误响应的后端公共结构已沿用；现有测试覆盖 401/403/404/409/422 的主要业务场景。
- 前端 `request.js` 对合法统一响应可正常解析，但对缺失 `success/code/message/data` 的 HTTP 200 响应会伪装为 `success=true`，详见 P1-003。

## 4. analytics与数据质量

- overview、sales、inventory、metrics、aggregates 与 aggregate-mock 路径存在；查询按 tenant、permission 和 analytics dimension scope 过滤。
- 指标版本、来源摘要、质量状态、缺失值、快照一致性、过期/失败数据排除已有测试覆盖。
- 财务指标仍要求独立财务权限；analytics 只用于分析，不直接触发采购、改价、RPA 或资金动作。
- 浏览器 Mock 验证中，经营总览展示数据可信度、质量状态、口径版本、来源/更新时间和明确的分析边界。

## 5. finance只读与脱敏

- `/api/finance/analytics/overview|reconciliation|exceptions/` 保持财务独立权限和 tenant 过滤。
- 返回中声明 `read_only=true`、`fund_action_available=false`；账号掩码和只读审计已实现。
- 浏览器 Mock 验证只展示掩码金额/账号，不存在付款、转账、提现或自动确认对账按钮。
- platform/currency scope 的正常过滤已有测试；非法 scope 值的异常转换仍受 P1-001 影响。

## 6. integrations与平台边界

- 配置响应不返回明文凭据，生产 provider 默认未配置，production 验证受控；页面只提供 Sandbox 验证和禁用操作。
- 未发现真实平台 HTTP 调用、真实连接按钮或生产启用能力；映射状态保持 `pending`。
- 创建配置和同步任务会校验请求体 scope。
- 配置详情 PATCH 只在读取旧对象时校验 scope，保存新 `platform` 后没有重新校验，实测授权仅含 `platforms=[mock]` 的用户可将配置改为 `other` 并获得 200，详见 P1-002。

## 7. lifecycle、workflow与高风险边界

- API/RPA 来源只生成建议；生命周期确认/拒绝、审批和异常动作走后端 permission-specific scope 与状态机。
- 清仓申请页面明确只进入审批流，不改变商品状态、不改价、不下架、不触发采购或 RPA。
- 浏览器 Mock 验证仅出现“创建Mock申请”，未发现自动清仓、停售、归档、改价或真实 RPA 动作。
- 工作流审计不可修改/删除及 tenant 保护语义的回归测试通过。

## 8. reports导出与审计

- `/api/report/catalog/`、`exports/`、详情和 download 路径保持 reports 权限、tenant/data_scope、来源权限交集、脱敏及审计边界。
- 下载失败、拒绝和成功授权均有审计；审计记录不可更新或删除，父对象/tenant 删除保护测试通过。
- 导出仅生成 placeholder 引用，不产生真实敏感测试文件；external/RPA 无权访问内部导出。

## 9. tenant、permission与data_scope

- 现有正常场景覆盖 tenant 隔离、internal/external/RPA/finance 权限边界和各动作 permission 独立校验。
- `ALL` scope 语义和无适用 scope 的拒绝路径已实现。
- 通用 scope 解析会忽略同时存在的未知 key；各模块也未统一校验正整数、非空字符串和 ISO 4217 等值格式。定向探针结果：
  - `{"platforms":["mock"],"unexpected":["x"]}` 被接受为 `{"platforms":["mock"]}`；
  - `{"integration_config_ids":["not-an-id"]}` 触发 Python `ValueError`，未按合同返回 `403 DATA_SCOPE_INVALID`。
- 上述行为不满足“非法 key 或非法值返回 403”的冻结合同，详见 P1-001。

## 10. 前端状态与权限

- 路由、菜单和动作按钮按后端 permission 显示；finance、integrations、reports 和高风险动作未由前端替代后端权限判断。
- Mock、pending、connected、degraded 状态已区分；UI-P6 integrations/finance 等尚未完成 Pilot 联调的端点保持 pending/mock。
- 但 `normalizeApiResponse()` 会把任意非统一 HTTP 200 payload 包装为成功，随后 `requestApi()` 写入 `api_status=connected`。实际探针输入 `{legacy_payload:true}` 得到 `success=true/code=OK/api_status` 成功链路，违反统一响应和连接状态证据要求，详见 P1-003。

## 11. 测试、构建与浏览器证据

- `python manage.py check`：通过，0 issues。
- `python manage.py makemigrations --check --dry-run`：通过，No changes detected。
- 后端 UI-P6 相关定向 pytest：84 passed，229 deselected。
- 后端全量 pytest：313 passed。
- `npm ci`：成功，审计为 0 vulnerabilities。
- 前端测试：8 files、98 tests passed，其中 UI-P6 7 tests passed。
- `npm run build`：成功，1934 modules transformed。
- Docker Compose 配置：解析通过；因未注入本地秘密环境变量出现空值 warning，不影响静态解析结论。
- RPA JSON：16 个文件全部有效。
- 浏览器：在 Mock 模式复核经营总览、财务分析、接入配置详情和清仓申请；桌面页面无横向溢出，关键只读/掩码/高风险提示存在。
- 受控 Pilot 的真实 JWT/API 联调未执行；原因是本次独立复审环境未提供受控 Pilot 凭据，相关端点仍保持 pending/mock，未伪造 connected。
- 本轮移动视口覆盖未独立复现：浏览器 viewport override 未生效并保持 1280px；不影响本轮三项合同 P1 结论。

## 12. 安全扫描

- 未发现真实 `.env`、私钥、证书、API Key、Token、Cookie、Session 或生产数据库密码被跟踪。
- 扫描命中的 Redis 密码仅位于 `env.pilot.example`，值为 `change-me-redis-password`，属于明确示例值。
- 未发现真实 BigSeller、Shopee、TikTok/TK、银行或支付接入。
- 未发现真实供应商、订单、银行或财务业务数据。
- `frontend/dist/`、`frontend/node_modules/` 均被忽略；`git diff --check` 通过。

## 13. P0

无。

## 14. P1

| 编号 | 问题 | 证据 | 整改验收标准 |
|---|---|---|---|
| UI-P6-R1-P1-001 | permission-specific `data_scope` schema 校验不完整，未知 key 被忽略，非法 ID 值可抛出 `ValueError` 而非 403。 | `backend/apps/permissions/ui_p6_scopes.py:10-35,115-130`；独立探针输出 unknown key accepted、invalid ID `ValueError`。 | 每个 permission 只接受合同声明的 key；未知 key、空值、类型错误、非正整数、非法 currency/resource/report type 均稳定返回 `403 DATA_SCOPE_INVALID`，并补齐各模块负向测试。 |
| UI-P6-R1-P1-002 | integrations 配置 PATCH 可把已授权对象修改到授权平台之外。 | `backend/apps/integrations/views.py:144-166` 保存前未按 validated data 再校验；隔离数据库实测 `mock -> other` 返回 200/OK 且成功落库。 | PATCH 对所有可改变 scope 归属的字段执行后置 scope 校验；越权返回 403 且数据库不变，补充回归测试。 |
| UI-P6-R1-P1-003 | 前端会把非统一 HTTP 200 响应包装为成功并标记 connected。 | `frontend/src/api/request.js:24-41,91-95,123-126`；Vite 模块探针将 `{legacy_payload:true}` 转为 `success=true/code=OK`。 | 非统一 envelope 必须返回受控协议错误/降级，不得标 connected；仅合法统一响应且实际调用成功可标 connected，并补充 malformed response 测试。 |

## 15. P2

- `npm ci` 提示 `esbuild`、`vue-demi` install scripts 尚未列入 allow-scripts 审批清单；当前安装、测试和构建均通过，建议在依赖治理中固化。
- Rollup 对 `@vueuse/core` 第三方 PURE 注释给出非阻断 warning。
- 受控 Pilot 真实 JWT/API、移动视口和浏览器认证态 E2E 尚需在 R2/收尾前补充或引用可复现证据；当前状态保持 pending/mock，不构成虚假 connected。

## 16. 是否允许UI-P6正式收尾

**不允许。**

应先关闭 UI-P6-R1-P1-001 至 UI-P6-R1-P1-003，补齐对应负向测试，再执行独立 UI-P6-ARCH-R2。现有通过项可保留，不需要扩大业务范围，也不得借整改接入真实平台或启用高风险自动化。
