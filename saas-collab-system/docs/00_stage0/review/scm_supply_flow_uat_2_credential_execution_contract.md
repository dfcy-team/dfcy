# SC-SUPPLY-FLOW-UAT-2 短期账号、凭据交付与人工验收合同

- 日期：2026-08-09
- 代码基线：`ca1240d`
- 数据基线：`SC-UAT-DATA-V1`
- 环境：架构员本机独立 UAT
- 状态：冻结候选

## 1. 目标与授权边界

本阶段为 `SC-UAT-DATA-V1` 中的不可登录占位账号定义短期激活、凭据交付、人工 UAT、证据归档和终止后吊销规则。当前合同只批准下一阶段实现本机账号激活/吊销工具和执行清单，不批准在本轮直接生成密码、启动服务、签发 Token 或执行人工验收。

禁止连接供应链正式系统、生产数据库、生产对象存储、微信正式环境、真实货代/报关/船司/承运商接口或真实通知通道。不得把 Sandbox、Pilot 或 Production 配置用于本机 UAT。

## 2. 激活账号范围

只允许激活 tenant `SC-UAT-A` 下由 UAT-1 创建且用户名以 `SC-UAT-` 开头的固定主体：采购员、装箱协调员、集货员、发运员、只读审计员、供应商 A/B/C，以及 OWN、DEPARTMENT、残缺 CUSTOM 等负向主体。`SC-UAT-B` 默认只用于跨租户负向验证；仅在具体用例需要时激活一个最小只读主体。

以下账号禁止激活：超级管理员、staff、RPA、非 `SC-UAT-` 用户、marker 不匹配的 tenant 用户、已执行 cleanup 的 inactive tenant 用户，以及任何真实人员账号。

每个账号只能绑定一个验收角色，不共享凭据，不临时附加超出冻结矩阵的权限。激活前必须重新执行 UAT `check`，并核对 role、permission、DataScope 和 supplier binding。

## 3. 凭据生命周期

1. 凭据必须由本机加密安全随机源生成，建议至少 20 个字符，并满足 Django 密码校验；不得使用固定口令、用户名、日期、项目名或仓库中的字符串。
2. 激活工具必须交互式运行，要求 `--environment local`、`--confirm-local`、精确数据库名、数据版本和明确的账号白名单；默认 dry-run。
3. 口令不得通过命令行参数、环境变量、Git 文件、数据库业务字段、日志、终端历史、截图、聊天、测试报告或剪贴板长期保存。
4. 工具只向调用终端显示一次临时口令，禁止再次查询明文。若必须生成交付文件，只允许写入用户明确指定的仓库外临时目录，并设置当前 Windows 用户独占 ACL（Linux 为 `0600`）；权限设置或复核失败必须回滚激活。
5. 交付记录只保存 username、role、tenant、生成时间、到期时间、激活批次 SHA-256、状态和操作者，不保存口令、Token、Cookie、Session 或可逆密文。
6. 有效期最长 8 小时，人工 UAT 结束、失败中止或到期时立即吊销；不得延期复用同一口令。
7. 登录成功后不允许业务人员自行修改 UAT 密码。口令遗失时执行吊销并重新生成，不做明文恢复。

## 4. Token、浏览器与小程序规则

- Web/JWT 只允许通过本机登录 API 获取短期 Token；Token 不输出到报告或截图。关闭浏览器和验收服务后必须失效或等待短 TTL 到期，并同步停用账号。
- 浏览器开发者工具网络导出不得包含 Authorization、Cookie 或完整请求体；证据只记录 request_id、状态码和脱敏对象编号。
- 小程序仅允许既有本地 sandbox/mock 身份链路，不调用微信正式 `code2Session`。sandbox subject 视同短期认证材料，不进入 Git、报告或截图。
- Web supplier 与 MiniApp 通道互斥验收必须使用不同会话，禁止复制 Token 绕过通道约束。
- 自动化浏览器如被使用，只能控制本机 UAT 页面；不得保存登录状态、密码管理器记录或浏览器同步数据。

## 5. 本机服务与网络隔离

| 项目 | 冻结要求 |
|---|---|
| Git SHA | 固定为审批后的 UAT 候选提交，任何代码变化需重跑门禁 |
| Django settings | 仅 `config.settings.dev/local/test` 白名单，`DEBUG=True` |
| 数据库 | 独立 SQLite 文件或 loopback MySQL；名称含 `sc_uat/local/test/dev` 标识 |
| HTTP bind | 仅 `127.0.0.1`，不得绑定 `0.0.0.0`、局域网地址或公网 |
| 前端 | 本机 dev server；API base 只能指向 loopback UAT 后端 |
| 小程序 | 本地开发者工具；生产 AppID、正式域名和真实上传关闭 |
| 上传/下载 | `SUPPLY_FLOW_LOCAL_UPLOAD_ENABLED` 默认关闭；若验证本地 fake adapter，必须单项审批且不得变成生产能力 |
| 外部连接 | 平台、微信、邮件、短信、对象存储、物流和报关全部拒绝 |
| 数据 | 只允许 `SC-UAT-DATA-V1` 合成数据 |

启动前和结束后均需记录监听端口、进程、数据库名、settings module、Git SHA 和外部连接扫描结果。任何非 loopback 监听或未知出站连接立即终止验收。

## 6. 人工 UAT 执行顺序

1. **G0 基线确认**：核对 Git SHA、工作区隔离、UAT check、数据库和端口。
2. **G1 账号激活**：dry-run、角色/scope 复核、短期激活、一次性交付、到期时间登记。
3. **G2 认证与权限冒烟**：登录、`auth/me`、菜单、直接 API；正向主体成功，负向主体按 403/404 fail-closed。
4. **G3 采购与路线**：执行 UAT-01～03，验证完工后散货/柜货分流和更正审计。
5. **G4 装箱与集货**：执行 UAT-04～11，验证 6+4、多批次、多供应商、证据和区域归集。
6. **G5 发运链路**：执行 UAT-12～15，验证部分 transfer、多次 dispatch、到港、到仓和清货。
7. **G6 安全与客户端**：执行 UAT-16～19，验证 DataScope、tenant/supplier、通道互斥及 Android/iPhone 显示项目。
8. **G7 审计与退出**：执行 UAT-20，导出脱敏证据索引，停用账号，删除凭据文件和浏览器状态，再运行 UAT check/cleanup 决策。

不得并行共用同一业务账号执行写动作。涉及并发/幂等的场景使用明确的两个受控会话和固定 request_id，不通过重复点击伪造并发证据。

## 7. 证据与隐私

每项结果只能为 `PASS`、`FAIL`、`BLOCKED` 或 `NOT RUN`。证据索引记录 case ID、Git SHA、数据版本、角色、时间、request_id、预期、实际、状态码和脱敏截图哈希。

不得归档密码、Token、Cookie、Session、sandbox subject、完整 Authorization header、数据库 DSN、真实地址/联系人或第三方凭据。截图必须裁剪浏览器账号、开发者工具敏感 header、系统通知和无关窗口。

证据目录必须位于仓库外；最终仅将脱敏索引和审核报告纳入 Git。原始截图按最长 7 天保留，验收关闭后由负责人确认销毁。

## 8. 立即终止条件

出现以下任一情况立即停止服务、吊销全部 UAT 账号并标记整体 `FAIL`：

- 连接或尝试连接正式系统/真实第三方；
- 非 loopback 监听、未知出站连接或误用非 UAT 数据库；
- 凭据、Token 或 Cookie 出现在日志、截图、Git 或聊天中；
- 跨 tenant/跨 supplier 数据泄露；
- 同箱双消费、提前/重复 shipped、状态跳跃或幂等同键异 payload 被接受；
- 账号权限或 DataScope 与冻结矩阵不一致；
- cleanup 影响非 UAT tenant。

## 9. UAT-2 实现准入条件

下一步仅允许实现：本地短期账号激活/吊销管理命令、凭据元数据清单、环境和账号矩阵预检、到期拒绝、测试及开发报告。实现不得保存明文口令，不得修改业务状态机、权限矩阵、API、Web/小程序业务功能或生产配置。

实现完成并通过独立安全代码审核后，才允许申请 `SC-SUPPLY-FLOW-UAT-3 本机人工 UAT 执行`。
