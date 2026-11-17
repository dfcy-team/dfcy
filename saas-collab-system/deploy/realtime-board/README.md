# 实时数据大屏工作时段保障

保障时段：每天北京时间 09:00–19:00。资源隔离和异步快照避免页面读取等待其他业务重任务；不能替代主机、Redis、数据库及网络本身的高可用。

## 服务与路由

保留 `realtime-board-api` 独立 gthread 服务和 `realtime-board-refresh` 独立 Celery 队列。两者加载 `board_service_settings`，开启 `BOARD_AVAILABILITY_ENABLED=1`，刷新 worker include `apps.sales_management.board_availability`。普通业务 backend 保持开关关闭。完整容器参数以受控生产 runtime-compose 为准，禁止用仓库旧 compose 覆盖现有运行拓扑。

`nginx-locations.conf` 内容需插入 HTTPS server 的普通 `/api/` location 之前；同时应用于 `/etc/nginx/conf.d/default.conf` 和 `/etc/nginx/templates/default.conf.template`。只修改前者会被容器启动模板覆盖。不得给授权响应添加共享 Nginx 响应缓存；每次快照读取仍校验用户和数据范围。

## 快照语义

快照新鲜期 60 秒，最多保留 600 秒；过期重算在独立队列执行。首次无快照返回 503 BOARD_WARMING，前端每 2 秒重试；同范围刷新保留旧页面并提示。权限范围改变即清空旧结果。库存独立读取，严格遵守 24 小时有效快照，最早失效时刻到达即停止展示旧库存。

## 工作时段资源策略

`resource_guard.py` 只管理白名单后台容器，09:00–19:00 绑定 CPU 1、权重 256；大屏专用服务使用 CPU 0。原始配置按不可变容器 ID 存档，受生产全局部署锁保护。非工作时段恢复配置，并回读确认后才删除恢复记录。Docker 空 cpuset/零 shares 更新会被视为无改动，因此默认值恢复为宿主允许的完整 CPU 集合和权重 1024。操作员主动修改或容器换代时不得恢复旧 ID 配置。

`runtime_tick.py` 每分钟调用资源策略，08:45–19:00 对最近活跃授权查询预热。systemd `dfcy-board-workhours.timer` 使用 Persistent=true。安装目录包含脚本、policy、state、last-tick.json、health.jsonl；定时任务路径保持一致。只读检查：`systemctl is-active dfcy-board-workhours.timer`，核对 last-tick 的 resource_policy 和 prewarm 结果。不要输出生产环境变量或凭据。

## 回退与发布约束

发布前读取当前受控 canonical，保留所有并行热修、上述两个服务和 systemd timer。发布大屏后端代码时同步更新普通 backend、API 和 refresh worker 镜像，不能只更新其中之一。资源策略回退使用 `python3 resource_guard.py --config resource-policy.json --state resource-state.json --restore`；必须检查 errors=0 和实际 CPU 配置，不能仅看命令退出。

2026-11-17 线上修复证据：工作目录 `开发交付/大屏工作时段保障_20261117` 的 resource-restore-fixed.json、public-api-verification.json。公网销售缓存 0.073–0.487 秒，库存 0.065–0.087 秒，另一个 31 天后台查询运行时当前大屏 0.059–0.231 秒。首次异步准备销售约 7.7 秒、库存约 6.6 秒。用户反馈常规更新提示多余，已取消正常刷新时的快照/正在更新提示，只有超过 180 秒未更新才提示异常。该调整 46 项前端测试通过，并重建容器验证启动模板路由仍生效。页面最终人工验收已通过：显示正常、无常规更新提示、自动刷新及库存回填正常。未登记版本、未合并 PR。
