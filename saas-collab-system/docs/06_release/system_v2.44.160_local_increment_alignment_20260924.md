# V2.44.160 本地增量对齐发布

## 基线与版本约束

- 本批次以虚拟机已部署的 `v2.44.158-deployed`（`acdd77300b6fca02b35c61c0a520fcad8c79c168`）为合并基线。
- 本地增量叠加在该基线上，不覆盖或回退 V2.44.158 已交付的飞书身份候选查询与确认绑定能力。
- 原 V2.44.159 候选发布由对应负责人另行调整版本号；V2.44.160 部署前必须再次确认该版本未被标签、发布单或生产账本占用。

## 交付范围

- 增加 Lazada、Shopee、TikTok 多平台财务交易采集、标准化、宽表服务与对账页面能力。
- 完善生产集成只读客户端、主体授权、凭据刷新、同步时间范围和调度配置。
- 完善仓库 SKU 映射、库存自动关联、库存分析展示及相关安全校验。
- 调整销售工作区的币种换算、筛选与排序，并补齐达人样品履约的仓库和成本约束。
- 增加本地 live 测试配置，仅从环境变量读取专用数据库和密钥，不登记真实凭据。
- 新增 finance `0002` 至 `0004` 迁移，并保持生产 integrations `0030_syncrun_queued_state` 与 products `0019_product_inventory_type` 的既有迁移序列不变。

## 发布安全约束

- 保留生产部署控制中的不可变镜像、镜像拉取超时与失败分类、`--no-build` 以及回滚保护，不接受本地旧脚本覆盖。
- 定时 worker 启动后若 5 分钟仍未取得执行锁，调度器回收该 `running` 派发并阻止迟到 worker 执行；已取得锁的抓取、归档和落库过程定期续租，失去租约的旧执行不得继续写入。
- 只允许经受保护 PR、CI 和 `Developer A Production Release` 工作流发布；虚拟机不从可变源码现场构建。
- 实际部署前再次核对远端主分支、V2.44.160 占用情况、迁移图、镜像摘要和回滚点。

## 候选验证

```text
python -m pytest -q
1831 passed, 30 skipped

python manage.py check
System check identified no issues

python manage.py makemigrations --check --dry-run
No changes detected

npm test
124 test files passed, 757 tests passed

npm run build
菜单权限快照一致：108 项菜单，141 项路由
BUILD_OK

python -m pytest -q tests/test_production_release_control.py
10 passed, 2 skipped

python -m pytest -q tests/test_schedule_contract.py tests/test_phase2_sync_framework.py tests/test_sync_task_controls.py
61 passed
```

## 登记说明

本文件登记的是 V2.44.160 候选范围，不是部署成功证明。只有 PR 合并、CI 通过、受控部署成功、六个生产容器健康、迁移和关键功能验收完成后，才能以实际合并 SHA 创建 `v2.44.160-deployed` 标签并登记生产账本；候选 SHA 不得作为生产 SHA。
