# 开发A API 平台连接配置变更日志

任务分支：`feature/module-a-api-configuration-ui`
基线 SHA：`a276fa647081ccdec1484473450d2b0828479480`
部署状态：未部署；不得以本地未提交代码作为真实平台证据。

## 变更

- 新增 Shopee/TikTok Shop 后端动态配置 Schema，支持 Sandbox/Pilot/Production、PH/TH/MY、合同版本、最小 scope 和超时边界。
- 扩展 `PlatformIntegrationConfig` 的非敏感配置、凭据状态和乐观锁版本；新增凭据 action 幂等记录。
- 新增 write-only 凭据替换/清除接口；托管不可用时 fail closed，不存在业务数据库明文 fallback。
- 新增 exact permissions 和 tenant/platform/environment/region/config data scope。
- 重建“API数据接入 → 连接配置”列表和编辑页；店铺授权只在配置详情中复用现有入口。
- 新增 `SecretField`：保存状态只显示固定八星号，本次输入可临时显示，提交后清空；清除使用独立二次确认。
- Production 读写同步开关保持禁用，不加入订单、库存、财务、Webhook、定时任务或平台写能力。
- 移植远程 `56ae18e` 的本地文件 custody 能力，但不合并其无关旧基线；保留当前 OAuth、refresh、revoke 与配置 UI。
- 新增项目专用 SSH known_hosts、custody 专用卷挂载和部署前 ACL 门禁。

## 回滚

1. 禁用 live platform network 和 OAuth initiate。
2. 撤销本次制品部署，恢复上一固定应用制品。
3. 数据库 migration 为新增字段和新增幂等表；如需数据库回退，先确认没有新配置/引用元数据，再按发布审批执行 migration 回退。
4. 凭据引用由 custody 单独撤销；不得把原始凭据导出到 SQL、文件或日志用于回滚。

## 移交限制

在远程 Review SHA、固定 artifact/image digest、MySQL 8.4、VM HTTPS、浏览器扫描、托管服务和两平台真实试点验证完成前，不得标记 `connected`，不得设置 `production-enabled`。

## 真实平台运行接线补充（2026-08-08）

- live provider 现在从当前 `PlatformIntegrationConfig` 读取批准的公开应用标识、精确 callback、合同版本及 custody 引用；配置不完整时在网络请求前 fail closed。
- 本地独立文件 custody 被纳入批准后端类型；业务数据库仍只保存引用、掩码、版本、状态和到期元数据。
- TikTok 配置新增必填 `service_id`；前端 OAuth start 使用选中配置的精确 scopes，不再发送固定空列表。
- OAuth start 增加 region、callback 和 scopes 与选中配置的精确绑定校验。
- live OAuth 响应不再向前端返回 state；synthetic 测试路径继续保留测试 state。
- Shopee state 绑定到批准 redirect query；TikTok token 响应兼容官方未返回 `user_type` 的情况。
- TikTok 无平台 revoke API 合同时执行 seller-managed/local disconnect，并撤销 custody 引用，不伪造平台 API 撤销成功。
- 当前验证：Django check PASS；migration drift PASS；后端全量 543 passed / 3 skipped；前端全量 165 passed；production build PASS（1963 modules）；CI guard 与 `git diff --check` PASS。
- 尚未执行真实 callback、authorized shop、最小只读 API、refresh、revoke、MySQL 试点及凭据扫描；两个 capability 继续保持 `pending/mock`。
