# UI-P5 业务主链路测试报告

## 1. 测试基线

- 日期：2026-07-17
- 分支：`feature/ui-p5-business-mainflow-integration`
- 范围：商品、采购、供应商协同、刊登/价格待接入边界

## 2. 后端结果

| 检查 | 结果 |
|---|---|
| `python manage.py check` | PASS，0 issues |
| `python manage.py makemigrations --check --dry-run` | PASS，No changes detected |
| 商品/采购/供应商/UI-P5 定向 pytest | PASS，23 passed |
| 后端全量 pytest | PASS，308 passed |

覆盖权限缺失拒绝、permission-specific data_scope、自定义资源范围、tenant 隔离、编码冻结独立权限与幂等、受控状态字段防绕过、采购供应商范围、供应商身份覆盖拒绝、供应商完成数量规则、大于 100 的页码和页大小上限。

## 3. 前端结果

| 检查 | 结果 |
|---|---|
| UI-P5 定向 Vitest | PASS，5 passed |
| 前端全量 Vitest | PASS，91 passed |
| `npm run build` | PASS，1931 modules transformed |

构建保留第三方 `@vueuse/core` PURE 注释位置警告，为非阻断观察项；未通过提高阈值隐藏警告。

## 4. 系统与安全检查

- `docker compose config -q`：PASS；因当前终端未注入运行环境变量而输出空值提示，不是语法错误。
- `git diff --check`：PASS。
- `frontend/dist`、`frontend/node_modules`：未被 Git 跟踪。
- 禁止路径扫描：未发现 UI-P5 页面访问 `/api/finance/*`、`/admin/` 或 RPA Agent 执行端点。
- 凭据扫描：未发现真实账号、密码、Token、Cookie、Session、API Key 或 API Secret。

## 5. 结论

UI-P5 R1 三项 P1 已完成定向整改并通过本地验证，可进入独立架构 R2 复审。刊登、价格和销售订单仍为非阻断 `pending/mock`，不代表后端接口已经完成。
