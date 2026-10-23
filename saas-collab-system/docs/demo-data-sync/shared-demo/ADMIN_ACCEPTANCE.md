# 8443 共享 Demo：管理员首批验收候选方案

状态：代码候选已完成定向测试；生产专用客户端已创建并停留在待审核、禁用状态，凭据仅保存在内网服务器私有目录；未部署新服务、未拉取生产数据、未切换 8443。

用户已于 2026-10-23 批准专用客户端范围，确认出口 IP 固定，并指定 root 创建、wudy 审核。已通过受控管理通道调用原有创建入口（保留权限检查、序列化验证、事务及审计），创建客户端 ID 3，未调用审核或启用入口。此授权不等于业务系统中的独立审核记录：现有 `client_review` 明确拒绝创建人或配置修改人审核自己的客户端，wudy 仍需自行审核。凭据已校验送达 VM `/opt/saas-demo-sync/private/readonly-client-20261023.json`（0600），生产临时副本已移除。有效期至北京时间 2026-10-30 18:33。无密钥回执见 `pending-client-receipt-20261023.json`。

wudy 操作入口：`https://xtsy.dingfengchuangyu.com/integrations/ai-open-api`，找到 `shared-demo-admin-acceptance-20261023`（ID 3），核对十资源、出口 /32 和有效期后审核通过。启用是单独步骤；不要旋转密钥或修改范围，否则服务器私有配置需同步更新/重新审批。

## 已确认边界

用户选择“先仅管理员验收，再开放指定开发账号”。初始白名单为现有内网管理员 ID 1（tenant 1）；新库只保留该管理员，现有 40 个账号及旧业务数据留在 `saas_collab_pilot`。不要复制旧库后直接开放全部账号。

2026-10-23 只读探测证据见同目录 JSON：VM 现有业务库为 `saas_collab_pilot`，存在运行中的 Celery / beat 容器；真实平台开关关闭。阿里云没有专用 Demo 客户端，不能借用现有两个内部客户端。新 VM 192.168.2.22 尚不可连接，本阶段以 192.168.2.10 同机隔离服务为候选。

## 数据及授权申请

申请单独的生产只读客户端：tenant 1；仅现有快照十类资源；不授予财务、广告、退款、采购、SSO 或凭据托管权限。建议有效期 7 天、每页 100 条、每分钟 60 次，最终由生产授权流程确认。2026-10-23 从 VM 通过证书校验访问 `https://xtsy.dingfengchuangyu.com/api/internal/health/` 返回 200，生产 nginx 对应请求观察到出口 `117.28.111.25`。候选 CIDR 为 `117.28.111.25/32`，固定 NAT 仍需确认，不能用 0.0.0.0/0。精确申请参数见 `client-authorization-proposal.json`，网络证据见 `network-preflight-20261023.json`。

首批建议业务日期 2026-10-22，订单 store 6，库存 warehouse 2。探测确认这两个范围有数据，尚未验证该日最终快照行数。客户端资源授权是租户级，日期/门店/仓库只是 worker 查询范围，并非客户端授权边界。主数据会包含租户内依赖，不代表全部资源都按门店/仓库强隔离。快照不是跨表一致性事务快照；验收需核对清单及金额/数量，不将其用于财务对账。

## 实施顺序及回退

1. 审批专用客户端与出口 CIDR，凭据只注入同步服务私有环境；代码及聊天不保存明文。
2. 同机建立独立同步服务及 `saas_collab_sync_shared_demo` 控制库，配置独立私有目录；禁止复用旧业务 worker、beat 或 Redis 队列。
3. 为本批次新建 `saas_collab_demo_shared_<batch>` 空工作库并迁移。通过服务器私有通道复制 tenant 1 与获准管理员 ID 1 的必要身份字段，保持已有身份，不复制其他账号、会话、权限组、业务配置或凭据。导出身份材料只允许服务器受限目录，验收后按发布流程清理。
4. 专用同步服务拉取并脱敏，审阅 manifest、范围、行数及哈希；在新工作库先 dry-run，再执行现有受控 importer。导入进程与共享 HTTP 服务分开，新服务禁止导入接口。
5. 新共享后端使用 `config.settings.shared_demo_snapshot`、`DEMO_SHARED_ADMIN_IDS=1`、独立 MySQL 库、私有绝对路径 `DEMO_SHARED_MAINTENANCE_FILE`。预先创建维护标记，暂不接入 8443。沿用 prod 的 HTTPS、安全 Cookie 及真实密钥要求。
6. 维护期间运行只读检查（以下占位符必须替换为已审阅实值）：

```sh
python manage.py check_shared_demo_snapshot \
  --settings=config.settings.shared_demo_snapshot \
  --bundle /private/reviewed-batch \
  --tenant-id 1 --admin-id 1 \
  --manifest-sha256 <reviewed-64-character-sha256>
```

只有 `SHARED_SNAPSHOT_REVIEW_READY` 才可进入人工预览。该结果验证文件完整性、迁移状态、行数记账、导入映射目标存在性/唯一性/租户归属、事实表租户关系及账号/外联门禁，不声称逐字段一致性或完整跨库结构比对，也不执行切换。

7. 在独立 HTTPS 预览入口按发布流程解除维护，验证管理员登录与数据；验证普通账号、匿名 API、机器令牌及后台入口均不能访问；重新启用维护后交出具体后端镜像、数据库、路由差异、检查报告及回退步骤。
8. 由受控发布流程确认最终切换：暂停写入并排空请求，只将 8443 上游指向验收的新后端，再解除维护。旧后端和旧库保留；旧业务 worker 不得连接新库。失败时恢复旧上游及旧库，禁止将新库写入反向合并到旧库。

开放指定开发账号是后续阶段：当前门禁要求内部超级管理员，不能通过把开发者升级为超级管理员来绕过。届时另做显式账号白名单与权限范围设计、测试及版本登记。

## 本阶段验证

`python -m pytest apps/demo_sync/tests/test_shared_gate.py apps/demo_sync/tests/test_shared_readiness.py --ds=config.settings.settlement_test --nomigrations -q`：17 passed（包含真实 ORM 的映射损坏拒绝测试；本批无迁移变更）。

关系检查查询已按实际模型编译验证：订单明细通过 `sales_order__tenant_id` 继承租户。本地既有合成 MySQL 工作库执行只读检查：4 条事实源/目标一致，租户关系异常 0；由于该库是普通合成用户而非获准超级管理员，检查按预期拒绝，见 `local-mysql-negative-acceptance.json`。旧测试库因缺迁移也按预期被阻断。尚未执行新共享服务的真实源数据导入、HTTPS UI 联调或 VM 部署，不能登记为上线完成。
