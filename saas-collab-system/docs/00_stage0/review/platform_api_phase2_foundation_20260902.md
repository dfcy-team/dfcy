# API 平台分层第二阶段实施说明（2026-09-02）

## 本阶段结果

本阶段在不替换旧字段、不迁移历史业务数据的前提下，补齐两个兼容层：

1. `PlatformMaster → PlatformSiteMaster → StoreMaster`
2. `MarketplaceStoreAuthorization → ConnectionCapability`

旧 `CountrySiteMaster`、`StoreMaster.country_code/currency/timezone` 和现有授权、同步对象继续保留。

## 数据库变化

- 新建 `PlatformSiteMaster`，以 `tenant + platform + site_code` 唯一标识平台国家/区域站点。
- `StoreMaster` 新增可空的 `platform_site`，以及外部店铺 ID、经营主体、业务模式、履约模式、结算币种。
- 新建 `ConnectionCapability`，按店铺授权连接记录 16 类能力的读写开关、同步方式、游标、优先级和健康时间。
- 所有新增店铺字段均为 nullable 或带安全默认值；迁移不自动回填历史记录。

## API 变化

- 平台站点使用现有主数据通用接口：`/api/internal/master-data/platform-sites/`。
- 能力矩阵接口：`/api/internal/integrations/store-authorizations/{id}/capabilities/`。
  - `GET`：店铺授权查看权限。
  - `PUT`：店铺授权管理权限，按能力代码幂等 upsert。
  - 未提交的能力不删除。
  - 本阶段拒绝所有 `write_enabled=true`。
- 店铺授权响应新增只读 `capabilities_summary`。

## 兼容和安全边界

- 旧店铺可以保持 `platform_site_id = null`。
- 站点必须与店铺属于同一 tenant、同一平台。
- 平台站点 URL 只允许保存非密钥 API 基础地址；凭据继续使用托管引用。
- 授权不是 Active 时，不允许把能力标为 Active。
- 新增主数据类型不扩大真实连接器范围，也不触发任何实时同步或写平台操作。

## 上线与回滚

1. 先部署数据库迁移，再部署 API 和前端。
2. 部署后核对旧店铺总数不变，且旧店铺 `platform_site_id` 为空不影响查询和编辑。
3. 逐租户人工创建平台站点，再分批关联店铺；本阶段不自动回填。
4. 回滚应用代码时，新表和新列可以保留，不影响旧代码读取；若必须反向迁移，应先确认没有新站点和能力记录。

## 下一步

- 增加站点批量种子和“旧国家档案 → 平台站点”的预览式映射报告。
- 根据现有连接器声明自动生成只读能力建议，但仍需人工确认后写入矩阵。
- 把同步任务的数据源选择改为读取能力级 `source_priority`，并加入审计日志。

