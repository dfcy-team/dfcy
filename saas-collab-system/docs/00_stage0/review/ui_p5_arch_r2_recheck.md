# UI-P5-ARCH-R2 独立架构复审报告

## 1. 复审对象

- 任务：UI-P5 R1 P1 整改独立复审
- 分支：`feature/ui-p5-business-mainflow-integration`
- 日期：2026-07-17
- 原结论：`UI-P5-ARCH-R1 = CONDITIONAL_PASS`
- 性质：只审核，不修复业务代码

## 2. 复审依据

- `docs/00_stage0/review/ui_p5_arch_r1_recheck.md`
- `docs/00_stage0/review/ui_p5_business_mainflow_change_log.md`
- `docs/03_api/ui_p5_business_mainflow_contract.md`
- R1 三项 P1 的后端实现、前端合同和回归测试

本轮只新增本复审报告。工作区中与 UI-P5 无关的 DOCX 文件继续保持未处理、未暂存状态。

## 3. 复审结论

**PASS**

- P0：无。
- P1：无；R1 的 3 项 P1 已全部关闭。
- P2：5 项，均为非阻断观察项。
- 允许 UI-P5 正式收尾、提交当前功能分支并创建 PR。
- PR 合并前仍需等待远端 CI 成功，并确认提交范围排除无关 DOCX。

## 4. 原 P1 关闭情况

| 原 P1 编号 | 问题 | 是否关闭 | 复审证据 | 备注 |
|---|---|---|---|---|
| UI-P5-R1-P1-001 | 通用 PATCH 可绕过工作流直接修改审批、采购及商品状态 | 是 | `ProductResearchSerializer` 将 `approval_status` 设为只读；`ProductSPUSerializer` 将 `lifecycle_status/sales_status` 设为只读；`PurchaseOrderSerializer` 将 `status/approval_status` 设为只读。POST 使用模型安全默认值，PATCH 显式提交受控字段返回 400。定向测试覆盖创建防注入、PATCH 拒绝和数据库状态不变。 | 通用资料编辑仍可修改普通字段；状态变化只能进入后续授权动作或工作流。 |
| UI-P5-R1-P1-002 | 供应商“已完成”状态前后端合同不一致 | 是 | `SupplierTaskFeedbackSerializer` 已允许 `COMPLETED`，并校验 `completed_quantity == production_quantity`；99/100 返回 400，100/100 成功并写入 completed。 | cancelled 等非白名单状态继续被拒绝。 |
| UI-P5-R1-P1-003 | 分页页码被错误限制为最大 100 | 是 | 公共分页解析仅对 `page_size` 使用最大 100 限制，`page` 允许任意有效正整数；回归测试验证 `page=101&page_size=1` 成功、`page_size=101` 返回 400。 | 超出实际页数仍按分页合同返回 404，不属于页码解析限制。 |

## 5. 通用写接口与工作流边界

1. 新品市调、SPU 和采购订单的受控状态字段均列入 `read_only_fields`。
2. 客户端在创建请求中伪造 approved、confirmed、discontinued 或 stopped 时，后端采用模型安全默认值。
3. 客户端在通用 PATCH 中显式提交受控状态字段时，统一返回 `VALIDATION_ERROR`，数据库原状态保持不变。
4. 商品状态机原有 confirm/reject 动作权限未被削弱。
5. 本次没有伪造新的审批、采购确认或生命周期动作端点；后续状态流转仍需由独立工作流和动作权限承接。

## 6. 供应商完成合同

1. 前端 `completed` 选项与后端枚举已一致。
2. 后端仍以当前 external 会话解析 `tenant_id + supplier_id`，供应商不能覆盖身份。
3. 完成数量小于或大于生产数量时不能将任务标记 completed。
4. 完成数量等于生产数量时可以提交 completed，并返回统一成功响应。
5. 反馈白名单未扩张到采购成本、付款、银行或财务字段。

## 7. 分页合同

1. `page` 必须为正整数，不设置 100 页上限。
2. `page_size` 必须为正整数且最大为 100。
3. 商品、采购和供应商列表继续返回 `count/next/previous/results`。
4. 大页码与页大小上限均有后端回归测试。
5. Mock 集合解析与真实分页结构仍保持兼容。

## 8. tenant、data_scope 与权限

1. 商品和采购查询仍先按当前 tenant 过滤，再执行 permission-specific data_scope。
2. 商品市调、商品主数据、编码冻结和采购订单权限码保持独立。
3. 编码冻结仍要求独立动作权限并保持幂等。
4. external 供应商仍只能访问自己的任务和出货数据。
5. internal、external、RPA 之间未发现新增越权入口。

## 9. pending/mock 与高风险边界

1. 刊登、价格和销售订单未完成能力仍为 `pending/mock`，未误标 connected。
2. 关闭 Mock 时，不会向不存在的刊登或价格接口发送网络请求。
3. 未发现自动采购、自动创建正式采购订单、真实刊登、真实改价、库存修改或真实 RPA。
4. UI-P5 范围未访问 `/api/finance/*`、`/admin/` 或 `/api/rpa/*` Agent 执行接口。

## 10. 独立测试与构建结果

本次 R2 实际重新执行：

| 检查 | 结果 |
|---|---|
| `python manage.py check` | PASS，0 issues |
| `python manage.py makemigrations --check --dry-run` | PASS，No changes detected |
| UI-P5 后端定向测试 | PASS，23 passed in 4.40s |
| 后端全量 pytest | PASS，308 passed in 27.98s |
| 前端全量 Vitest | PASS，7 files / 91 passed |
| `npm run build` | PASS，1931 modules transformed |
| `docker compose config -q` | PASS；仅提示当前终端未注入运行环境变量 |
| 仓库 CI guard | PASS，未发现禁止文件或高置信度凭据 |
| `git diff --check` | PASS；仅有换行符转换提示 |

远端 CI：尚未创建 PR，本轮未执行远端 PR CI，不伪造结果。

浏览器认证态 E2E：本轮未执行，保留为 P2。

## 11. 安全扫描结果

1. 仓库自带 `ci_guard.py` 实际执行通过。
2. 未发现真实账号、密码、Token、Cookie、Session、API Key、API Secret 或私钥。
3. 未发现真实 BigSeller、Shopee、TikTok/TK、银行或支付平台连接。
4. 未发现真实供应商、订单、财务或银行数据。
5. `frontend/dist`、`frontend/node_modules` 未被 Git 跟踪。

## 12. P0 问题

无。

## 13. P1 问题

无。

## 14. P2 问题

| 编号 | 观察项 | 建议 |
|---|---|---|
| UI-P5-R2-P2-001 | 商品主数据列表一次仅取前 100 条 SKU 后在前端关联，大数据量时 SKU 摘要可能不完整。 | 后续由后端返回 SPU 的 SKU 摘要，或提供按当前页 SPU 批量查询合同。 |
| UI-P5-R2-P2-002 | 商品搜索提示包含市调编号或 SPU，后端当前主要按商品名称模糊查询。 | 后续冻结多字段搜索合同并补充字段级测试。 |
| UI-P5-R2-P2-003 | Rollup 对第三方 `@vueuse/core` PURE 注释位置输出警告。 | 在依赖升级和构建优化阶段处理，不通过提高阈值隐藏。 |
| UI-P5-R2-P2-004 | 未执行浏览器认证态 E2E。 | 合并前或后续测试阶段补充 internal 商品/采购与 external 供应商主链路 E2E。 |
| UI-P5-R2-P2-005 | 商品市调审批和采购确认与 UI-P4 工作流资源的业务状态同步尚未形成独立动作合同。 | 后续单独设计动作权限、幂等、审计和状态同步；在此之前保持状态字段只读，不得恢复通用 PATCH 写入。 |

## 15. 是否允许 UI-P5 收尾

**允许。** R1 三项 P1 已全部关闭，未发现新增 P0/P1，UI-P5 可正式收尾。

## 16. 是否允许提交和创建 PR

**允许。** 提交时必须排除无关 DOCX 和 `docs/00_stage0/architecture/` 等非 UI-P5 文件；创建 PR 后需等待远端 CI 成功，再决定是否合并到最新 main。
