# SCM-V3-MAP-1 剩余P1快速整改

- 日期：2026-08-12
- 状态：`READY_FOR_SECOND_RECHECK`

| 剩余P1 | 整改 |
| --- | --- |
| FK删除/保留未冻结 | tenant及跨聚合FK统一PROTECT；私有明细CASCADE但完成聚合禁物理删除；新增RET-AUDIT/PII/MEDIA/TRANSIENT分类及删除/匿名化责任 |
| permission斜杠缩写 | 全部展开为独立exact code；外部供应商submit使用capability而非内部permission |
| API真实路径/HTTP状态 | internal采购路径改为当前`/api/internal/purchasing/supply-orders/...`；existing/proposed明确；补200/201/202/204及4xx合同 |

未修改代码、模型、迁移或数据库。下一步执行第二次快速复核。
