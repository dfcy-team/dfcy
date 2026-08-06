# A2-00 阻断证据提交单（真实 Sandbox OAuth 接入门禁）

> 用途：A-PR2-REAL-SANDBOX-OAUTH 前置条件核查。六项齐备前保持 synthetic，不发起真实网络请求。
> 填写规则：只填**掩码/引用/登记信息**，禁止真实 partner_key、app_secret、access_token、refresh_token、授权 code 原值、密码。
> 本单只列**必须提交**的字段；项目文档/任务书已固定、代码已就位或可由其他字段派生的项不再重复收集（见文末“无需提交项”）。

---

## a) 获批应用标识（只登记掩码/引用）

| 字段 | Shopee | TikTok Shop |
|---|---|---|
| 应用标识（掩码，如 `shp_app_****8f2a`） | `[待提交]` | `[待提交]` |
| 所属组织 / 负责人 | `[待提交]` | `[待提交]` |

> 环境固定为 Sandbox（Production 始终禁用）；控制台复核人与日期随 b 项文档版本统一登记一次。

## b) 精确端点与合同（以控制台与官方文档原文为准，不填推测值）

> 一次性注明：官方文档版本号/发布日期、控制台复核人、复核日期（两平台可相同）。
> 回调校验方式已由任务书固定为：字段白名单 + state 一次性消费 + 交换响应 shop_id 比对，无需提交。

| 字段 | Shopee | TikTok Shop |
|---|---|---|
| 授权入口 URL | `[待提交]` | `[待提交]` |
| Token 交换 endpoint | `[待提交]` | `[待提交]` |
| Token 刷新 endpoint | `[待提交]` | `[待提交]` |
| 授权撤销 endpoint（平台不支持则注明） | `[待提交]` | `[待提交]` |
| 区域域名 | `[待提交]` | `[待提交]` |
| API 版本 | `[待提交]` | `[待复核]` `/authorization/202309/*` 系列，须控制台确认精确路径 |
| 最小只读 scope 清单 | `[待提交]` | `[待提交]` |
| Token 时效（access/refresh TTL） | `[待提交]` | `[待提交]` |
| 门店信息 endpoint | — | `[待复核]` `/authorization/202309/shops`（获取 shop_id/shop_cipher/region） |

## c) 已登记 HTTPS callback URL

> 硬性要求：HTTPS；与平台控制台登记完全一致；禁止通配符、IP 地址、localhost、用户任意提交 URL。

| 平台 | callback URL |
|---|---|
| Shopee | `[待提交]` |
| TikTok Shop | `[待提交]` |

> 一致性确认随 b 项复核统一登记，不单独收集。

## d) 密钥托管服务合同

> 输入 code / 输出 credential_id、token_id、mask、version、expires_at / HMAC 仅托管侧 / refresh 轮换版本——语义已由任务书固定，无需提交。

| 字段 | 值 |
|---|---|
| 托管服务名称/提供方 | `[待提交]` |
| 托管接口端点（掩码或内网登记名） | `[待提交]` |
| 合同版本号与生效日期 | `[待提交]` |

## e) 网络出口方案

> 双重门禁开关、仅 HTTPS、DNS 不落私网、上限退避、紧急停止开关机制均已由代码/设计固定，无需提交。

| 字段 | 值（无异议即采用默认） |
|---|---|
| 连接超时 / 读取超时（秒） | 默认 5 / 15；`[待提交]` 如不采用默认 |
| 回退方案 | 默认回退 synthetic + 登记故障事件、保持旧授权不变；`[待提交]` 如需变更 |

> allowlist host 清单由 b 项区域域名 + d 项托管端点自动派生，不单独收集；开关责任人并入 f 项批准人。

## f) 专项安全评审书面批准

> 必须区分 synthetic / Sandbox / Pilot / Production 四个环境层级，不得沿用环境权限。

| 字段 | 值 |
|---|---|
| 批准文件路径或编号 | `[待提交]` |
| 批准人 | `[待提交]` |
| 批准日期 | `[待提交]` |
| 覆盖范围声明 | `[待提交]`（须写明本次批准仅覆盖 Sandbox 联调） |

---

## 无需提交项（已由项目文档/任务书/代码固定）

- 环境=Sandbox，Production 始终禁用、无生产开关
- 回调校验=字段白名单 + state 一次性消费 + 交换响应 shop_id 比对
- 托管语义=输入 code（仅内存）、输出引用与掩码、HMAC 仅托管侧、refresh 轮换版本
- 网络门禁=`MARKETPLACE_OAUTH_NETWORK_ENABLED` + 域名 allowlist 双重启用，prod 无条件拒绝
- 出口约束=仅 HTTPS、DNS 不落私网、429/5xx 上限退避、认证错误不无限重试、开关关闭即 fail closed
- allowlist host、开关责任人、各节复核人/日期：从 b/d/f 项派生或统一登记

## 提交后处理流程（由开发A执行）

1. 逐项核对完整性，缺项继续阻断。
2. 登记 evidence registry：仅存掩码、来源、审核人、审核时间、合同版本；入 Git 前经 CI guard 凭据扫描。
3. 冻结 `a2-sandbox-v1` 真实合同。
4. 实现 ShopeeAdapter / TikTokShopAdapter、托管 gateway 切换、网络门禁双重启用。
5. Sandbox 全流程验证 + 凭据扫描 + 变更日志，提请 R8 专项复审；PR #40 保持 Draft。

## 红线提醒

- 本文件与任何 PR/Issue/聊天记录中不得出现真实 Token、Secret、授权 code 原值或密码。
- 控制台截图仅作线下复核依据，须打码，不进 Git。
- 任一证据过期或变更，须重新登记并重新触发门禁核查。
