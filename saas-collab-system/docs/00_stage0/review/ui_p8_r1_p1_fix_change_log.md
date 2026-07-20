# UI-P8 R1 P1 整改变更日志

## 1. 整改目标

本次定向关闭 UI-P8-ARCH-R1 提出的六项 P1，不接入真实平台，不启用生产发布或高风险自动化。

## 2. P1 整改情况

| P1 | 整改结果 | 主要证据 | 状态 |
|---|---|---|---|
| 财务安全评审 PATCH 与受控引用校验 | PATCH 同时校验财务 scope、原/目标环境、受控 target alias 和 evidence reference；引用按 tenant + environment 登记 | `backend/apps/pilot/ui_p8_services.py`、`backend/apps/pilot/models.py`、迁移 `0005`、后端专项测试 | 已整改，待独立 R2 |
| 准入批准时证据重新验证 | 批准时重新读取证据并核对类型、ID、版本、状态、摘要和有效期；stale 或阻断证据返回 409 | `backend/apps/pilot/ui_p8_services.py`、`test_entry_approval_revalidates_expired_evidence` | 已整改，待独立 R2 |
| 403/422/409 失败审计 | 已认证失败请求写入脱敏不可变审计，状态码映射统一错误码，不覆盖原 API 响应 | `backend/apps/pilot/ui_p8_views.py`、`audit_failure()`、失败审计测试 | 已整改，待独立 R2 |
| 模型直接创建绕过状态机 | 新实例 `save()`/`objects.create()` 必须具备服务层写标记，QuerySet/bulk 防护保持有效 | `backend/apps/pilot/models.py`、直接创建拒绝测试 | 已整改，待独立 R2 |
| 前端分页、筛选、PATCH 与组件状态矩阵 | 增加环境/状态筛选、page/page_size、草稿 PATCH；挂载测试覆盖 loading/empty/401/403/404/409/422/stale/offline、逐 action 权限与成功 action 重载 | `P8WorkflowWorkspace.vue`、`pilot.js`、前端专项 `23 passed` | 已整改，待独立 R2 |
| 接口映射、JWT E2E 和远端 CI 证据 | 总映射已更新；真实 JWT 下 GET/POST/PATCH 通过；远端 CI 明确保留为 PR 后门禁 | `frontend_api_mapping.md`、`ui_p8_jwt_e2e_result.md` | 本地证据已完成；远端 CI 待 PR |

## 3. 实际验证

- Django check：通过。
- migration 一致性：通过，`No changes detected`。
- UI-P8 后端专项：`19 passed`。
- 后端全量：`397 passed`。
- UI-P8 前端专项：`23 passed`。
- 前端全量：`153 passed`。
- 前端 build：通过。
- 真实 JWT 浏览器 E2E：login/me、GET、POST、PATCH 通过，版本由 1 更新为 2。
- 远端 CI：尚未执行，必须在提交分支并创建 PR 后确认。

## 4. 安全确认

- 未提交真实 `.env`、凭据、平台配置或业务数据。
- 未连接真实 BigSeller、Shopee、TikTok/TK、银行、支付或 RPA。
- 未启用真实部署、恢复、回滚、采购、清仓、改价或资金动作。
- 无关 DOCX、`docs/00_stage0/architecture/` 和 `docs/04_rpa/协同开发下发/` 不属于本次整改范围，后续提交必须排除。

## 5. 待复审事项

由独立 `UI-P8-ARCH-R2` 重新执行代码、测试、浏览器和安全核验。远端 CI 未成功前，不得将该门禁记录为已关闭，也不得正式收尾。
