# UI-P6 API接入与分析复盘验收清单

## 1. 准入条件

- UI-P6 范围、API、权限和 data_scope 合同通过独立架构复审。
- 基于最新 `main` 实施，工作区无审核外修改。
- 不使用真实平台、真实银行、真实凭据或真实业务数据。
- Mock、pending、sandbox、connected、degraded、disabled 状态均有可验证证据。

## 2. 页面与交互

- [ ] 经营总览、销售、库存、财务、生命周期、清仓申请、接入中心和报表页面均可从授权菜单进入。
- [ ] 未登记路由默认拒绝，详情路由继承资源权限。
- [ ] 每页覆盖 loading、empty、error、401、403、404、409、422、degraded 和 offline。
- [ ] 桌面和窄屏无文本重叠、横向溢出或不可操作控件。
- [ ] 筛选、分页、刷新、钻取和返回保持上下文。
- [ ] 数据更新时间、口径版本、质量状态和缺失值清晰可见。

## 3. 路径唯一性

- [ ] 总映射不再把 `suggestions`、`lifecycle/history`、未分资源 `alerts`、`config/items` 或 `config/versions` 作为现行后端路径。
- [ ] integrations 配置列表/创建只使用 `GET/POST /api/internal/integrations/configs/`。
- [ ] integrations 配置详情/修改只使用 `GET/PATCH /api/internal/integrations/configs/{id}/`，集合级 PATCH 返回 405 或不存在。
- [ ] disable、verify、rotate 分别使用 `{id}/disable/`、`{id}/verify/`、`{id}/rotate/`。
- [ ] 同步任务和运行只使用 `sync-jobs`、`sync-runs`，不再使用 `sync-tasks`、`sync-logs`。

## 4. analytics逐端点合同

- [ ] overview、sales、inventory 分别验证合同允许的查询参数；未知参数返回 400。
- [ ] `page_size > 100` 返回 400，不静默截断。
- [ ] 三个聚合端点统一返回 `count/next/previous/results/api_status/quality`。
- [ ] `results[]` 包含 metric_code、metric_name、value、unit、时间范围、dimensions、updated_at、metric_version、quality_status、is_missing、source_summary。
- [ ] overview/sales/inventory 的 `metrics/trend` 与对应端点字段合同一致。
- [ ] metrics 列表/详情和 aggregates 列表/详情使用各自固定字段，不混用页面聚合字段。
- [ ] aggregate-mock 只生成 Mock 聚合结果，不触发采购、RPA、商品状态或资金动作。
- [ ] 缺失值使用 `null + is_missing=true`，不改写为 0。

## 5. finance analytics逐端点合同

- [ ] overview、reconciliation、exceptions 只接受合同列出的分页、时间、platform、currency 和 status 参数。
- [ ] 三个端点统一使用分页结构，并返回 `read_only=true`、`fund_action_available=false`。
- [ ] overview 逐项验证金额、差异、异常数、account_mask、quality_status、metrics 和 trend。
- [ ] reconciliation 逐项验证 status、match_count、matched_amount、total_difference、currency、quality_status。
- [ ] exceptions 逐项验证 exception_type、status、exception_count、total_difference、currency、quality_status。
- [ ] 不再返回或消费 `currencies/statuses/exceptions/items` 顶层变体。
- [ ] 完整账号、付款、转账、提现和自动确认入口均不存在。

## 6. permission-specific data_scope

- [ ] 每个端点按 exact permission 获取 scope，不使用全局合并 scope 替代。
- [ ] `ALL` 仅放行当前 tenant；跨 tenant 始终返回 404。
- [ ] 无 scope、空 scope、非法 key 或非法值返回 403。
- [ ] 未冻结归属模型的 `OWN/DEPARTMENT` 返回 `403 DATA_SCOPE_UNSUPPORTED`。
- [ ] 多条 CUSTOM scope 记录按 OR，同一记录不同 key 按 AND。
- [ ] 合法但超 scope 的列表筛选返回 200 空分页；详情/动作返回 404；请求体越权维度返回 403。
- [ ] `analytics.view` 与 `analytics.calculate` 分别校验 `analytics_dimensions`，允许 key 仅为 platform/store_id/country/product_id/sku_id/warehouse_id。
- [ ] lifecycle 的 view/evaluate/confirm/high_risk_confirm 分别校验 `spu_ids/sku_ids`；高风险操作取 confirm 与 high_risk_confirm 交集。
- [ ] workflow 的 view/submit/review 分别校验 `approval_types=clearance`。
- [ ] integrations 的 view/manage/rotate/run 分别校验 `platforms/integration_config_ids/resource_types`。
- [ ] `finance.view` 校验 `platforms/currencies` 且保持财务独立授权。
- [ ] reports 的 view/export/download 分别校验 `report_types` 与来源资源 scope 交集。
- [ ] external 与 RPA 用户不能访问 UI-P6 internal/finance/report 接口。

## 7. 高风险边界

- [ ] 生命周期普通确认和高风险确认权限分离。
- [ ] 清仓、停售、归档、改价不能由分析页直接执行。
- [ ] 清仓Mock申请不修改商品、价格、刊登、采购或RPA状态。
- [ ] 补货和库存风险只产生建议，不创建采购订单。
- [ ] API同步仅运行 run-mock，production 验证和执行被拒绝。
- [ ] 财务页面无付款、转账、提现和自动确认对账入口。
- [ ] 报表导出和下载执行权限、数据范围、脱敏和不可删除审计。

## 8. 建议执行命令

### 后端

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q tests -k "analytics or lifecycle or integration or finance or report or workflow or data_scope"
pytest -q
```

必须记录逐端点 schema、tenant、exact permission data_scope、401、403、404、409、422、财务独立权限、清仓审批范围、凭据脱敏和导出审计测试结果。

### 前端

```bash
cd frontend
npm ci
npm test -- --run
npm run build
```

必须新增 UI-P6 路由、动作权限、逐端点字段、统一分页、错误展示、Mock/API切换、敏感字段和高风险边界定向测试。

### 系统与安全

```bash
docker compose config -q
git diff --check
git ls-files frontend/dist frontend/node_modules
```

扫描 `/api/rpa/`、`/admin/`、明文凭据、真实平台域名、真实账号/订单/财务数据和自动高风险动作。未执行项必须记录原因，不得伪造。

## 9. 浏览器验收

使用真实本项目登录会话在受控 Pilot 环境执行桌面与窄屏截图、网络请求、空数据、慢请求、断网和权限切换检查。不得连接真实 BigSeller、Shopee、TikTok/TK、银行或支付平台。

## 10. 通过标准

- P0：无。
- P1：无。
- P2：仅允许有责任人、后续计划且不影响安全和主流程的观察项。
- 只有本清单通过并完成独立架构复审，UI-P6 才可进入实施。
