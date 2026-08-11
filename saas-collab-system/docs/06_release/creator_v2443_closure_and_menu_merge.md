# V2.44.3 发布关闭与菜单合并记录

## 发布状态

- 状态：已完成并关闭
- 关闭日期：2026-08-11
- Git 版本分支：`codex/creator-v2.44.3`
- 应用层镜像：`saas-collab-frontend:creator-v2.44.3-20260811`
- 后端镜像：`saas-collab-backend:creator-v2.44-20260810`（本次未修改）
- 数据库：本次未修改、未重启
- VM HTTPS 验证：通过，状态码 200

## 本版本关闭范围

1. 恢复 V2.43 合并时遗漏的全球刊登前端能力。
2. 保留 V2.43 商品明细及商品字段设置入口。
3. 保留达人管理模块，并固定在经营决策之后、流程协同之前。
4. 生产构建使用 `VITE_USE_MOCK=false`，避免加载旧 Mock 菜单和权限。

## 当前菜单基线

### 全球刊登

- 全球刊登工作台：`/listings/workbench`
- 刊登任务：`/listings/tasks`
- 在线商品：`/listings/online-products`
- 平台类目映射：`/listings/category-mappings`
- 商品属性映射：`/listings/attribute-mappings`
- 刊登日志：`/listings/logs`
- 刊登异常：`/listings/exceptions`
- 刊登资料：`/listings/sites`
- 刊登模板：`/listings/templates`

### 商品字段

- 商品明细数据：`/products/details`
- 分类设置：`/products/categories`
- 属性设置：`/products/attributes`
- 颜色设置：`/products/colors`
- 规格设置：`/products/specifications`
- 组合商品：`/products/bundles`

### 达人管理位置

一级菜单顺序必须保持：`经营决策 → 达人管理 → 流程协同`。

## 后续模块合并约束

1. 以 `frontend/src/router/menu.js` 和 `frontend/src/router/index.js` 为菜单与路由基线，禁止使用旧文件整体覆盖。
2. 新模块只插入自身菜单、路由和权限项，不得删除或重排已有模块。
3. 全球刊登必须同时保留页面、API、路由、菜单和权限能力，不能只复制菜单项。
4. 达人管理的 `internal`、`permissions` 和全部 `children` 配置必须完整保留。
5. 商品字段菜单依赖 `products.master.view` 及相应字典权限；合并后需验证角色权限可见性。
6. 全球刊登至少需要校验 `listings.workbench.view`、`listings.mapping.view`、`listings.task.view` 和 `listings.profile.view`。
7. 合并后执行前端测试及真实 API 模式生产构建，并检查全球刊登、商品明细数据、达人管理菜单运行时资源。

## 验证结果

- 前端自动化测试：156 项通过
- 前端生产构建：通过，2005 modules transformed
- 全球刊登运行时资源：通过
- 全球刊登工作台运行时资源：通过
- 在线商品运行时资源：通过
- 商品属性映射运行时资源：通过
- 商品明细数据运行时资源：通过
- 达人管理运行时资源：通过

