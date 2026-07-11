# P3-A-004 商品生命周期复盘服务变更日志

## 交付

- 新增 `ProductLifecycleReview` 与 `ProductLifecycleDecision`，支持周/月复盘周期、来源指标、规则版本、建议、置信度、人工确认/拒绝和审计证据。
- 生命周期覆盖新品观察、成长、稳定、滞销观察、清仓候选、清仓、停售和归档。
- 新增列表、详情、Mock 评估、确认、拒绝和决策列表接口，并应用 tenant、DataScope 和动作级权限。
- 服务层锁定复盘与商品目标，拒绝非法、陈旧和重复流转；普通保存和 QuerySet 更新不能绕过人工决策服务。

## 安全边界

- API、RPA readback 和 Mock 数据只能生成建议。
- 清仓、停售和归档确认需要独立高风险权限。
- 确认只写决策与审计，不自动改价、不上下架、不触发 RPA，也不直接修改商品业务状态。
- external 与 RPA 用户不能访问 internal 生命周期接口。

## 验证

- P3-A-004 定向测试：`10 passed`。
- 全量 pytest：`203 passed`。
- Django check：通过，`0 issues`。
- 迁移一致性：通过，`No changes detected`。
- 全新临时数据库迁移与权限目录检查：通过，`Permission catalog is complete`。
- 安全文件扫描、Docker Compose 配置与 `git diff --check`：通过。
