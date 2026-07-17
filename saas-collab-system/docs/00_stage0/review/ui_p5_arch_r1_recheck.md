# UI-P5-ARCH-R1 独立架构复审报告

## 1. 复审对象

- 任务：UI-P5 业务主链路独立架构复审
- 分支：`feature/ui-p5-business-mainflow-integration`
- 日期：2026-07-17
- 范围：商品、采购、供应商协同、权限目录、前端 API 与页面、Mock/pending 边界及对应测试
- 性质：只审核，不修复业务代码

## 2. 复审依据

- `docs/00_stage0/review/ui_p5_arch_recheck_prompt.md`
- `docs/03_api/ui_p5_business_mainflow_contract.md`
- `docs/05_test/ui_p5_business_mainflow_test_report.md`
- 当前分支相对基线的后端、前端和测试实现

工作区包含尚未提交的 UI-P5 实现以及与本次审核无关的 DOCX 文件。本次复审未修改业务代码，也未处理、暂存或删除无关 DOCX。

## 3. 复审结论

**CONDITIONAL_PASS**

- P0：无。
- P1：3 项，尚未关闭。
- P2：4 项，均为非阻断观察项。
- 当前不允许提交 UI-P5 分支或创建 PR；应先定向关闭 P1，再执行独立 `UI-P5-ARCH-R2`。

## 4. 权限、tenant 与 data_scope

复审通过项：

1. 商品市调、商品主数据、编码冻结及采购订单已建立独立权限码。
2. 商品与采购权限类要求已认证的 internal 用户，并同时校验动作权限与 permission-specific data_scope。
3. 商品和采购查询先按当前用户 tenant 过滤，再应用资源范围过滤。
4. 缺少权限、跨 tenant、超出自定义资源范围的请求已有拒绝测试。
5. 编码冻结使用独立权限，重复冻结保持幂等，已有回归测试。

未通过项：通用商品、采购更新序列化器仍允许直接写入审批或业务状态，详见 P1-001。

## 5. 供应商边界

复审通过项：

1. external 供应商身份由后端 `ExternalUserProfile` 解析，不信任前端自行提交的 `supplier_id`。
2. 供应商任务和出货查询按 `tenant_id + supplier_id` 双重过滤。
3. 请求尝试覆盖其他 `supplier_id` 时会被拒绝。
4. 供应商反馈仅开放完成数量、任务状态、反馈说明和异常说明白名单字段。
5. 供应商响应未发现采购成本、付款、银行或其他财务敏感字段。

未通过项：供应商任务“已完成”状态的前后端合同不一致，详见 P1-002。

## 6. 分页与 Mock 兼容

复审通过项：

1. 商品、采购和供应商列表统一返回 `count/next/previous/results` 分页结构。
2. 前端统一兼容分页结果和 Mock 数据集合。
3. 刊登、价格和销售订单未完成能力保持 `pending/mock`，关闭 Mock 时不会请求不存在的真实接口。
4. 未发现未完成接口被误标为 `connected`。

未通过项：公共分页函数把 `page` 与 `page_size` 同时限制为最大 100，详见 P1-003。

## 7. 工作流与高风险动作边界

1. 未发现自动创建采购订单、自动采购、真实刊登、真实改价、库存直接修改或真实 RPA 执行。
2. 刊登和价格占位操作保持禁用或 pending，不会触发真实平台。
3. 编码冻结动作具备独立权限和幂等保护。
4. 商品审批、采购确认和商品生命周期状态仍可通过通用 PATCH 直接写入，尚未完全收敛到工作流或动作权限，构成 P1-001。

## 8. 独立测试与构建结果

本次复审实际重新执行结果：

| 检查 | 结果 |
|---|---|
| `python manage.py check` | PASS，0 issues |
| `python manage.py makemigrations --check --dry-run` | PASS，No changes detected |
| UI-P5 后端定向测试 | PASS，20 passed |
| 后端全量 pytest | PASS，305 passed in 28.79s |
| 前端全量 Vitest | PASS，7 files / 91 passed |
| `npm run build` | PASS，1931 modules transformed |
| `docker compose config -q` | PASS；仅有当前终端未注入环境变量的空值提示 |
| `git diff --check` | PASS；仅有换行符提示 |

远端 CI：本轮未创建 PR，因此未执行远端 PR CI，不伪造结果。

浏览器认证态 E2E：本轮未执行；当前证据为单元/接口测试和生产构建结果。

构建观察项：Rollup 对 `@vueuse/core` 的第三方 PURE 注释位置输出非阻断警告。

## 9. 安全扫描结果

1. 未发现真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。
2. 未发现真实 BigSeller、Shopee、TikTok/TK 平台连接或凭据。
3. 未发现 UI-P5 页面访问 `/api/finance/*`、`/admin/` 或 RPA Agent 执行端点。
4. `frontend/dist`、`frontend/node_modules` 与 npm 缓存未被 Git 跟踪。
5. 未发现真实供应商、订单、财务或银行数据进入实现和测试样例。

## 10. P0 问题

无。

## 11. P1 问题

| 编号 | 问题 | 证据 | 风险 | 验收标准 |
|---|---|---|---|---|
| UI-P5-R1-P1-001 | 通用更新接口可绕过工作流和动作权限直接修改关键状态 | `backend/apps/products/serializers.py` 的 `ProductResearchSerializer` 可写 `approval_status`，`ProductSPUSerializer` 可写 `lifecycle_status/sales_status`；`backend/apps/purchasing/serializers.py` 的 `PurchaseOrderSerializer` 可写 `status/approval_status`；对应通用 PATCH 仅使用 manage 权限。现有采购测试还允许 PATCH `status=confirmed`。 | 具备 manage 权限但不具备审批/确认权限的用户可直接审批市调、确认采购单或改变商品高风险状态，绕过 UI-P4 工作流审计。 | 通用编辑序列化器将审批、订单状态、生命周期和销售状态设为只读；所有状态流转进入动作权限或工作流端点；补充通用 PATCH 拒绝和授权动作成功/未授权动作拒绝测试。 |
| UI-P5-R1-P1-002 | 供应商任务完成状态前后端合同不一致 | `backend/apps/suppliers/serializers.py` 的 `ALLOWED_SUPPLIER_STATUSES` 不包含 `COMPLETED`；`frontend/src/views/suppliers/SupplierTaskDetail.vue` 提供并提交 `completed`。 | 供应商选择“已完成”后得到 400，任务回填主链路无法完成。 | 冻结唯一合同：后端在满足完成数量规则时接受 `COMPLETED`，或前端移除该选项；前后端合同测试必须覆盖完成和非法完成场景。 |
| UI-P5-R1-P1-003 | 页码被错误限制为最大 100 | `backend/apps/common/query.py` 对 `page` 和 `page_size` 复用 `positive_int(..., maximum=100)`。 | 超过 100 页的 tenant 无法访问第 101 页及后续数据，分页合同不完整。 | 分离页码和页大小解析；`page_size` 上限保持 100，`page` 允许合理的任意正整数；增加第 101 页回归测试并验证空页分页结构。 |

## 12. P2 问题

| 编号 | 观察项 | 建议 |
|---|---|---|
| UI-P5-R1-P2-001 | 商品主数据列表仅一次请求前 100 条 SKU 后在前端关联，SKU 超过 100 条时展示不完整。 | 由后端返回 SPU 的 SKU 摘要，或按当前页 SPU 批量查询全部相关 SKU，避免固定 100 条截断。 |
| UI-P5-R1-P2-002 | 商品列表搜索提示包含“市调编号”或“SPU”，后端当前主要按商品名称模糊查询。 | 统一搜索合同并补充 research 编号、SPU 编码等明确字段测试。 |
| UI-P5-R1-P2-003 | 前端构建存在第三方 `@vueuse/core` PURE 注释警告。 | 记录依赖版本并在后续依赖升级或构建优化中观察，不通过提高阈值掩盖问题。 |
| UI-P5-R1-P2-004 | 本轮未执行浏览器认证态 E2E。 | P1 修复后增加至少一条 internal 商品/采购和一条 external 供应商主链路 E2E，覆盖权限拒绝和状态展示。 |

## 13. 整改建议

1. 优先封闭通用 PATCH 的关键状态写入口，使业务状态仅能经动作权限和工作流流转。
2. 冻结供应商完成状态合同，并以相同枚举和业务规则更新前后端测试。
3. 修正公共分页参数解析，补充大页码回归测试。
4. 完成整改后重新执行后端定向/全量测试、前端全量测试、构建与安全扫描。
5. 生成独立 `UI-P5-ARCH-R2` 报告；R2 达到 PASS 后，才允许提交、推送并创建 UI-P5 PR。

## 14. 是否允许提交和创建 PR

**不允许。** 当前无 P0，但仍有 3 项未关闭 P1，结论为 `CONDITIONAL_PASS`。应先完成定向整改并通过独立 R2 复审。
