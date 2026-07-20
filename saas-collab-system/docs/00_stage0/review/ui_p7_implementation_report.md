# UI-P7 治理与受控试点实施报告

## 1. 实施对象

- 分支：`feature/ui-p7-governance-pilot-readiness`
- 基线：UI-P6 合并后的 `main`，提交 `17fc2a286e33fb5f5e320d6e630cbf7988a47c0d`
- 范围：API治理、助手治理占位、试点准入、拓扑、恢复演练、发布回滚记录、容量观察及其权限、data_scope、Mock/dry-run 和测试。

## 2. 后端实施

- 新增 `governance` app：API合同目录/详情、固定合同检查、助手目录/详情和固定安全评估。
- 新增 `pilot` app：准入门禁、掩码拓扑、固定拓扑校验、容量观测、恢复计划/演练、发布/回滚计划及不可变审计。
- 已实现冻结合同的 37 个 `method + path` 组合，对应 35 条 Django URL pattern；恢复计划和发布计划的集合路径各由同一 pattern 分别承载 `GET` 与 `POST`，不存在缺失端点。
- 新增 17 个 UI-P7 权限码及数据迁移。
- 所有 UI-P7 接口仅允许 `internal` 用户，并按精确 action permission 和 permission-specific data_scope 校验。
- 未知 scope key、空数组、非法 ID/环境/枚举拒绝；环境、门禁、服务、网段、计划和发布通道均支持范围过滤。
- 恢复和发布状态只能通过专用服务迁移；实例 `save()`、QuerySet `update/delete`、批量更新不能绕过。
- 创建、审批、记录和回滚动作使用幂等键、版本冲突检查、职责分离及不可变审计。
- `start`、`resume`、结果和回滚端点仅记录外部受控操作，不执行基础设施命令。

## 3. 前端实施

- 新增治理与试点菜单及 7 个路由工作台。
- 新增 API合同/助手目录、试点准入、拓扑、恢复、发布和容量页面。
- 页面具备 loading、empty、error、权限拒绝及 capability 状态展示。
- 动作按钮按 `governance.*`、`pilot.*` 精确权限显示。
- 写请求统一携带 `Idempotency-Key`；统一解析 `success/code/message/data`。
- 固定检查使用 `mock`；真实后端结果在浏览器 E2E 前保持 `sandbox`，不会因 HTTP 200 自动标记 `connected`。

## 4. Mock/dry-run

- Mock 数据仅使用 `demo`、`fixed_demo`、掩码主机引用和无效示例环境。
- 合同检查、助手评估和拓扑校验均为固定输出，不调用外部模型、网络工具或真实平台。
- 未提供 Web Shell、Docker、SQL、备份恢复、部署、真实回滚或平台连接按钮。

## 5. 安全边界

- 未接入 BigSeller、Shopee、TikTok/TK、真实 AI provider、银行或支付平台。
- 未提交真实账号、密码、Token、Cookie、Session、API Key、API Secret、私钥或生产连接配置。
- 未启用自动采购、改库存、刊登、改价、清仓、停售、归档、付款、转账、提现或真实 RPA。
- 未修改 `rpa-agent/` 真实执行代码或 `docs/04_rpa/` 协议。

## 6. 实施结论

UI-P7 实现、Mock/dry-run、页面和自动化测试已完成，允许进入独立 `UI-P7-ARCH-R1` 实现复审。该结论不代表允许真实平台接入或生产发布。

## 7. R1 P1 定向整改补充

2026-07-20 已按 `UI-P7-ARCH-R1` 的 5 项 P1 完成定向整改：

- 公共响应字段、枚举、分页和精确错误码已与冻结合同统一，失败响应保持 `data=null`。
- 恢复/发布关键字段全面纳入防绕过保护，回滚批准引用唯一，成功及失败动作均写不可变审计。
- permission-specific data_scope 增加登记值、数量、去重、受控 ALL、创建与 action 独立 scope 校验。
- 恢复/发布/回滚页面补齐全部记录型动作；API合同与助手详情支持直接路由加载。
- 前端真实 JWT 登录兼容后端保留的 SimpleJWT 登录合同；业务 API 仍严格校验统一响应外壳。
- 真实认证本地浏览器已验证 API合同详情和试点准入 sandbox 数据，未标记 `connected`，未执行真实基础设施动作。

整改详情与 R2 验收入口见：

- `docs/00_stage0/review/ui_p7_r1_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p7_arch_r2_recheck_prompt.md`

本补充仅说明整改完成，不替代独立 `UI-P7-ARCH-R2` 结论。R2 通过前仍不得正式收尾。

## 8. R2 P1 定向整改补充

2026-07-20 已完成容量五态与阈值映射、回滚批准数据库唯一性与计划失败审计、前端真实组件状态矩阵及无效详情 URL 404 的定向整改。详细变更和验证证据见：

- `docs/00_stage0/review/ui_p7_r2_p1_fix_change_log.md`
- `docs/00_stage0/review/ui_p7_test_result.md`

本补充不替代独立 `UI-P7-ARCH-R3` 结论；R3 通过前仍不得正式收尾、接入真实平台或执行真实基础设施动作。
