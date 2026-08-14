# 销售管理模块审查包

## 1. 基线与范围

- 开发基线：`codex/system-v2.44.6-reviewed-baseline`
- 基线提交：`a4818a7c3fb69f5c4b62cded53595e12695bafb2`
- 开发分支：`feature/module-a-sales-management`
- 工作项：A-SM-01 至 A-SM-06
- 模块定位：只读销售分析（L1）；不执行改价、退款、库存调整、订单状态写回或平台凭据配置。
- 发布状态：仅供业务与架构审查，未声明生产启用。
- 当前评审对象状态：工作树尚未提交和推送；生成 Code Review SHA、Evidence HEAD 与 PR 后方可发起正式复审。

## 2. 交付内容

### 后端

- 新增 `sales_management` Django 应用，覆盖订单、订单行、退款退货、门店销售事实、SKU 销售事实、同步来源、数据质量问题、导出任务和同步重跑申请。
- 平台原始响应的解释和标准化契约归属 `integrations`；销售模块只消费 `sales_order.v1` 标准化结果，兼容入口不再维护独立 Shopee/TikTok 字段映射。
- 新增销售总览、订单、退款退货、门店、SKU、导出、数据质量和同步重跑 API。
- 所有查询均强制 tenant 边界并叠加角色数据范围；导出和重跑按 `tenant + actor + Idempotency-Key` 隔离，并校验请求 payload 与 data scope 指纹。
- 销售总览金额严格按币种分组；仅在结果为单币种或显式筛选币种时返回顶部金额指标，不生成跨币种合计。
- 订单详情的订单行与退货记录在序列化时重新校验 tenant、平台、区域、门店和当前订单查看范围；伪造的跨租户或跨门店反向关联不会进入响应。
- 同步重跑仅接受 `failed` 或 `partial` 来源状态；`pending`、`running`、`success`、`completed` 均由后端拒绝且不写审计。
- 同步重跑先处理既有幂等记录；只有创建分支才锁定请求用户和 `SyncSource`、重新读取来源状态，再执行 `full_clean()` 和插入。同一幂等键在来源状态变化后仍返回原申请，新幂等键则按最新状态拒绝。
- `Idempotency-Key`（最多 120 字符）和重跑原因（最多 240 字符）在事务写入前完成类型、必填和长度校验，避免 SQLite/MySQL 严格模式行为不一致。
- 导出接口和 `create_export_request()` 服务边界同样在写库前限制 `Idempotency-Key` 最多 120 字符；120 字符可创建，121 字符返回 400，且不会新增任务或审计。
- 导出历史同时校验当前权限范围、历史 scope 快照和历史 filters；权限缩小后，不再返回超出当前范围的任务元数据。
- 导出 filters 按导出类型执行字段白名单、值类型、日期格式、敏感键和单数/复数范围字段校验；未知字段及 credential/token/password 等敏感键不会持久化或进入审计。

### 权限

- `sales_management.view`
- `sales_management.orders.view`
- `sales_management.returns.view`
- `sales_management.stores.view`
- `sales_management.skus.view`
- `sales_management.export`
- `sales_management.data_quality.view`
- `sales_management.sync.view`（只读）
- `sales_management.sync.rerun`（独立写权限）

### 前端

- 固定一级菜单顺序：经营决策 → 销售管理 → 达人管理 → 流程协同。
- 新增销售总览、销售订单、退款退货、门店销售、SKU 销售、销售明细导出、数据同步与质量七个页面。
- 前后端未联调时统一显示 `Mock`，不再将模拟数据标记为 `connected`。
- 默认统计区间为最近 30 天；展示数据新鲜度、来源、币种口径、质量评分，以及加载、空、异常、部分成功和过期等状态。
- 同步重跑按钮只由 `sales_management.sync.rerun` 控制，`sales_management.sync.view` 不再产生写能力。

## 3. 路由清单

| 页面 | 路由 | 权限 |
|---|---|---|
| 销售总览 | `/sales-management/overview` | `sales_management.view` |
| 销售订单 | `/sales-management/orders` | `sales_management.orders.view` |
| 退款退货 | `/sales-management/returns` | `sales_management.returns.view` |
| 门店销售 | `/sales-management/stores` | `sales_management.stores.view` |
| SKU 销售 | `/sales-management/skus` | `sales_management.skus.view` |
| 销售明细导出 | `/sales-management/exports` | `sales_management.export` |
| 数据同步与质量 | `/sales-management/data-quality` | 读取：`sales_management.data_quality.view`；重跑：`sales_management.sync.rerun` |

## 4. 数据库迁移

- `permissions.0028_seed_sales_management_permissions`：登记原始八项销售管理权限；迁移内容保持不可变。
- `permissions.0029_seed_sales_sync_rerun_permission`：新增独立重跑权限，并更新导出、同步查看权限描述；逆向迁移恢复旧描述并删除新增权限。
- `sales_management.0001_initial`：创建销售管理模块表、索引和 tenant 内唯一约束。
- `sales_management.0002_*`：为导出与重跑增加请求指纹、重跑数据范围，并将幂等唯一约束扩展到 actor。
- `development.0002_product_sales_summary_view`：设置 `atomic = False`，使既有 `DROP VIEW` / `CREATE VIEW` 迁移可在 MySQL 上执行；未改变视图 SQL 或业务结构。
- SQLite 空库和 MySQL 8.4.11 临时空库均从零完成全部迁移。

## 5. 可复现验证记录

验证时间：2026-08-14（Asia/Shanghai）。测试数据均为合成数据；命令中的数据库密码为测试占位符，不进入仓库。

| 项目 | 环境与命令 | 结果 |
|---|---|---|
| Django 迁移一致性 | Windows；Python 3.11.9；Django 5.2.17；`python manage.py makemigrations --check --dry-run` | 通过，`No changes detected` |
| Django 系统检查 | `python manage.py check` | 通过，0 issue |
| 权限目录一致性 | `python manage.py sync_permissions --check` | 通过，目录完整 |
| SQLite 定向测试 | SQLite 3.45.1；`python -m pytest tests/test_sales_management.py -q` | 22/22 通过，0 skip，49.52s；包含行锁路径及导出 120/121 字符边界 |
| SQLite 后端全量 | `python -m pytest -q` | 455/455 通过，0 skip，122.86s |
| MySQL 定向测试 | Docker 29.5.3；MySQL 8.4.11；`python -m pytest tests/test_sales_management.py -q --create-db` | 从零迁移后 22/22 通过，0 skip，79.32s |
| 前端全量 | Node 24.16.0；npm 11.13.0；Vitest 3.2.6；`npm.cmd test` | 13 files、167/167 通过，0 skip，8.98s |
| 前端构建 | Vite 6.4.3；`npm.cmd run build` | 通过，2012 modules，14.64s；仅第三方 VueUse PURE 注释警告 |

MySQL 证据环境使用独立 Docker network、临时容器数据层和仅本机端口绑定：

```powershell
docker network create codex-sales-evidence-net
docker run --name codex-sales-mysql-evidence --network codex-sales-evidence-net `
  --tmpfs /var/lib/mysql:rw,noexec,nosuid,size=1g `
  -p 127.0.0.1:33307:3306 `
  -e MYSQL_ROOT_PASSWORD=<TEST_ONLY_PASSWORD> `
  -e MYSQL_DATABASE=codex_sales_evidence `
  -e MYSQL_USER=codex_sales_user `
  -e MYSQL_PASSWORD=<TEST_ONLY_PASSWORD> mysql:8
```

容器检查结果：MySQL `8.4.11`；`/var/lib/mysql` 为 `tmpfs`；网络为 `codex-sales-evidence-net`；端口仅绑定 `127.0.0.1:33307`。测试完成后删除专用容器和网络，镜像缓存不删除。

### 浏览器验收

- 环境：Codex 内置浏览器；本地 Vite `http://127.0.0.1:5173`；验证日期 2026-08-14。
- `/sales-management/overview`：标题、七项指标、趋势、异常和门店表正常渲染；页面与侧栏均显示 `Mock`；控制台 0 error。
- `/sales-management/orders`：标题为“销售订单”，16 行可见数据；显示 `Mock`；无横向溢出；控制台 0 error。
- `/sales-management/data-quality`：同步来源和质量问题正常渲染；成功来源重跑按钮禁用、部分成功来源重跑按钮可用；无横向溢出；控制台 0 error。
- 验收后浏览器已恢复到用户原页面 `/analytics/inventory`。

## 6. 指标口径

- 销售额：筛选范围内订单原始销售金额汇总，严格按币种分组。
- 净销售额：同币种销售额扣除已确认退款金额。
- 订单量：筛选范围内订单数。
- 销售件数：订单行销售数量汇总。
- 客单价：同币种净销售额 ÷ 订单量。
- 退款金额与退款率：同币种已确认退款金额及其占销售额比例。
- 未指定币种且命中多个币种时，API 返回 `grouped_by_currency` 和 `currency_groups`，顶部 `metrics` 为空，禁止生成跨币种总额。
- 排名与趋势均继承当前租户、角色数据范围、时间、平台、区域、门店和币种筛选。

## 7. 已知边界与后续联调

- 前端当前使用模块级 Mock 数据展示设计与状态；真实 API 接入前不标记为 `connected`。
- Shopee、TikTok Shop 的真实平台接口、授权、调度、字段映射和凭据由 API 数据接入模块负责；销售模块只消费标准化契约和安全授权引用。
- 正式下载文件存储、任务执行器和同步调度器需在后续联调中接入；当前 API 只保留受控任务和审计边界。
- 当前变更尚未提交或推送，因此还没有可冻结的 Code Review SHA、Evidence HEAD 或 PR；正式复审前必须先生成这些对象。

## 8. 回退策略

1. 若尚未合并，直接放弃本功能分支的销售管理变更。
2. 若已合并但未发布，使用新的回退提交撤销模块代码，不重写受保护分支历史。
3. 若迁移已应用，先停止销售管理入口，再按备份与变更窗口执行逆向迁移；确认无须保留本模块新增数据后才可删除表。
4. 如发现 tenant、权限、数据范围、敏感信息或审计边界异常，立即停止合并和发布。
