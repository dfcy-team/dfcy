# TK 广告夜间采集核验与管理员交接

## 范围与结论

本次核验仅涉及阿里云 SaaS 租户 1 的 TikTok GMV Max 广告。生产数据库查询使用只读事务，未改账号、其他模块、授权或既有采集任务。

2026-11-03 晚间核验：正式原始快照表中共有 29 条 `gmv-max-day-v1` 快照，覆盖 15 家店铺。以下店铺均已有 2026-11-02 日快照：

| 店铺 ID | 店铺编号 |
| --- | --- |
| 8 | TKKJ1PH |
| 9 | TKKJ1TH |
| 10 | TKKJ1MY |
| 11 | TKKJ2PH |
| 13 | TKKJ3PH |
| 16 | TKKJ4PH |
| 18 | TKKJ5PH |
| 21 | TKKJ6TH |
| 23 | TK1PH |
| 24 | TK2PH |
| 25 | TK3PH |
| 26 | TK4PH |
| 28 | TK7PH |
| 57 | TK1MY |
| 68 | TK9PH |

这表示日快照已入库，不表示每家最近 7 天均完整，也不代表页面验收完成。多次观察可产生多条快照，报表不能把同一天的历史快照重复相加。

## 已有夜间任务

- 定时器：`saas-tk-gmv-max-daily.timer`，已启用，每天北京时间 02:30。
- 服务：`saas-tk-gmv-max-daily.service`。
- 入口：`python manage.py sync_tiktok_gmv_max_recent --tenant-id 1 --actor-id 1 --commit`。
- 窗口：按广告账户报表时区，刷新最近 7 个完整自然日，不包含当天。
- 范围：动态读取启用的广告映射，逐项核验权限、凭据、店铺归属及 GMV Max 专属广告户证据；不是硬编码上述 15 家，也不会自动放开被拦截映射。
- 并发：系统文件锁加应用采集租约，避免重复执行；不自动重启失败进程。
- 部分失败会记录失败结果，不把排队、启用、空响应或校验失败计为成功、零消耗。

本次没有另建定时器，没有重启服务，也没有重复触发采集。核验时下一次计划为 2026-11-04 02:30（北京时间），并非该轮已执行完成的证明。

## 源码与热部署一致性

以下 PR 工作树文件与线上对应文件按 LF 规范化后逐字节一致：

| 仓库文件 | 线上文件 |
| --- | --- |
| `backend/apps/integrations/gmv_max_schedule.py` | 容器 `/app/apps/integrations/gmv_max_schedule.py` |
| `backend/apps/integrations/management/commands/sync_tiktok_gmv_max_recent.py` | 容器 `/app/apps/integrations/management/commands/sync_tiktok_gmv_max_recent.py` |
| `docs/06_release/saas-tk-gmv-max-daily.service` | 主机 `/etc/systemd/system/saas-tk-gmv-max-daily.service` |
| `docs/06_release/saas-tk-gmv-max-daily.timer` | 主机 `/etc/systemd/system/saas-tk-gmv-max-daily.timer` |

管理员同步 PR #466 时，必须将两个 Python 文件及其依赖纳入正式镜像，不能只保留容器内热补丁。主机 systemd 文件不会随镜像自动安装；应保留并核对现有同名任务，不新增重复任务。完整安装、预检查及回退说明见 `TK-ADS-DAILY-GMV-20261102.md`。

## 验收边界

本次验证了只读入库数量、已有调度配置与四个文件的一致性；没有重新调用 TikTok API，没有重新跑全店 7 天，也没有验证登录后的报表页面。历史绑定证据不完整、店铺身份不符或权限不足的账户仍应阻止采集，不得直接改成通过。

后续管理员应核对每轮成功、失败、阻塞及店铺日期覆盖情况，金额按币种分别展示；GMV Max 与 BASIC 不混加。此前文档中的历史测试与金额不能作为本轮运行结果。
