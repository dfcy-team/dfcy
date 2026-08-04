# Shopee / TikTok Shop API 对齐矩阵

## 1. PR-A1 资源对齐

| 业务概念 | 现有实现 | PR-A1 决策 | 状态 |
|---|---|---|---|
| 连接配置 | `PlatformIntegrationConfig` | 唯一主模型，改为引用式凭据元数据 | pending |
| 旧连接配置 | `APIIntegrationConfig` | 标记 legacy，不扩展 Shopee/TK 能力 | pending |
| 内部店铺 | `masterdata.StoreMaster` | 直接复用 | pending |
| 门店授权 | 无 | 新增关联主配置和 StoreMaster 的授权记录 | pending |
| 凭据内容 | 三个旧持久化敏感字段 | 仅安全迁移 Mock 后删除；未知内容阻断迁移 | pending |
| 门店权限 | 旧 `integrations.*` 四项 | 新增六项 exact action permission；旧权限保留兼容 | pending |
| data scope | platform/config/resource | 新门店资源增加 `store_ids` | pending |
| 授权审计 | 可变、级联删除 | 只追加、PROTECT、仅脱敏元数据 | pending |

## 2. 平台身份对齐

| 标准字段 | Shopee | TikTok Shop | 存储与校验 |
|---|---|---|---|
| `platform` | `shopee` | `tiktok` | 固定枚举 |
| `region` | 店铺所属区域 | 店铺所属区域 | 大写区域码 |
| `platform_store_id` | `shop_id` | `shop_id` | 字符串，参与全局身份哈希 |
| `merchant_subject_id` | `merchant_id` | 商家主体 ID | 仅后端元数据 |
| `shop_cipher` | 空 | `shop_cipher` | TikTok 必填，非凭据 |
| `credential_id` | 密钥托管引用 | 密钥托管引用 | 不返回列表/详情 |
| `token_id` | Token 托管引用 | Token 托管引用 | 不返回列表/详情 |

## 3. 未来平台接口登记

下列均为未来合同登记，本 PR 不创建路由、不发请求、不标记 connected。

| 能力 | Shopee 合同 | TikTok Shop 合同 | 当前状态 |
|---|---|---|---|
| OAuth authorize | v2 应用授权入口，精确路径待控制台复核 | Partner Center 授权入口 | pending |
| OAuth callback | 校验 state、签名、shop_id、merchant_id | 校验 state、签名、shop_id、shop_cipher | pending |
| Token refresh/revoke | 密钥托管服务内执行 | 密钥托管服务内执行 | pending |
| Authorized shops | 精确 endpoint/version 待复核 | Authorization Shops 日期版本资源 | pending |
| Orders/refunds | A-07 冻结 | A-07 冻结 | pending |
| Inventory | A-08 冻结 | A-08 冻结 | pending |
| Webhook | 平台事件 ID、签名、时间窗去重 | notification ID、HMAC、时间窗去重 | pending |

## 4. 内部 API 对齐

| 页面/调用方 | 方法与路径 | 请求字段 | 响应字段 | 权限 | 状态 |
|---|---|---|---|---|---|
| 内部授权列表 | `GET /api/internal/integrations/store-authorizations/` | `page/page_size/platform/status/store_id` | 分页、平台、店铺、掩码、状态、scope、时间、错误码 | `integrations.store.view` | pending |
| 内部授权详情 | `GET /api/internal/integrations/store-authorizations/{id}/` | ID | 同上；不含 credential/token 引用原值 | `integrations.store.view` | pending |
| 授权动作 | 未注册 | 禁止 raw credential | 无 | `integrations.store.authorize` | pending |
| 撤销动作 | 未注册 | ID、稳定原因码 | 无 | `integrations.store.revoke` | pending |
| 引用轮换 | 未注册 | synthetic/受控托管引用（服务层） | 掩码、版本、状态 | `integrations.credential.rotate` | pending |
| 同步/重试 | 未注册 | ID、幂等键 | 脱敏状态 | `integrations.store.sync/retry` | pending |

## 5. 失败映射

| 场景 | HTTP | code 口径 |
|---|---|---|
| 未认证 | 401 | `NOT_AUTHENTICATED` |
| 非 internal 用户/缺 exact permission | 403 | 统一权限拒绝码 |
| scope 缺失/非法/越权 | 403 | `DATA_SCOPE_MISSING/INVALID/FORBIDDEN` |
| 跨 tenant/store 或不存在 | 404 | `RESOURCE_NOT_FOUND` |
| 全局门店重复绑定/状态冲突 | 409 | `STATE_CONFLICT` |
| raw credential/字段规则错误 | 422 | 统一校验错误码 |

## 6. 放行门槛

`pending -> mock` 仅表示 synthetic 流程测试通过。`mock/pending -> connected` 必须同时具备真实 Sandbox、JWT、200/401/403/404/409/422、tenant/store scope、字段映射、密钥托管和安全审核证据。本 PR 不满足 connected 条件。
