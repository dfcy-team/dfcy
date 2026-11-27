# 系统自动化观测采集

将 collect.py 安装到 /opt/saas-collab/automation，将 service/timer 安装到 systemd 单元目录，执行 daemon-reload 后启用 saas-automation-observations.timer。
采集器每分钟更新 /var/lib/saas-automation/observations.json。将目录只读挂载提供给后台，设置 AUTOMATION_OBSERVATIONS_FILE 为容器内路径。文件600时需通过共同用户及目录权限保障后台只读访问。

覆盖固定清单 systemd 配置、启停、下次触发和最近服务进程结果，三个 cron 文件的实际排程，以及 ABC/补货最近业务计算记录。业务结果携带 tenant_id，由后台按租户过滤。
Beat 配置从 production-celery-beat-1 读取。最近15分钟、最多1000行的 background/control 日志只提取任务ID、结果及时间。其他工作队列以及重启前已清理日志的运行证据可能缺失。
库存预警和首次销售日期维护只提供cron配置观测，其逐次业务运行记录尚未接入。不可读取或不存在的来源将启用状态保留为空，页面显示未采集。
快照先写临时文件再原子替换，超过128KiB时移除最旧运行记录。历史数量有限，文件用于当前观测。
导入前可使用 import_automation_observations 验证。回退时停止并禁用观测timer，恢复此前设置和文件。
