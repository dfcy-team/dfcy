# SCM-REQ-V3-R1 P1 整改报告

- 日期：2026-08-10
- 范围：`SCM-REQ-V3-R1-P1-001..005`
- 状态：`READY_FOR_P1_RECHECK`
- 约束：仅需求与映射文档；不授权业务代码、迁移或正式系统操作

## 1. 整改结果

| 问题 | 整改 | 证据 | 结果 |
| --- | --- | --- | --- |
| P1-001 源文件未冻结 | 增加 Source ID、字节、修改时间、SHA-256、UTF-8/NUL及源变更自动失效规则 | `scm_requirement_baseline_v3_full_scope.md` 第1章 | 已关闭，待复核 |
| P1-002 缺逐条ID | 新增网页/小程序稳定ID；小程序81条验收逐条 `MINI-AC-001..081` | `scm_requirement_v3_traceability_matrix.md` 第7-8章 | 已关闭，待复核 |
| P1-003 两源冲突无规则 | 冲突统一 `UNRESOLVED`，共享领域由映射合同冻结，禁止开发自选 | V3第1章、MAP-0 | 已关闭，待复核 |
| P1-004 路线/模式不唯一 | 冻结生产完成后采购决定路线；散货分 direct/groupage；柜货独立聚合 | `scm_requirement_v3_route_state_mapping_contract.md` 第1-3章 | 已关闭，待复核 |
| P1-005 状态无映射 | 冻结订单8态、发货5态、货柜9态、装箱审核派生状态和迁移原则 | MAP-0第4-9章 | 已关闭，待复核 |

## 2. 用户追加导航规则

新增 `WEB-NAV-001`：主系统一级菜单固定为：

`产品开发 -> 供应链协同 -> 多平台刊登`

已同步到：

- V3完整范围基线；
- V3追踪矩阵；
- `frontend/src/router/menu.js`；
- `frontend/tests/supply-flow-client.spec.js` 自动化断言。

菜单调整不改变 `supply.consolidation.view`、`supply.shipment.view` 权限和路由能力合同。

## 3. 决策边界

- 最新两份源需求仍是业务最高权威。
- 当前协同架构和安全门禁是实现约束，不缩减业务范围。
- `direct_dispatch` 与 `regional_groupage` 是散货下互斥模式，不再使用同一个含糊“散货”状态判断流程。
- 源状态映射为展示/派生状态时，客户端不得直接写入。
- Container 聚合尚未实现，MAP-0 不等同于代码完成。
- 本轮没有连接正式系统，没有数据库写入或迁移。

## 4. 复核门禁

快速复核应检查：

1. 两份源文件摘要与本机重新计算结果一致；
2. `MINI-AC-001..081` 连续、无重复、无缺号；
3. 网页4.1-4.16及5-12、小程序3-10均有稳定ID；
4. 路线合同不存在未命名的散货第三路径；
5. 四组状态明确权威源、派生关系和未知数据处理；
6. 菜单顺序测试通过；
7. 所有整改文件为UTF-8、无NUL且 `git diff --check` 通过。

复核通过后，才允许将 V3 状态改为 `BASELINE_FROZEN_FOR_MAP_1` 并进入 `SCM-V3-MAP-1`；否则继续整改。
