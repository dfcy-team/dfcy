# SCM-V3-MAP-1 量化迁移与回滚矩阵

| 波次 | 输入/输出摘要 | 成功阈值 | 失败与回滚 |
| --- | --- | --- | --- |
| DISCOVER | 每租户表计数、状态分布、FK空缺/跨租户、数量和金额总和、附件分类hash | 只读完成；源摘要签名可复算 | 任一查询写入即失败；清理本机快照后重跑 |
| CLASSIFY | 每条source_id唯一归入AUTO/MASTER/STATE/QUANTITY/TENANT/ATTACHMENT/DUP_BOX | 输入计数=所有分类计数；重复/遗漏0 | 分类不守恒即丢弃分类结果，不进入ADD |
| ADD | schema before/after、迁移plan、约束/索引列表 | fresh及历史副本正向成功；反向恢复schema；业务行变化0 | 反向迁移到checkpoint；不可逆DDL禁止准入 |
| BACKFILL | source count、mapped/manual count、逐租户数量/金额、事件重建、hash | source=mapped+manual；跨租户0；超量0；金额/数量差0；重复运行变化0 | 回滚本波新增行/标记，保留审计摘要；不得修改源记录 |
| DUAL_READ_VERIFY | 新旧DTO逐字段、列表计数、权限集合、累计/状态 | 权威字段差异0；预定义展示差异有映射解释；越权泄漏0 | 保持旧读，删除切换候选标记，修复后全量重跑 |
| SWITCH_WRITE | checkpoint、最后旧写ID、新事件ID、幂等账本、队列水位 | 旧入口只读；新写100%领域服务；双写缺失/重复0；错误率门限由部署审核冻结 | 立即关闭新写；回放checkpoint后新事件到旧兼容层，无法无损回放则禁止切换 |
| RETIRE | 备份ID、观察期、恢复演练、依赖扫描、旧字段访问量 | 观察期内旧写0、旧读0、恢复演练PASS、审批齐全 | RETIRE前恢复旧读；删除后只能用已验证备份/正向修复，故属生产独立批准 |

零容忍项：跨租户、同箱双消费、数量超量、丢失审计事件、权限扩大、accepted附件无可信来源、金额对账差异、source_id遗漏/重复。任何一项非零即阻断。

Checkpoint至少包含代码提交、migration leaf、数据库schema摘要、源数据只读摘要、目标表计数、事件最大ID、幂等账本最大ID和备份标识。本机checkpoint不得冒充生产备份。

MySQL门禁覆盖空库/历史合法/所有异常分类、正反向、并发创建/动作、1205/1213、ORM绕过及重放。生产的备份、停写窗口、责任人、RTO/RPO和监控阈值另立审批。
