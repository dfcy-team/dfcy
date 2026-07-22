# 开发A/B模块开发进入说明

## 1. 启动结论

开发A和开发B可以准备本地环境；正式编码必须等待本分发 PR 合并 `main`，再从最新 `main` 创建各自分支。

| 节点 | 模块 | 建议分支 | Sandbox profile |
|---|---|---|---|
| 开发A | 销售库存财务对账 | `feature/module-a-sales-inventory-finance` | `sales-inventory-finance-reconciliation` |
| 开发B | 达人管理 | `feature/module-b-creator-management` | `creator-management` |

## 2. 首批开发内容

开发A先完成销售库存口径、现有 API 联调和财务独立权限负向测试，再扩展合成对账流程。开发B先完成达人模型、权限、scope 和状态机，再实现 API 与页面。两者均先使用合成数据和 Local Sandbox。

## 3. 合并条件

1. 模块合同与总接口映射准确。
2. 本地 profile 和 GitHub CI 通过。
3. tenant、permission、`data_scope`、状态机和敏感字段负向测试通过。
4. 实际联调完成前不标 `connected`。
5. 独立架构审核无 P0/P1。
6. 第二个合并模块同步最新 `main` 后通过 integration。

## 4. 发布边界

- 模块 PR 合并 `main` 不等于允许生产发布。
- Production 只部署受保护 `main` 由 CI 产生的不可变制品和相同镜像 digest。
- 不允许从开发电脑或功能分支向生产主机复制源码或本地镜像。
- 真实平台、真实 RPA、自动采购、改价、清仓、资金操作仍需专项评审。

## 5. 回退规则

接口或迁移不兼容、tenant/权限边界失败、敏感信息泄露、真实连接被启用或 CI 失败时立即停止合并。已合并变更按 merge commit 回退，并使用已验证的迁移回滚或向前修复方案；不得强制重写 `main` 历史。
