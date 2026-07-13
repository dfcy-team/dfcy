# P3-A-007 报表、财务分析与导出审计接口变更日志

## 交付

- 新增 `ReportExportRequest` 与不可变 `ReportExportAuditLog`，记录 tenant、请求人、DataScope 快照、筛选条件、行数限制、占位文件引用和访问审计。
- 新增报表目录、导出创建、导出列表和导出详情接口；详情访问也记录审计。
- 新增财务概览、对账与异常只读聚合接口，全部使用独立 `finance.view` 权限并写财务访问审计。
- 新增 `reports.view` 与 `reports.export` 动作权限；财务导出还需要 `finance.export`。

## 安全边界

- 报表按 tenant、DataScope、报表类型权限和请求人范围过滤。
- 财务接口只返回按币种/状态聚合的数据及掩码，不返回完整账户信息。
- 导出不生成真实文件，只生成 `placeholder://report-export/<id>`；超过行数上限记录为 rejected。
- external 与 RPA 用户不能访问内部导出；没有下载真实文件的接口。
- 不执行付款、转账、提现或其他资金动作。

## 验证

- P3-A-007 与权限兼容定向测试：`12 passed`。
- 全量 pytest：`241 passed`。
- Django check：通过，`0 issues`。
- 迁移一致性：通过，`No changes detected`。
- 全新临时数据库迁移与权限目录检查：通过，`Permission catalog is complete`。
- 安全文件扫描、Docker Compose 配置与 `git diff --check`：通过。
