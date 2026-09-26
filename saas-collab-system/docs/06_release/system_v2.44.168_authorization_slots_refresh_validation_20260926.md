# V2.44.168 授权槽隔离与自动续期校验

## 版本登记

- 登记日期：2026-09-26（Asia/Shanghai）
- 状态：`REGISTERED_FOR_CONTROLLED_RELEASE`；不是部署成功证明
- 发布通道：受保护 PR、CI 与 Developer A Production Release 虚拟机功能发布通道
- 当前已部署基线：`V2.44.166`；`main` 与 `v2.44.166-deployed` 均指向 `5c9a5189156c4aba08485d80874732ea9f84cea0`，生产发布运行 [36204989696](https://github.com/dfcy-team/dfcy/actions/runs/36204989696) 返回 `PRODUCTION_DEPLOY=PASS`
- 计划前序版本：`V2.44.167` 由 [PR #223](https://github.com/dfcy-team/dfcy/pull/223) 登记，当前尚未合并或部署；本候选必须等待其实际合并、受控部署和账本闭环，再对齐最终主干并核定是否仍使用 V2.44.168
- 最终发布 SHA：以本 PR 实际合并到受保护 `main` 的提交为准，不以候选提交代替
- 数据库迁移：`integrations.0033_authorization_api_type_slots`；本批无菜单或路由变更

## 增量范围

1. Shopee 同一店铺的商城与广告 API 授权使用独立槽位，保留既有 marketplace 槽位键，迁移已有非 marketplace 授权键，避免两个授权互相覆盖。
2. 自动续期分为保存新令牌与最小只读校验两阶段；只有后者成功才记录 `automatic_refresh=success`。进程中断后从新令牌校验阶段恢复，不重复调用刷新接口。
3. 极风 WMS 以绑定仓库库存接口、`pageSize=1` 验证；Shopee/TikTok 验证绑定店铺；Lazada 以单页订单列表验证。
4. 仅网络异常按 2、5、15 秒重试只读验证；401/403 和业务/响应格式错误不重试。验证失败保留新令牌引用、标记 `AUTO_REFRESH_VALIDATION_FAILED`，暂停关联同步任务并创建脱敏同步异常；人工重新授权后可恢复。

## 候选验证与发布闸门

- 授权、自动续期、极风及 Lazada 扩展回归：80 passed、1 skipped；`manage.py check` 与 `makemigrations --check --dry-run` 均通过；`git diff --check` 通过。
- V2.44.166 主干的前端构建通过；本批未修改前端。PR #223 若改变菜单或路由，以其实际合并后的 CI 快照为准。
- 发布前再次确认 V2.44.167 已完成部署、V2.44.168 未被其他标签、PR 或账本占用，且主分支、虚拟机运行版本、镜像摘要及回退点一致。必须等待本 PR 更新后的 CI 与审批，再从最终合并 SHA 构建不可变镜像并受控部署。
- 部署后核对迁移、六个生产容器健康、只读通路与实际生产版本；三个真实仓库尚未重新授权，应列为业务验收，不把本地 `local_live` 的空 Celery Beat 计划带入生产配置。
- 只有部署与业务验收通过后，才创建 `v2.44.168-deployed` 标签并登记生产账本；不能将候选 SHA 登记为生产 SHA。
