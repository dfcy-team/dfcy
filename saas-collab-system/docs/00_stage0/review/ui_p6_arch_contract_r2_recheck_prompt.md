# UI-P6-ARCH-CONTRACT-R2 独立复审提示

## 1. 复审性质

只审核合同整改，不修改业务代码或合同内容。输出文件仅为：

`docs/00_stage0/review/ui_p6_arch_contract_r2_recheck.md`

## 2. 复审依据

- `docs/00_stage0/review/ui_p6_arch_contract_recheck.md`
- `docs/00_stage0/review/ui_p6_contract_p1_fix_change_log.md`
- `docs/00_stage0/frontend_api_mapping.md`
- `docs/03_api/phase3_api_contract_final.md`
- `docs/03_api/ui_p6_api_analysis_contract.md`
- `docs/05_test/ui_p6_api_analysis_acceptance.md`
- 后端现有 URL、serializer、permission 与 data_scope 实现
- 前端现有 API 封装、路由和页面字段消费

## 3. 原P1定向复审

### P1-001 路径唯一性

- 总映射不得再把 `suggestions`、`lifecycle/history`、未分资源 alerts、`config/items`、`config/versions` 作为现行路径。
- integrations 的 `PATCH` 必须唯一为 `/api/internal/integrations/configs/{id}/`。
- disable、verify、rotate、sync-jobs、sync-runs 必须各有唯一方法与路径。
- 不得存在未验证却标记为 `connected` 的 UI-P6 能力。

### P1-002 逐端点schema

- analytics overview/sales/inventory/metrics/aggregates 的查询参数、分页、结果字段和质量字段必须逐端点明确。
- finance overview/reconciliation/exceptions 必须逐端点明确，保持 `read_only=true`、`fund_action_available=false`。
- 缺失值、旧字段退役、未知参数、分页上限和 400/401/403/404/409/422 必须可测试。
- 前后端现状若尚未符合合同，应明确列为后续实施项，不得误判已完成联调。

### P1-003 permission-specific data_scope

- 必须明确 exact permission 取 scope，不使用全局合并 scope 替代。
- analytics、lifecycle、workflow、integrations、finance、reports 的 scope key 必须唯一且可实现。
- ALL、CUSTOM、OWN、DEPARTMENT、无scope、空scope、非法scope语义必须完整。
- CUSTOM 的记录间 OR、记录内不同 key AND 必须明确。
- 列表、详情、动作、请求体和跨tenant越权响应必须明确。

## 4. 安全与范围

确认整改仅修改允许文档，无业务代码、真实密钥、真实平台配置、真实业务数据或高风险自动化。

## 5. 报告结构

# UI-P6-ARCH-CONTRACT-R2 复审报告

## 1. 复审对象
## 2. 复审结论
结论仅允许 `PASS`、`CONDITIONAL_PASS`、`FAIL`。
## 3. 原P1关闭情况
## 4. 路径唯一性
## 5. 逐端点schema
## 6. permission-specific data_scope
## 7. 验收可执行性
## 8. 安全与修改范围
## 9. P0
## 10. P1
## 11. P2
## 12. 是否允许进入UI-P6实施

判断规则：有 P0 为 `FAIL`；无 P0 但有未关闭 P1 为 `CONDITIONAL_PASS`；无 P0/P1 为 `PASS`。
