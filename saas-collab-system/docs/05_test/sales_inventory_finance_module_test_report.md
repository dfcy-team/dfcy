# 销售库存财务对账模块测试报告

## 自动化结果

| 检查 | 结果 | 证据摘要 |
|---|---|---|
| 后端全量 pytest | PASS | 410 passed |
| 模块合同测试 | PASS | 分页、空数据、401、403、404、409、422、tenant、scope、幂等和审计均覆盖 |
| Django check | PASS | 0 issues |
| 迁移一致性 | PASS | No changes detected |
| 前端 Vitest | PASS | 单 worker 全量复跑：12 个测试文件、160 个测试全部通过；默认并行 worker 曾触发本机 Node OOM |
| 前端 build | PASS | 第三方 PURE 注释告警，不阻断 |
| npm audit | PASS | 0 vulnerabilities |
| Sandbox fixture | PASS | 两 tenant、两平台、两币种、三类库存、匹配/差异 |
| Local Sandbox profile | BLOCKED | `auth.docker.io:443` 连接超时，基础镜像无法拉取 |
| 浏览器 Mock 冒烟 | PASS | 库存预警、匹配列表、异常列表和匹配详情均渲染成功，控制台无错误 |

## 安全负向覆盖

- 普通 internal、external、RPA 和未登录用户不能使用财务敏感接口。
- `finance.view`、`finance.reconcile` 和 `finance.exception.handle` 不可互相替代。
- 跨 tenant、超 platform/currency scope 和超资源 scope 请求被拒绝或按详情隐藏为 404。
- 无关角色的 ALL scope 不扩大 alerts/replenishment 的 exact permission scope。
- 重复动作返回 409；非法合成平台输入返回 422。
- 银行账号仅返回掩码，审计内容经过敏感数据清洗。
- 模型保存、批量更新和非法批量创建不能绕过对账状态服务。

## 待补证据

- 镜像注册表网络恢复后运行 `sandbox.ps1 verify sales-inventory-finance-reconciliation`。
- 使用 Local Sandbox JWT 复验成功响应、权限拒绝、tenant 和 permission-specific scope。
- 合并前同步最新 main 并运行 `sandbox.ps1 verify integration`。
