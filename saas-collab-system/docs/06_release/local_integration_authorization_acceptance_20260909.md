# 平台接入、店铺授权、仓库授权专项验收

后续优化与回调判断更正见 [本地接入与授权流程优化](local_authorization_optimization_20260909.md)：手动回填不要求公网转发可达；仍需本地 state、回调登记和加密托管满足条件。以下保留当时的测试记录。

执行日期：2026-09-09，Asia/Shanghai。结论：**本地部分用例通过；真实平台端到端验收阻塞待验**。

## 环境与边界

- 代码：V2.44.83 / `338085edb3d163a09987291d4cc0a5adf89d933d`，保留现有未提交增量。
- 用户实际已登录的 Chrome 会话，租户管理员；前端 `http://127.0.0.1:3001`，后端 `http://127.0.0.1:8001`。
- 页面写入仅在 `saas_collab_acceptance_20260909`（本机 Docker MySQL，127.0.0.1:3307）。没有写入原共享库、虚拟机或阿里云，也未发布代码。
- 自动化使用独立 SQLite 内存数据库、合成账号和假凭据，阻断外部 socket；合成 Provider 的成功不作为真实 OAuth 成功。
- 本次仅新增非敏感公共配置。用户填写的真实密钥未导入当前 file 托管，不调用真实授权、连接校验或同步。

## 实际页面与数据库核对

| 编号 | 操作 | 结果与证据 | 判定 |
| --- | --- | --- | --- |
| I01 | 新建极风公共配置，TH / 库存 API | 隔离库配置 #4，pending_review / unconfigured；创建后引导先维护四个公共字段，再填写仓库凭据 | 通过 |
| I02 | 新建 Shopee 公共配置，PH / 商城 API | 隔离库配置 #5，pending_review / unconfigured；刷新后存在 | 通过 |
| I03 | 新建 TikTok Shop 公共配置，PH / 商城 API | 隔离库配置 #6，pending_review / unconfigured；未混用广告 API | 通过 |
| I04 | 对无凭据极风配置执行“检查凭据” | reference-check 返回 400，配置未变为已连通；本项不代表外部平台检查 | 通过 |
| S01 | 新建 Shopee 店铺 #68 的 API 接入 | 显示未绑定、暂无可用配置；授权与手动回调提交按钮禁用 | 通过（缺配置分支） |
| S02 | 新建 TikTok Shop 店铺 #67 的 API 接入 | 商城与广告区域分开，均未绑定；无就绪配置不可授权 | 通过（缺配置分支） |
| W01 | 新建三方仓，选择自定义编码的“极风平台” | 显示接入配置、OMS Email、一次性 Token、服务商外部仓库编码；配置下拉仅出现极风配置 | 通过 |
| W02 | Email / Token 留空保存 | 返回 400，两字段各显示“首次配置极风仓库时必填”；可继续编辑，仓库计数仍为 0 | 通过 |
| W03 | 填写明确标记的假 Email / Token，绑定未就绪的公共配置 | 返回 400；只读服务校验确认原因是“接入配置必须处于已配置、已检查或启用状态”；没有留下仓库或授权记录，随后取消表单 | 通过（失败原子性）；成功保存待验 |

最终只读查询：测试店铺 2 个、两者 is_connected=false；测试仓库 0 个；店铺授权 0、仓库授权 0、同步任务 0、同步运行 0。库内已有 2 条 2026-08-08 的 pending OAuth 会话，不是本次新建，不修改、不算成功授权。

三个新配置 network_enabled、sync_read_enabled、sync_write_enabled 全为 false。配置的 environment=production 仅表示拟对接的上游类型，不表示生产部署或网络已放行。

## 自动化专项回归

首组最终 **82 passed、3 skipped，137.08 秒，退出码 0**，文件如下：

- test_phase2_integrations_secure_config.py
- test_integration_credential_maintenance.py
- test_shopee_production_oauth_readiness.py
- test_manual_store_callback.py
- test_oauth_callback_target_security.py
- test_warehouse_api_binding_closure.py
- test_jifeng_warehouse_credentials.py
- test_warehouse_credential_idempotency.py
- test_custody_service.py
- test_custody_security_gate.py

覆盖配置权限/租户隔离、敏感值不回显、受控凭据维护、回调目标与 state 校验、仓库换绑及重放幂等、Token 留空保留、凭据失败回滚、只读检查选择正确仓库授权、托管加密与认证边界。3 个跳过项为 Windows 不支持的 POSIX 文件权限检查，不计为通过。

执行问题及处理：

1. 首次收集缺少 cryptography；按现有 requirements 范围安装到本地虚拟环境，未修改依赖声明。
2. 随后运行 79 passed / 3 failed / 3 skipped。根因是验收启动器把 PLATFORM_NETWORK_MODE 配成当前版本不接受的 mock，导致运行配置整体退回安全默认值；不是三个业务功能同时失效。
3. 将两个本地临时启动器改为该版本支持的空模式（关闭外部调用），保持安全批准=false、只读同步=false、主机白名单为空。重新运行得到上述 82 passed。
4. 仅重启 8001 验收后端以加载正确设置，未重启原 8000 或远程服务。当前 file 托管仅限合成测试，不能据此放入真实密钥。

另新增 `test_marketplace_callback_acceptance.py`，针对 Shopee / TikTok Shop 分别验证：新手动回调成功且重放不覆盖、未认证请求不消费 state、自动成功后手动重放不破坏授权、错误店铺不消费正确回调。结果 **8 passed，117.65 秒，退出码 0**。未认证用例不是浏览器真实 JWT 刷新链路测试。

本轮两组所选测试互不重复，合计 **90 passed、3 skipped**。未计入此前阶段的 119 项及其他回归，避免重复统计。

## 未解决问题与真实联调阻塞

1. **回调目的地**：用户文件的 Shopee 回调指向生产主机 xtsy.dingfengchuangyu.com；TikTok 回调主机 dingfengchuangyu.com 是否落入独立验收后端尚未确认。不能因用户填写就视为可写生产，不能仅因域名不同就判断是本地。
2. **真实凭据托管**：本地当前为 FileCustodyBackend，仅允许本地合成测试，文件内容不是生产级加密托管。已有加密 HTTP custody 实现的合成回归通过，不等于该服务已部署。真实凭据导入前必须准备受控、加密、认证且目标明确的托管服务。
3. **误导文案**：接入配置及店铺弹窗宣称“加密写入 SaaS MySQL”，而当前体系主要保存托管引用；仓库也无条件宣称“Token 加密保存”。已登记，不据此认定实际加密通过，本轮未改这些页面说明。
4. **配置可用性提示**：仓库下拉显示尚未就绪的公共配置，保存时才拒绝；店铺下拉则隐藏它们并只显示“暂无可用配置”。后台防护生效，但缺少就绪条件说明，需后续改善。
5. **未通过的完整链路**：三平台真实授权、有效凭据只读连接、8 月数据采集均未执行；仓库真实凭据首次保存、MySQL 下完整换绑和校验成功路径仍待验。不创建或启用真实同步任务。

需补充：指向本地隔离验收后端的 Shopee / TikTok Shop 注册回调地址（不是完整授权回调，不含 state、code 或 Token），并确认 TikTok Shop 的实际店铺身份；准备本地加密托管后再执行真实联调。此前已填写的真实密码/密钥无需在聊天中重复发送。

## 用户确认转发后的路由核查（14:14–14:16）

用户已明确说明 registered_callback_url 已转发到本地验收后端。故不能再仅凭生产域名断言其实际处理环境为生产；需以请求到达记录确认。

- 当前文件：Shopee 注册路径 `/`，TikTok Shop 注册路径 `/callback`。这些公开路径可以通过显式路径重写映射到本地 OAuth 接口，本轮没有更改文件或转发规则。
- 探测不含 state、code、Token 或用户认证；不跟随重定向，不关闭 TLS 证书校验，也未发起真实授权。
- Windows HTTP 栈握手失败后，改用 Python 标准库 OpenSSL 栈复核：Shopee 注册根路径返回 200 / text/html；TikTok 注册地址仍为 SSL EOF。仅 HTTP 200 不能证明进入授权接口。
- 使用相同非敏感标记 `acceptance-route-probe-70e40a17cf6e` 的 HEAD 检查中，本机 8001 日志只出现直接本地对照请求（探测路径不存在，返回 404，证明日志采集有效）；公网注册地址未出现对应到达记录。
- 在两个域名上补查现有规范 OAuth 路径同样遭遇 TLS EOF，因此不能从这次检查判定全部转发规则失效，也不能确认转发成功。没有绕过 TLS 或以真实授权码探路。
- 当前本地后端监听 `127.0.0.1:8001`，需确认转发使用的目标主机、端口及路径重写是否指向这一个验收进程，而非 8000 共享本地实例、前端 3001 或其他主机的回环地址。

下一步需用户提供脱敏转发规则或目标主机/端口/路径，以完成独立验收目的地的验证。真实凭据托管的前置条件保持不变。
