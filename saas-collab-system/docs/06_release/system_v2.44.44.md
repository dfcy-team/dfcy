# System V2.44.44

发布日期候选：2026-08-27
父版本：`2.44.43`
候选分支：`feature/developer-a-v24443-incremental-data`

## 本次增量

- 基础档案恢复平台、国家、店铺、仓库原设计维度，并由当前租户基础数据驱动联动下拉项。
- API 数据接入恢复连接配置、同步任务、运行记录的业务维度、详情操作和配置联动。
- 增加 Lazada 平台配置、两店共享应用配置、店铺 OAuth 授权与本地模拟回调闭环。
- 接入配置支持服务端平台、API 类型、环境和多站点数据，不使用前端硬编码选项。
- 删除接入配置改为软删除，保留审计、同步任务和历史授权引用。
- 开发环境启用受限文件凭据保管；生产环境仍要求独立、已认证的 HTTP 凭据保管服务。
- 新增两家 Lazada 店铺的脱敏数据结构示例：`docs/03_api/examples/lazada_two_store_config.example.json`。
- 新增仓库档案、极风 WMS 只读库存调用和标准化库存快照的可干跑合成包：`docs/03_api/examples/warehouse_inventory_handoff.example.json`。
- 新增销售管理、经营决策与经营分析的联动合成数据：`docs/03_api/examples/sales_decision_analysis_handoff.example.json`。

## 数据与安全边界

- 示例文件只含占位符，不包含真实 App Secret、Token、密码或租户数据。
- 真实开发者密钥和店铺 Token 不进入 Git、业务表、镜像或发布包；业务表仅保存不透明引用和脱敏状态。
- 本地测试数据不随应用层增量发布，架构员仅接收结构示例和迁移清单。
- 仓库合成包保留 HZ001、PH001、THTB 和演示仓的档案维度，数量、SKU、运行记录均为无凭据示例。
- 销售、预警、补货建议、生命周期复盘和分析指标使用同一组店铺、仓库、SKU 与汇总口径，便于架构员核对跨菜单联动。
- 正式平台网络、OAuth 回调和生产迁移继续受架构安全门禁控制。

## 数据库迁移

- `integrations.0017_platformintegrationconfig_deleted_at`
- `integrations.0018_add_lazada_platform_choice`

迁移必须由架构发布通道审核和执行；开发A受控入口不得直接执行生产 DDL。

## 验证要求

- 前端标准测试与 production build。
- Django system check、迁移漂移检查及相关 integration/masterdata 测试。
- `git diff --check` 与敏感信息扫描。
- 受控发布入口 `--check`，由架构员处理共享路径、迁移和镜像溯源门禁后再批准发布。
