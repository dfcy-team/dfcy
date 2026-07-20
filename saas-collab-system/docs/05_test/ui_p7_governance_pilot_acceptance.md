# UI-P7 治理与受控试点验收清单

## 1. 合同与范围

- [ ] 页面、API、权限、data_scope、状态机和审计合同已通过独立前审。
- [ ] 实施分支基于 UI-P6 合并后的最新 main。
- [ ] 未修改 `rpa-agent/` 真实执行脚本或 `docs/04_rpa/` 既有协议。
- [ ] 未接入真实平台、真实 AI provider、银行、支付或真实凭据。

## 2. 页面与状态

- [ ] API治理、智能体占位、试点就绪、拓扑、恢复、发布和容量页面均登记路由合同。
- [ ] 未登记路由默认拒绝；详情继承最长匹配资源权限。
- [ ] 页面覆盖 loading、empty、error、401、403、404、409、422、degraded、offline 和 stale。
- [ ] 桌面与窄屏无重叠、横向溢出或不可操作按钮。
- [ ] pending/mock/sandbox/connected/degraded/disabled/stale 均有证据，不以 HTTP 200 伪造 connected。
- [ ] 初始全部 UI-P7 能力为 pending；planned mock 仅在 handler、固定 demo 数据和自动化证据齐备后改为 mock。

## 3. API治理与智能体占位

- [ ] 合同目录按 module、status、version、tenant/system scope 过滤。
- [ ] 同一能力只有一个现行路径；兼容别名有 owner 和废弃日期。
- [ ] Mock合同检查不请求真实外部平台。
- [ ] 智能体占位不读取真实凭据、不调用外部模型、不使用网络工具、不写业务数据库。
- [ ] Mock建议明确 `human_confirmation_required=true`，不能触发高风险动作。
- [ ] 每个端点仅接受合同列出的查询参数、请求字段和枚举；未知字段返回 400。
- [ ] ApiContractDetail 的 RequestFieldSpec、ResponseFieldSpec、ApiErrorSpec、ContractChangeEntry 字段、排序、null/空数组和组合规则逐项通过schema测试。
- [ ] 四类 item schema 对每个字段验证 required/nullable/type/enum/长度或数值约束；未知字段返回 `422 SCHEMA_FIELD_UNKNOWN`。
- [ ] 列表 page 默认1、page_size默认20且最大100；超过上限返回400，不静默截断。
- [ ] planned mock 在实现前不可被映射、页面或 capability 状态标成 mock/connected。

## 4. tenant、权限与data_scope

- [ ] external、RPA 和普通 internal 无精确权限时均被拒绝。
- [ ] `governance.*`、`pilot.*` 各动作使用独立权限，不以 view 权限替代写动作。
- [ ] 未知 scope key、空值、非法 ID/枚举返回 `403 DATA_SCOPE_INVALID`。
- [ ] 列表超 scope 返回空分页；详情和审计按 ID 越权返回 404；请求体越权返回 403。
- [ ] system scope 不泄露 tenant 业务明细，tenant 引用已脱敏。

## 5. 双主机与网络

- [ ] 数据库主机仅开放应用主机到 MySQL 的受控路径，MySQL 不暴露公网。
- [ ] Redis、Celery broker、Docker socket、Django 后端端口和管理端口不暴露公网。
- [ ] 前端只经 Nginx 访问后端；Host、CORS 和 allowed hosts 使用试点配置。
- [ ] 页面和日志不显示完整主机 IP、连接串、密码或代理凭据。
- [ ] topology verify-mock 只验证示例结构，不修改防火墙或主机。

## 6. 备份恢复与回滚

- [ ] 恢复计划具备 RPO、RTO、审批、备份摘要、校验和审计引用。
- [ ] 实际恢复在受控主机人工执行，Web API 只记录结果。
- [ ] 恢复演练验证 tenant 数据、权限、迁移、审计和关键页面健康。
- [ ] 发布计划关联不可变 commit/tag、数据库兼容性、观察窗口、停止条件和回滚点。
- [ ] 回滚不使用未经批准的 `reset --hard`、数据删除或卷删除。
- [ ] 失败、manual_required、cancelled 和 rolled_back 路径均有回归测试。
- [ ] recovery/release 的 submit-review、approve、reject、schedule、start、resume、cancel 和结果动作逐项符合合法迁移矩阵。
- [ ] 创建人与审批人分离；review/record/rollback 各自使用 exact permission 和 permission-specific data_scope。
- [ ] 通用 PUT/PATCH/DELETE、serializer status写入、model直接save、QuerySet update/delete、admin和批处理均不能绕过状态服务。
- [ ] 非法from/to、版本冲突、幂等冲突、门禁过期和审批失效分别返回合同约定的409/422。
- [ ] 发布 manual_required 按 manual_context 区分：`resume`仅允许release上下文和record权限，`resume-rollback`仅允许rollback上下文和rollback权限。
- [ ] 回滚必须先调用approve-rollback并保存独立rollback_approval_ref；原发布审批不自动授权回滚。
- [ ] rollback approval 保存批准人、批准时间和失效时间；不匹配、过期、替换、离开/重新进入 rollback_required 以及 commit/tag/rollback_point 变化均按合同失效并留审计。
- [ ] 过期批准返回 `422 ROLLBACK_APPROVAL_EXPIRED`，不匹配批准返回 `422 ROLLBACK_APPROVAL_INVALID`；失败请求不得改变计划状态。
- [ ] 回滚批准人不得是创建人、发布审批人或回滚结果记录人；权限/data_scope不足分别覆盖403/404。
- [ ] 成功与失败状态动作均生成不可修改、不可删除且tenant删除受保护的审计事件。

## 7. 低风险灰度与容量

- [ ] 灰度范围仅限 demo tenant 和只读/低风险能力。
- [ ] 自动采购、改价、库存、清仓、上下架、RPA 和资金动作全部排除。
- [ ] 容量摘要包含采样时间、来源、阈值、质量和 stale 标记。
- [ ] 缺失数据不补零；跨环境、跨 tenant 不由前端拼接。
- [ ] 达到停止条件后只标记阻断/回滚需要，不由页面直接执行回滚。

## 8. 自动化与构建

```bash
cd backend
python manage.py check
python manage.py makemigrations --check --dry-run
pytest -q tests -k "governance or pilot or readiness or recovery or release or capacity or data_scope"
pytest -q

cd ../frontend
npm ci
npm test -- --run
npm run build
```

- [ ] 后端覆盖 400/401/403/404/409/422、tenant/system scope、权限和状态机。
- [ ] 后端逐端点覆盖必填/可选字段、类型、枚举、nullability、Idempotency-Key、version和禁止敏感字段。
- [ ] 前端覆盖路由、按钮、统一响应、分页、错误、stale 和 capability 状态。
- [ ] CI 不依赖真实平台、模型、银行或支付密钥。

## 9. 系统、安全与E2E

- [ ] `docker compose config -q` 与试点 Compose 静态解析通过。
- [ ] 16 个 RPA JSON 和既有 RPA 协议未被破坏。
- [ ] 固定密钥、私钥、证书、`.env`、真实域名和真实数据扫描无阻断项。
- [ ] `frontend/dist`、`node_modules`、备份文件和运行日志未跟踪。
- [ ] 使用受控试点用户执行登录、刷新、权限切换、关键页面和 API 浏览器 E2E。
- [ ] 未执行项目明确禁止的真实平台、真实 RPA 或资金动作。

## 10. 通过标准

- P0：无。
- P1：无。
- P2：仅可保留有责任人、期限和不影响安全/恢复能力的观察项。
- 合同前审 PASS 只允许进入实现；实现复审和发布审核 PASS 后才允许 UI-P7 正式收尾。
