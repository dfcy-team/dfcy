# API 平台类型前期审计与补全（2026-09-02）

## 结论

当前系统存在三套平台枚举：租户平台档案 `PlatformMaster.PlatformType`、集成配置
`integrations.PlatformChoices`、平台档案前端表单硬编码。三者范围不一致，前端甚至未包含已经进入
主数据的 Lazada、Temu。平台身份与连接器可用性也没有统一的只读说明。

本次只完成安全的前置层：建立统一平台目录、兼容别名、目录 API、平台记录的目录元数据，以及
前端动态选项。没有修改订单、库存、财务历史数据，没有扩张真实连接器范围。

## 现有能力核对

| 对象 | 当前证据 | 本次目录状态 |
|---|---|---|
| Shopee | OAuth/授权、只读订单、退货退款 | `ACTIVE` |
| TikTok Shop | OAuth/授权、只读订单、退货退款 | `ACTIVE` |
| Lazada | OAuth/授权框架，未声明同步资源 | `TESTING` |
| 极风 WMS | 独立库存接入，不属于销售平台 | 不进入销售平台目录 |
| BigSeller | 仅保留历史枚举，无能力注册 | `NOT_IMPLEMENTED` |
| Temu、Amazon、Wildberries、Ozon 及 P1-P3 | 未发现可运行连接器 | `NOT_IMPLEMENTED` |

## 本次补全

- 目录覆盖资料中的 P0/P1/P2/P3 平台，并保留 BigSeller、Other。
- 内部值保持历史小写兼容；另提供稳定的大写 `canonical_code`。
- `TK/TIKTOKSHOP/TIKTOK_SHOP` 统一到 `tiktok`，`WB` 统一到 `wildberries`。
- 单独返回 `platform_category`、`priority_level`、`default_integration_mode`、
  `connector_status`，不再用一个“已接入”布尔值混淆概念。
- 平台档案页面从后端只读目录加载类型选项，并明确显示未实现连接器。
- 数据库迁移只扩展字段 choices，不回填、不删除、不覆盖现有记录。

## 尚未完成及风险

1. `CountrySiteMaster.platform` 仍是可空文本提示，不是 `PlatformMaster` 外键；平台与站点尚未真正分层。
2. `PlatformIntegrationConfig`、店铺授权和映射已存在，但还没有统一的连接级能力矩阵。
3. 集成层枚举继续保持原范围，避免仅因“主数据可选”就误启用未实现连接器。
4. 平台标签仍散落在销售、分析、权限范围和 Mock 页面，需要后续逐模块替换。
5. 下一阶段应新增可回滚的 `platform_site` 与 `connection_capability` 模型，先兼容读/双写，
   再做历史数量核对；不得直接替换旧字段。

