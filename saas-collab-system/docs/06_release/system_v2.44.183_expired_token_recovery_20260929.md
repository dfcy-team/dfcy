# V2.44.183 过期 Token 恢复候选流水

## 登记状态

- 日期：2026-09-29；状态：`REGISTERED_FOR_REVIEW`。仅候选登记，不是正式发布或生产部署证明，未创建 deployed 标签。
- 本次实时核对 main 与 `v2.44.182-deployed` 解引用均为 `c6ea8a68f5f2881598d808914d5d38200a457fb0`；最近成功部署为 [36405738065](https://github.com/dfcy-team/dfcy/actions/runs/36405738065)。未发现更高版本远端标签或版本候选 PR。183 为本次检查时的下一候选序号，修正后仍须再次核对占用。
- 新隔离分支：`release/v2.44.183-expired-token-recovery-resumed`。旧撤回工作区不作为候选。
- 最新只读控制检查 [36509677542](https://github.com/dfcy-team/dfcy/actions/runs/36509677542) 成功，返回 `PRODUCTION_BASELINE_RUNTIME=PASS`；此结果不是生产 SHA、双账本或六服务健康的独立读取证明。

## 严格范围

- 初始仅从源工作区相对 V2.44.182 提取 `backend/apps/integrations/automatic_refresh.py` 和 `backend/tests/test_automatic_credential_refresh.py` 两文件差异：152 行新增、6 行删除。源文件不修改，不复制 dirty 树。根据用户后续“本地阻塞处理”授权，在隔离候选新增 `backend/apps/integrations/warehouse_credential_service.py` 的最小修正及真实刷新服务模拟回归；代码范围扩为三文件。
- 意图：未过期保存 Token 仅重验；已过期先现存 RefreshToken 续期再最小只读验证；验证失败保留新引用并保持同步暂停；待验证 Token 在扫描期间过期可续期；恢复入口行锁核对旧引用；诊断字段仅闭合枚举与受限 HTTP 状态。
- 现有菜单影响：店铺档案、仓库档案、平台操作演练、同步任务、集成审计。前端、菜单、路由、布局无差异，无新增迁移。
- 不带入源工作区 `net_guard.py`、`test_custody_security_gate.py` 等既有保护差异，不修改代理配置、安全组或密钥。
- 前端按钮文案、广告专用验证接口、首次新 Token 验证失败根因未交付或未查明；本候选不是广告 API 完整修复。

## 本次验证与阻断

- 隔离定向回归：自动刷新、托管安全、脱敏诊断，SQLite 内存库，启用迁移（未使用 `--nomigrations`）：105 passed / 2 skipped，157.78 秒。这不是全量后端回归或生产业务验收。
- Django check 无问题；makemigrations --check --dry-run 无变更；git diff --check 与仓库 ci_guard 安全检查通过。
- 新增独立非落盘模拟探针调用真实 `refresh_warehouse_authorization`，仅模拟数据库取对象、HTTP 与托管后端，保留真实客户端预检。对 `AUTO_REFRESH_VALIDATION_PENDING` 和 `AUTO_REFRESH_VALIDATION_FAILED` 均确认：`ReadonlyClientBase.preflight()` 先拒绝，HTTP 与 RefreshToken 读取均未发生。
- 初始两文件补丁的仓库过期恢复无法到达刷新接口；定时待验证仓库过期续期同样受该预检影响。原新增仓库测试模拟整个刷新函数，未覆盖真实刷新链路；此问题已在隔离候选修正，见下节。
- 不通过清除生产错误状态、放开普通只读预检或真实刷新来绕过阻断。需要为刷新链路制定最小安全修正及真实服务链路模拟回归，再重新候选核对、正式审阅、CI、受控部署与部署后健康验证。

## 未执行

- 本文登记时尚未部署或登记生产账本；审阅、CI、正式发布提交及部署证据以实际完成结果为准。
- 未发起真实平台刷新、重新授权、同步或启用暂停任务。
- 部署后实际 SHA、镜像摘要、迁移状态、健康和回滚点验证均尚未进行。

## 隔离修正与本次发布前核对

- 仓库刷新仅在“保存 Token 已过期且状态为待验证/验证失败”时，为现有刷新预检创建内存副本并清空该副本的验证错误码。数据库隔离状态不因此清除，普通只读客户端不修改；原有运行模式、模块、配置、网络、托管及自动续期权限/旧引用检查保持不变。
- 新增模拟回归保留真实仓库刷新函数及真实只读预检，仅模拟批准配置和 HTTP/托管边界；修正前六种手动/调度与验证结果组合均失败，修正后通过。覆盖普通读取仍被拦截、未过期不续期、网络未批准不调用平台、后续验证失败保留新引用且任务不启用。
- 快速定向回归：139 passed / 2 skipped（SQLite 内存库，`--nomigrations`）；启用迁移的同组定向回归亦为139 passed / 2 skipped，167.51秒。Django check、迁移漂移和安全扫描通过。这不是全量测试或正式业务验收，本地授权数据不作为生产证据。
- 本次阿里云现场只读核对：`production-backend-1` 与 `production-frontend-1` OCI revision 均为 `c6ea8a68f5f2881598d808914d5d38200a457fb0`，六个 production 服务在运行，服务器内部健康返回 `success=true / code=OK / status=ok`。此为发布前基线，不是183验收。
- 流程：正式 PR 审阅与 CI → 重新核对虚拟机版本及流水 → 受控不可变镜像部署虚拟机及登记 → 统一晋级阿里云 → 阿里云正式服务器最终验证。部署授权不包含真实平台刷新、重新授权、同步启用或安全组调整。
