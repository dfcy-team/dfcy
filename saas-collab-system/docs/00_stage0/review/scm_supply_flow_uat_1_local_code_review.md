# SC-SUPPLY-FLOW-UAT-1 本地代码审核

- 日期：2026-08-08
- 审核基线：`b274eab` 之后的 UAT-1 工作区变更
- 审核范围：本地 UAT 数据生成、自检、停用式清理工具及测试
- 结论：`APPROVED_FOR_SCOPED_LOCAL_COMMIT`

## 1. 审核结论

实现限定在 UAT tooling、管理命令、定向测试和开发报告，没有新增迁移，也没有修改业务模型、状态机、API、权限/DataScope 语义、Web 或小程序。

生成器固定使用 `SC-UAT-DATA-V1`、`SC-UAT-A/B` 和 `SC-UAT-` 业务编号。采购生产、6+4 两批次装箱、集货、附件、异常/受控释放、部分转运、分批 dispatch、到港、到仓和清货均通过既有领域服务推进；没有用 ORM 直接伪造业务终态。

## 2. P1 整改复核

主审发现初版环境门禁仅依赖 `DEBUG`，且未显式拒绝 SQLite 网络路径。整改后：

- 加载 settings 与环境 `DJANGO_SETTINGS_MODULE` 必须一致；
- 只接受明确的 dev/development/local/test/testing 白名单；
- prod/production/pilot/sandbox 明确拒绝，即使 `DEBUG=True`；
- MySQL 只接受 loopback，SQLite 拒绝 UNC、`//`、`file:` 和 `sqlite://` 网络或非本地 URI；
- 数据库名必须与当前连接完全一致，并带 local/test/uat/dev 标识；
- 内存 SQLite 仅在自动化测试显式授权时准入。

新增测试证明生产 settings 和三类网络 SQLite 路径均在写入 tenant 前停止。上述 P1 已关闭。

## 3. 数据、权限与清理审核

相同版本和 payload 重放保持幂等；相同版本异 payload 在 tenant marker 校验处冲突停止。自检覆盖双 tenant、多 supplier、订单明细数量、6+4 守恒、箱消费、附件状态、集货/shipment 状态以及完整/残缺 scope 配置。

清理只接受精确的 `SC-UAT-A/B`，先停用 UAT 用户和小程序身份，再停用 tenant。append-only 事件和受保护业务图保留，不以物理删除伪装清理成功；非 UAT tenant 的负向测试通过。

生成账号全部使用 unusable password，因此当前只完成数据、角色和 scope 准备，不可直接用于人工登录。短期凭据生成、保管、一次性交付和验收后吊销必须作为后续独立安全步骤实施。

## 4. 验证证据

- Django `check`：通过，0 issues；
- UAT SQLite 定向测试：`8 passed in 10.94s`；
- Python 编译检查：通过；
- 本轮文件 `git diff --check`：通过；
- 未新增 migration。

全仓 `makemigrations --check` 受当前工作树中未提交的 `permissions.0024` 与已提交 `permissions.0026` 双叶节点影响而阻塞。本轮未越权修改或 fake 该并行迁移，也未把 `--nomigrations` 结果表述为完整迁移门禁。

## 5. 未准入事项

- MySQL UAT 数据工具实证；
- 可登录 UAT 短期账号和凭据文件；
- HTTP、Web、小程序人工 UAT；
- Android/iPhone 真机验收；
- Sandbox、Pilot、Production 部署或数据迁移；
- 生产附件、下载票据和第三方物流/报关连接。

下一阶段建议进入 `SC-SUPPLY-FLOW-UAT-2 本地短期账号激活、安全凭据交付与人工 UAT 执行基线冻结`，并在启动前单独审核凭据生命周期与本机服务隔离方案。
