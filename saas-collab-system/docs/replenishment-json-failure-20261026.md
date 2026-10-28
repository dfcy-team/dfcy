# 全国家补货清单 JSON 保存失败修复

2026-10-26 正式环境只读排查：马来西亚、策略版本 3、销量截至 2026-10-25，两次任务均停在 processed=20 / total=6128。不是任务两小时截止时间到期。

使用原任务权限上下文，在数据库只读事务内计算第 21—40 个候选商品，20 条计算成功。对结果执行 JSONField 保存前转换（不写数据库），复现 `TypeError: Object of type datetime is not JSON serializable`。非 JSON 原生字段为 `data_at: datetime`。

原因：后台直接调用参考视图，未经过 HTTP 响应渲染；带 datetime 的数据时间直接进入 JSONField，第二个分块保存失败。现有异常处理只提供通用错误文本。

修复：在结果快照写入前使用 DjangoJSONEncoder 转为 JSON 原生值；datetime/date 按 ISO 格式保存，Decimal 保留精度为字符串。数量字段和补货算法保持原逻辑。无数据库结构变化。

正式数据只读验证：同一分块 20 条经过转换后全部通过 JSONField 编码校验；未写任务、订单、策略或库存，未部署。

回归覆盖：首批 20 条正常、后续批次嵌套 datetime/date/Decimal/null；任务完成、分页结果可读、重复执行不重复创建。

验证：`python -m pytest tests/test_replenishment_jobs_acceptance.py -q --nomigrations`，11 passed（3.77s）；此前标准迁移初始化成功，10 个原有用例通过，新增用例的分页参数改为接口支持的 limit=20 后全部通过。`git diff --check` 通过。

证据位于工作区 `审计产物/replenishment_failure_probe_20261026.json`、`replenishment_chunk_failure_20261026.json`、`replenishment_chunk_normalized_20261026.json`。

部署后需重新生成失败任务，确认全量 6128 个候选可完成；不能将本次 20 条只读验证视为全量验收通过。
