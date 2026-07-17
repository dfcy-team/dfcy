# UI-P5-ARCH-R1 独立架构复审提示

请只审核，不修复业务代码，并输出 `docs/00_stage0/review/ui_p5_arch_r1_recheck.md`。

## 复审范围

- `backend/apps/products/`
- `backend/apps/purchasing/`
- `backend/apps/suppliers/`
- `backend/apps/permissions/`
- `backend/tests/test_ui_p5_business_mainflow.py`
- `frontend/src/api/`、`frontend/src/views/products/`、`purchasing/`、`suppliers/`、`listings/`、`pricing/`
- `frontend/tests/ui-p5-business-mainflow.spec.js`
- `docs/03_api/ui_p5_business_mainflow_contract.md`

## 必查项

1. 商品和采购是否执行动作权限、tenant 与 permission-specific data_scope。
2. 供应商是否只能访问当前 `tenant_id + supplier_id` 数据，且不能覆盖 supplier_id。
3. 列表是否统一分页并兼容 Mock。
4. 编码冻结是否独立授权且幂等。
5. 供应商反馈是否只修改白名单字段且不泄露财务数据。
6. 刊登、价格、销售订单是否保持 pending/mock，未误标 connected。
7. 是否不存在自动采购、真实刊登、真实改价、库存修改或真实 RPA。
8. 后端全量 pytest、前端测试和 build 是否真实执行。

## 结论规则

- 有 P0：FAIL。
- 无 P0 但有 P1：CONDITIONAL_PASS。
- 无 P0/P1：PASS。
