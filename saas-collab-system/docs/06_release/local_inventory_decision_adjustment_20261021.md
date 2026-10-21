# 库存预警与补货建议调整（2026-10-21）

## 交付行为

- 补货建议默认仅展示正数建议，可切换全部可计算结果（包括建议为 0 的商品）和待核对数据。
- 待核对按国家/SKU 展示已确认库存、已采集销量、阻断原因和有权访问的处理入口；未知数量保持未知。两个菜单复用同一组件和数据口径。
- 库存预警区分有效预警、评估状态、待核对数据；支持历史查询、SKU/商品、国家代码、类型、等级、处理状态过滤。
- 预警和补货展示计算时间、库存数据时间、规则版本及触发/计算依据。可计算仅表示数据校验通过，创建运营订货草稿前仍需人工复核。
- 完整数据不再命中时自动解除并记事件，重新出现风险时复用原预警；同规则升级复用记录和跟进信息。数据不完整或失效时标为待核对，不能以此解除风险。
- 明确零销量与缺失销量；零可用库存且有可验证需求可命中缺货规则。

## 菜单性能与一致性

分类菜单 GET 不扫描全 SKU 的库存/销售事实。首个请求只登记后台视图；后台每批最多 100 个 SKU，已核对行先显示，统计未完成时明确提示。完成后按数据库分类过滤、计数、分页；切换页签和翻页复用相同国家、销量窗口、目标天数的结果。

视图按租户、用户、当前权限范围、国家和参数隔离。每个请求重新校验权限；权限解析仅在单个请求内复用，不跨请求缓存授权。组织身份保存到后台任务，执行前验证成员、部门及权限状态。

构建使用版本校验防止数据变化后发布旧结果；失联任务有回收路径，轮询不延长后台租约。缓存有效期从完成时计算，最长 5 分钟并受库存快照 24 小时有效期限制。用户可主动重新校验。列表不加载全部预警事件，详情按需读取。

## 自动评估与运行条件

显式评估过的国家/SKU 自动登记刷新策略，保留原评估用户、组织身份、销量窗口和目标天数。一次手动调整会停用同一国家/SKU 的旧策略；后台执行前再检查，防止旧任务恢复旧策略。

同步完成/失败、历史覆盖变化、规则调整、供应进度及相关档案更新后，以固定数量 SQL 标记结果失效，不在业务提交中重算目录。后台重新核对已登记商品，并每 5 分钟补偿刷新。尚未评估的商品显示未评估，需要有权用户在评估状态或补货结果中选择并评估。

需要正常运行现有 Celery worker 和 Beat：

- `apps.alerts.tasks.build_inventory_decision_views`：每 5 秒领取最多两个视图块。
- `apps.alerts.tasks.refresh_inventory_decisions`：每 60 秒领取最多 50 个到期商品。

服务不可用时页面显示后台核对进度，不能把未完成查询显示成无需补货或库存正常。

## 数据库与验证

新增迁移：alerts 0004、0005、0006，仅新增评估/菜单快照表、预警数据状态字段与索引，保存原业务和预警历史。发布时执行现有 migrate 流程并重启 worker/Beat。

验证命令：

```text
python manage.py check
python manage.py makemigrations --check --dry-run
python -m pytest tests/test_inventory_decision_workflow.py tests/test_country_inventory_decisions.py tests/test_phase3_inventory_alerts.py tests/test_inventory_alert_followup.py tests/test_country_read_performance.py tests/test_operating_orders_v2.py -q
npm test -- --run tests/country-inventory-decisions.spec.js tests/inventory-alert-followup.spec.js tests/inventory-workbench-api.spec.js tests/ui-p1-foundation.spec.js
npm run build
```

最终结果：后端 79 项通过（78 项含完整迁移的回归，加 1 项新增权限边界用例）；前端 47 项通过；生产构建、菜单权限快照、Django 系统检查、迁移一致性和 git diff --check 通过。

性能用例：SQLite 本地 1000 SKU，读取 20 行，36 次 SQL，约 0.025 秒；断言该请求不读取库存/销售事实表。该数字不是正式库性能承诺。

页面验收：本地 Playwright 使用模拟 API 数据，1440×1000 与 390×844，验证建议/待核对切换、原因、有效预警和布局，无页面运行异常。正式库数据、跨服务 Celery 部署和端到端延迟仍需发布环境验证。

当前交付为本地源码调整，未部署正式系统。
