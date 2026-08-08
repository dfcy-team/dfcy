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
