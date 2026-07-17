# UI-P6-ARCH-R2 API接入与分析复盘整改复审报告

## 1. 复审对象

- 任务：UI-P6-ARCH-R2 独立架构复审。
- 分支：`feature/ui-p6-api-analytics-review`。
- 复审日期：2026-07-17。
- 原报告：`docs/00_stage0/review/ui_p6_arch_r1_recheck.md`。
- 整改记录：`docs/00_stage0/review/ui_p6_r1_p1_fix_change_log.md`。
- 复审范围：三项原 P1 的实现、负向测试、全量回归、构建、安全和系统边界。
- 本次复审只新增本报告，未修改 `backend/`、`frontend/`、`rpa-agent/` 或业务配置；工作区中的无关 DOCX 未处理。

## 2. 复审结论

**PASS**

未发现 P0 或未关闭 P1。UI-P6-R1-P1-001 至 UI-P6-R1-P1-003 均已通过代码检查、独立负向探针和自动化回归验证，可关闭。

## 3. 原P1关闭情况

| 原P1编号 | 问题 | 是否关闭 | 独立证据 | 备注 |
|---|---|---|---|---|
| UI-P6-R1-P1-001 | `data_scope` 未严格拒绝未知 key 和非法值 | 是 | `backend/apps/permissions/ui_p6_scopes.py`；`backend/tests/test_ui_p6_data_scope_validation.py`；独立探针分别得到 `403 DATA_SCOPE_INVALID` | permission/module 白名单、类型、正整数、非空字符串、currency 和 report type 均执行严格校验 |
| UI-P6-R1-P1-002 | integrations PATCH 可将配置修改到授权平台范围外 | 是 | `backend/apps/integrations/views.py`；`backend/tests/test_phase2_integrations_secure_config.py`；隔离数据库探针得到 `403 DATA_SCOPE_FORBIDDEN` | 保存前按候选 platform 和当前 config id 重新校验，拒绝后数据库值保持不变 |
| UI-P6-R1-P1-003 | 非统一 HTTP 200 响应会被包装为成功并标记 connected | 是 | `frontend/src/api/request.js`；`frontend/tests/ui-p6-api-analysis.spec.js`；模块探针返回 `success=false/code=INVALID_API_RESPONSE/data=null` | 仅合法统一响应且 `success=true` 才允许写入 connected |

## 4. data_scope严格校验复审

- scope 顶层仅接受当前 permission/module 声明的 key；未知 key 统一拒绝。
- analytics、lifecycle、integrations、finance 和 reports 的 scope 值均执行结构与类型校验。
- 非法 ID 不再泄漏 Python `ValueError`，统一转换为 `403 DATA_SCOPE_INVALID`。
- `ALL` 与具体值列表语义保持明确；非法空值、错误类型、非法 currency/resource/report type 均不能进入查询或动作。
- 独立隔离数据库探针结果：未知 key 为 `403 DATA_SCOPE_INVALID`，非法值为 `403 DATA_SCOPE_INVALID`。

## 5. integrations PATCH复审

- PATCH 在保存前读取 serializer 候选 platform，并与当前 config id 一并执行 `integrations.manage` scope 校验。
- 仅获授权 `platforms=[mock]` 的用户尝试将配置改为其他平台时返回 `403 DATA_SCOPE_FORBIDDEN`。
- 越权请求未写入数据库，未发现先保存后校验或跨授权平台迁移资源的路径。
- production provider 仍默认禁用，未增加真实平台连接能力。

## 6. 前端统一响应与connected复审

- `isApiEnvelope()` 要求响应同时具备合法的 `success`、`code`、`message` 和 `data` 合同。
- HTTP 200 但 envelope 非法时返回受控协议错误 `INVALID_API_RESPONSE`，不会伪造 `OK`。
- `withApiStatus()` 只对 `success=true` 的合法响应写入 API 状态；协议错误不会被标记为 connected。
- 独立模块探针输入非统一 payload 后得到：`success=false`、`code=INVALID_API_RESPONSE`、`data=null`、`protocol_error=true`。

## 7. 测试、构建与系统检查

- `python manage.py check`：通过，0 issues。
- `python manage.py makemigrations --check --dry-run`：通过，No changes detected。
- 后端三项 P1 定向测试：18 passed。
- 后端全量 pytest：322 passed，耗时 33.51s。
- 前端合同与 UI-P6 定向测试：34 passed。
- 前端全量测试：8 files、99 passed。
- `npm run build`：通过，1934 modules transformed。
- Docker Compose 静态配置：可解析；未注入本地私密环境变量产生空值 warning，不阻断本次代码复审。
- RPA JSON 校验：16 个 JSON 全部有效。
- `git diff --check`：通过；仅有工作区换行符提示，无空白错误。

## 8. 安全与边界复审

- 固定格式密钥扫描未发现真实 API Key、Token、私钥或证书。
- 未发现真实 BigSeller、Shopee、TikTok/TK、银行或支付平台连接。
- 未发现真实账号、供应商、订单、财务或银行业务数据。
- `frontend/dist/` 和 `frontend/node_modules/` 均被 `.gitignore` 正确忽略，未作为交付文件跟踪。
- 未放开自动采购、自动清仓、停售、归档、改价、真实 RPA 或付款、转账、提现。
- tenant、permission-specific `data_scope`、财务独立授权和后端可信权限判断边界保持有效。

## 9. P0

无。

## 10. P1

无。R1 的三项 P1 全部关闭。

## 11. P2

- Rollup 对 `@vueuse/core` 第三方 PURE 注释给出非阻断 warning；生产构建成功。
- Docker Compose 在本地未注入私密环境变量时存在空值 warning，应在受控部署环境通过环境文件注入示例之外的真实运行值，且不得提交仓库。
- 受控 Pilot 的真实 JWT/API 和浏览器认证态 E2E 本次未执行；相关未验证端点继续保持 pending/mock，不得据此标记 connected，也不影响三项 P1 的关闭结论。

## 12. 是否允许UI-P6正式收尾

**允许。**

UI-P6 已达到正式收尾条件，可以进入提交、远端 CI 和 PR 流程。该结论不授权真实平台接入或高风险自动化；此类能力仍须单独安全评审、受控试点和明确审批。
