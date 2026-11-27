# 自动化任务菜单交付说明

入口为系统管理 → 自动化任务，路由 /system/automation-tasks。总览、任务列表、详情、运行记录支持名称、来源和指定任务筛选。内部超级管理员可访问，业务同步、闪购和计算结果按租户读取。

数据接入包括数据库同步任务及运行记录、已安装的闪购模块、实际 Beat 配置观测、九种服务器任务。观测超过15分钟显示待确认，未知启停使用空值。服务器采集安装见 deploy/automation/README.md。运行记录当前每来源最多1000条，服务器观测每任务最多100条，整个快照128KiB有界。

部署时将 source 中的增量合入目标发布源，使用完整目标基线构建。基线提交见manifest。若目标含闪购模块，保留该模块及现有工作台，使用既有同步任务页面链接。当前本地较新主线未收录闪购模块，适配器按是否安装加载；同一接口源码另在含闪购的开发基线通过12项测试。

将 deploy/automation/collect.py 安装至 /opt/saas-collab/automation/collect.py，安装同目录service/timer，执行 systemctl daemon-reload 和 systemctl enable --now saas-automation-observations.timer。将 /var/lib/saas-automation 目录只读挂载到backend，设置 AUTOMATION_OBSERVATIONS_FILE=/var/lib/saas-automation/observations.json。后台必须能读取采集文件，按实际容器UID设置目录与文件权限。使用目录挂载以便原子替换后仍读取新文件。先运行采集器并执行管理命令 import_automation_observations 校验候选快照，再配置页面读取路径。

回退时恢复本次变动前源文件及前端制品，停止禁用观测timer并恢复后台观测设置。部署前备份旧文件、compose及配置。无数据库结构迁移。

安装后使用内部超级管理员验证菜单，核对补货定时器实际启停和下次触发、ABC参考结果、同步运行及闪购批次。检查普通用户403，其他租户业务记录不可见，停止采集15分钟后页面标记待确认。外部服务结果为进程退出证据，业务计算结果另标明状态。

库存预警及首次销售日期维护目前提供cron排程观测，逐次业务运行记录待对应来源补接。Beat事件来自background/control最近15分钟有界日志，其他队列及已清理日志可能没有事件。浏览器验收使用本地受控API响应，生产登录态页面尚未验收。

版本登记使用随包changes.json，按登记时最新账本分配版本。发布准备遵循仓库 release:prepare、release:build、部署后release:confirm。本包状态为开发完成待版本登记及生产发布，生产历史中不写未发布记录。
