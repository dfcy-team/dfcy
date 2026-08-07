# PR-A2 Marketplace OAuth 与映射回滚指南

- 适用分支：`feature/module-a-marketplace-oauth`（A2-01 至 A2-10，HEAD 见发布说明）；回滚目标基线为 A-PR1 `05308bd`。
- 本 PR 新增迁移 `integrations.0010/0011/0012` 均为纯新增表（oauth_state_session、marketplace_store_mapping、marketplace_product_mapping），不改动任何既有表结构或数据。

## 1. 回滚前提

1. 确认无进行中的 OAuth 发起流程（`oauth_state_session` 无 pending 记录），避免用户悬在授权中途。
2. 确认回滚窗口内无人执行门店/商品映射操作；映射数据均为 synthetic 开发数据，回滚丢弃不影响业务。
3. 备份当前数据库（只读副本），备份文件仅留本地，禁止提交到仓库。

## 2. 数据库回滚

```powershell
# 反向卸载三个新增迁移（顺序 0012 → 0011 → 0010，均为 CreateModel 自动反向）
python manage.py migrate integrations 0009 --no-input
```

- 该命令只删除三张新表与其索引/约束，不影响 A-PR1 的引用托管结构与既有 integrations/sync 数据。
- 回滚不会恢复任何"被删除的凭据内容"——本 PR 全链路不落 raw 凭据，任何真实凭据（如未来接入）必须从密钥托管系统重新下发，禁止从数据库、日志或本地备份恢复。

## 3. 应用回滚

1. 将部署分支/版本回退到 A-PR1 基线 `05308bd`（或 revert 本 PR 的合并提交）。
2. 重启后端服务；确认 `/api/internal/integrations/` 下 oauth、store-mappings、product-mappings 路由随代码移除。
3. 既有 configs / store-authorizations（A-PR1）/ sync-jobs / sync-runs 路由不受影响。

## 4. 本地演练记录

- 在 `db.sqlite3` 副本（`DB_NAME` 环境变量指向副本）完成往返演练：正向应用 `0010/0011/0012` → 反向 unapply 到 `0009` → 再次正向应用，三步全部 OK。
- 工作库未受影响；演练副本已删除。

## 5. 禁止事项

- 禁止手工 DROP/TRUNCATE 新表绕过迁移框架。
- 禁止提交或分发 `db.sqlite3*.bak` 本地备份文件。
- 禁止在回滚后把能力状态改标为 `connected`；回滚后相关能力不存在，状态无意义。
