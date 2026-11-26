# 月度历史成本导入

输入 UTF-8 CSV 列必须为 `tenant_id,warehouse_id,sku_code,month,unit_cost`，月份格式 `YYYY-MM`，金额为人民币、最多四位小数。每一行建立独立确认成本版本，生效区间为上海时区当月 1 日至下月 1 日（右开）。零成本合法。

默认只预览：

```sh
python manage.py import_monthly_cost_history costs.csv --tenant-id 1 --actor-id 1
```

明确执行写入时添加 `--apply`。导入仅允许同租户有效仓库和 SKU；缺失档案、重复月份、已有确认区间重叠或非法价格会使本次文件拒绝写入。应用在事务中逐行调用追加版本服务，版本号按 SKU 增长。候选数据中的来源期间重叠或补价选择必须先在 CSV 生成阶段通过显式 period-map/month choice 消歧；本导入器不推测平均值，也不导入模糊补价。

预览结果输出 JSON：`valid`、`preview`、`errors`、`applied`。建议原始工作簿先使用本地确定性解析程序做表头、月份、SKU 数量及重复/重叠聚合摘要，再人工映射为上述格式；命令不读取或应用原始工作簿。
