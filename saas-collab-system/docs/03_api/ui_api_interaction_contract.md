# 用户界面 API 交互合同

## 1. 接口分区

- 内部后台：`/api/internal/*`
- 供应商外部端：`/api/external/supplier/*`
- RPA Agent执行端：`/api/rpa/*`
- 财务：`/api/finance/*`
- 报表：`/api/report/*`
- 微信回调：`/api/wechat/*`
- 飞书回调：`/api/feishu/*`
- 平台数据与Webhook：`/api/platform/*`

前端管理页面不得调用 RPA Agent 的 claim、heartbeat、logs、screenshots、complete 或 fail 接口。供应商页面不得访问 internal 或 finance；RPA 不得访问 internal、finance 或 admin。

## 2. 统一响应

成功响应：

```json
{
  "success": true,
  "code": "OK",
  "message": "success",
  "data": {}
}
```

列表响应的 `data` 必须包含 `count`、`next`、`previous` 和 `results`。失败响应必须保持 `success=false`、稳定业务码、可执行消息和 `data=null`。

## 3. 状态码与界面行为

| HTTP状态 | 语义 | 界面行为 |
|---|---|---|
| 400 | 请求结构错误 | 定位字段或请求格式，不自动重试 |
| 401 | 未认证或会话失效 | 尝试一次受控刷新；失败后清理会话并进入登录页 |
| 403 | 角色、tenant或data_scope不足 | 显示无权状态，不提供绕过入口 |
| 404 | 资源不存在或不可见 | 显示不存在，不推断其他租户资源 |
| 409 | 重复操作、状态或幂等冲突 | 锁定重复提交并提示刷新状态 |
| 422 | 字段或业务规则失败 | 显示可修正原因，保留安全的用户输入 |

## 4. 认证与会话

- 登录调用 `POST /api/internal/auth/login/`。
- 当前用户调用 `GET /api/internal/auth/me/`，返回 tenant、user_type、roles、permissions 和 data_scope。
- Access Token 只用于 API 调用；Refresh Token 必须采用受控存储和轮换策略。
- 请求层统一添加认证头、处理单次刷新、阻止刷新风暴并支持显式退出。
- 前端路由守卫只能改善体验；后端必须拒绝所有未授权请求。
- 生产构建不得默认注入 Mock 已登录用户。

## 5. 能力状态

| 状态 | 定义 |
|---|---|
| mock | 仅使用示例数据，不访问真实后端能力 |
| pending | 合同存在但实现或联调未完成 |
| sandbox | 仅连接受控测试环境 |
| connected | 已有最近验证时间和测试证据 |
| degraded | 能力部分可用，必须显示影响和回退方式 |
| disabled | 主动禁用或不允许使用 |

网络失败后的 Mock fallback 必须显式标记为 fallback，不得伪装为 connected。

## 6. 权限与敏感字段

- 菜单、页面、按钮、字段、数据范围、流程节点和导出分别授权。
- 无权字段由后端不返回或脱敏，前端不得依赖 CSS 隐藏保护数据。
- 财务、利润、银行、价格和凭证引用使用独立权限。
- 所有列表、详情、导出和聚合接口必须按 tenant 和 data_scope 过滤。

## 7. 高风险操作

高风险提交必须携带审批实例、幂等键、对象版本、前后值和原因。补货、生命周期、清仓、改价、库存和财务只能产生建议或待确认记录，不得由页面直接触发真实平台、RPA或资金动作。

## 8. 合同冻结要求

每个页面进入实现前，必须在 `frontend_api_mapping.md` 中登记页面、路由、方法、路径、请求字段、响应字段、权限、data_scope、敏感字段、Mock状态、后端负责人和测试用例。不存在的接口只能标记 pending 或 mock。
