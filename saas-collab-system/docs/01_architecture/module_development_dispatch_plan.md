# 模块化开发节点分发方案

## 1. 分发基线

- 分发日期：2026-07-22。
- Git 基线：`origin/main` 提交 `b697620fefb0c8614467cd7c9fc7eb7cd21a87eb`。
- 交付模式：开发人员本地 Sandbox、GitHub CI 不可变制品、生产发布门禁。
- 开发A模块：销售库存财务对账。
- 开发B模块：达人管理。
- 架构员模块：供应链采购；开发A、开发B不得直接修改该模块。

本分发只冻结任务、API、权限、测试和交付边界，不创建开发人员功能分支，也不修改业务代码。开发人员必须在本分发 PR 合并 `main` 后，从最新 `main` 创建自己的分支。

## 2. 分支与启动命令

开发A建议分支：`feature/module-a-sales-inventory-finance`。

开发B建议分支：`feature/module-b-creator-management`。

```powershell
git fetch origin --prune --tags
git switch main
git pull --ff-only origin main

# 开发A
git switch -c feature/module-a-sales-inventory-finance

# 开发B在自己的工作目录执行
git switch -c feature/module-b-creator-management
```

两个分支不得基于旧 UI、Sandbox、阶段1/2/3功能分支创建。PR 初始状态必须为 Draft；作者不得成为唯一批准人。

## 3. 开发顺序

1. 读取本方案、模块 API 合同和各自任务书。
2. 运行对应 Local Sandbox profile，确认基线可启动、可迁移、可验证。
3. 先提交模型、API、权限、状态机和前端字段合同；涉及公共底座或跨模块合同的变更先由架构员审核。
4. 使用合成数据实现后端、前端、测试和文档，不连接真实平台。
5. 运行模块 profile 验证并提交 Draft PR。
6. 架构员按 L2/L3 门禁独立审核；存在 P0/P1 时定向整改后复审。
7. 一个模块合并后，另一个模块同步最新 `main`，运行 `integration` profile 后再合并。

开发A和开发B可以并行开发，但不得互相合并功能分支，也不得直接修改对方拥有的数据模型。公共 `accounts`、`permissions`、`common`、`audit`、统一响应或跨模块 API 的修改必须在 PR 描述中单独列出影响面。

## 4. Local Sandbox

| 开发节点 | Profile | 主要数据 | 外部能力 |
|---|---|---|---|
| 开发A | `sales-inventory-finance-reconciliation` | 合成销售、商品、库存和脱敏对账数据 | 禁止真实平台、银行和支付连接 |
| 开发B | `creator-management` | 合成达人、合作和效果数据 | 只读 Mock；禁止真实达人平台连接 |
| 合并前 | `integration` | 全模块合成数据 | 所有高风险动作仍禁用 |

Windows 示例：

```powershell
cd deploy/dev-sandbox
.\sandbox.ps1 init
.\sandbox.ps1 start <profile>
.\sandbox.ps1 verify <profile>
```

开发电脑不得连接生产数据库；生产应用主机和数据库主机不得承载开发 Sandbox。

## 5. 风险等级与审核

### 开发A

- 销售只读分析、库存查询和普通页面：L2。
- 财务对账、数据导出、状态确认、权限、`data_scope`、迁移和审计：L3。
- 只要 PR 含 L3 内容，整个 PR 按 L3 执行全量 CI、架构复审、发布审批和回滚验证。

### 开发B

- 达人档案、合作任务、合成效果统计：L2。
- 联系方式等敏感信息、导出、审批、权限、`data_scope` 或状态机：L3。
- 本期不实现结算、付款、真实触达或真实平台同步。

## 6. 合并与集成

- 两个模块没有必须先后依赖，可按独立审核完成顺序合并。
- 第二个待合并分支必须包含当时最新 `origin/main`，并重新运行模块验证和 `integration` 验证。
- 接口不存在时只能标记 `pending`；只使用 Mock 时标记 `mock`；实际 JWT 联调、权限负向测试和 CI 均通过后才能标记 `connected`。
- 合并只使用 merge commit，保留任务、实现、整改和复审历史。
- 合并到 `main` 不代表允许生产发布；生产只接受 CI 生成、固定 Git SHA 和镜像 digest 的不可变制品。

## 7. 不可降低的边界

1. 不提交真实密码、Token、Cookie、Session、API Key、API Secret、私钥或生产 `.env`。
2. 不导入真实客户、达人、订单、供应商、财务、银行或平台数据。
3. tenant、exact action permission 和 permission-specific `data_scope` 必须由后端执行。
4. 财务保持独立授权、脱敏和审计；销售库存权限不能替代 `finance.*`。
5. 补货只产生建议，不自动创建采购订单或通知供应商。
6. 不执行付款、转账、提现、改价、清仓、上下架或真实 RPA。
7. 不连接 BigSeller、Shopee、TikTok/TK、达人平台、银行或支付平台。
8. 前端权限只用于展示和交互，不能成为可信授权边界。
