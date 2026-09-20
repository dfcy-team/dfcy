# V2.44.134 组合商品业务闭环

## 发布目标

将组合商品合并至商品明细数据，并完成新增、检索、版本管理、库存计算、订单快照、采购展开、退货建议及旧 ZH 关系迁移闭环。

## 主要变更

- 商品明细数据支持全部商品、普通商品、组合商品切换和统一搜索。
- 新增 BigSeller 风格的全屏组合 SKU 编辑器，支持新建组合 SPU 或选择已有组合 SPU。
- 组合 SKU 支持独立主图上传，以及公网图片链接安全下载并转存租户本地存储。
- 组合关系按版本和生效时间管理；历史订单保存下单快照。
- 组合库存按子 SKU 最新仓库快照计算最小可组套数量。
- 采购链路展开组合组成，退货链路提供快照拆分建议。
- 旧 `ZH` SPU 仅作为旧编码识别；支持关系 CSV 预览、校验和确认迁移。
- 补充组合商品查看、管理权限及演示数据。

## 数据库迁移

- `commerce.0002_salesorderbundlesnapshot`
- `commerce.0003_salesorderbundlesnapshot_bundle_version_and_more`
- `products.0022_productbundlemigrationbatch_productbundleversion_and_more`
- `purchasing.0007_supplypurchaseorderline_source_bundle_sku_and_more`

迁移必须在应用容器切换前完成备份，并由受控发布流程执行。禁止跳过迁移或手工写入版本账本。

## 验收结果

- 后端组合商品相关测试通过。
- 前端组合商品及商品明细相关测试通过。
- 前端权限快照检查通过。
- 前端生产构建通过。
- 内置浏览器完成新增组合商品、新旧 SPU 切换、组成 SKU 增删、主图入口及链接转存入口验收。

## 发布与回滚要求

- 基线版本：`V2.44.133`。
- 目标版本：`V2.44.134`。
- 使用 `Developer A Production Release` 受控工作流发布。
- 发布前创建数据库可恢复备份并记录 SHA256。
- 发布后核验四项迁移、容器 revision、前后端镜像摘要、HTTPS 健康检查及组合商品核心接口。
- 完成代码库与虚拟机双账本登记，并创建不可变标签 `v2.44.134-deployed`。
