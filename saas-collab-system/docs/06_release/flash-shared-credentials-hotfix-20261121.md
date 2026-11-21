# 闪购共用凭据热修复 PR 交接

本文件是源码与 PR 交接记录，不是正式热修复台账。用户已授权创建 PR；正式业务验收与版本登记仍由发布流程确认。

## 问题与改动

百世配置加入当前生产配置后，旧闪购进程不识别 best_ecapi，整份运行配置被判无效，托管凭据回退为拒绝后端。随后托管或续期等待又被计入闪购核对次数，可能导致未发送平台请求就耗尽重试预算。

- 补齐百世配置字段兼容，保留默认未批准与未知字段拒绝行为。
- 闪购和 Shopee 通用只读客户端共用凭据读取与有效期判断，续期继续由现有凭据队列负责。
- 凭据续期、配置不兼容、托管不可用与引用缺失显示明确原因；等待不消耗业务核对或重建次数，不触发清理和重复写入。凭据恢复后继续原任务。
- Worker、Beat 启动检查有效生产配置、托管后端和必要文件；Django 增加 integration_credentials 部署检查标签。
- verify_runtime_consistency.py 动态检查主 API 和所有 production-celery-* 进程的公共模块、有效版本、托管后端与启动监听器。部署控制器已强制执行此门禁。

各业务原有授权范围、签名、限速、写入保护及原时段清理流程保留。无模型迁移。

## 依赖与累计候选

本 PR 基于 #613 的 fix/weekly-flash-recovery-20261120，基点 556857464507b1cfb99f1c8719ba9b80556ac3b9，只提交本次增量。

核对时 #622（release/v518-cloud-reconciled-20261121）已经包含相同的 credential_access.py、IntegrationsConfig、CredentialWait 与 ShopeeReadonlyClient._request。其他累计改动使 provider.call、engine.run_step 和部分文件整体不再完全相同，不能据此宣称本 PR 全部已纳入，也不要整文件覆盖或直接重复 cherry-pick。由统一发布方逐段核对；本次不修改该冻结候选。

## 验证

本 PR 隔离工作区复跑：120 passed，2 skipped；跳过项需要真实数据库行锁。SQLite、内存 broker、模拟平台测试不使用业务数据库或真实密钥。覆盖五轮凭据等待后恢复、重试预算保持、准备写入遇凭据故障后只创建一次、配置错误安全分类、启动拒绝及遗漏进程门禁。

已上线核心函数与本 PR 通过 AST 对比一致。云端热修复批次 credential-unification-r1-20261121：
- 主 API、通用后台、凭据续期、闪购、Beat、视频等共 13 个进程接受有效配置版本46；共用模块 SHA256 为 7d9361f46fbcc795de426f6df10bb61c4de109ce98668893af70cb47a07c74b8。
- 闪购及通用只读客户端使用同一个托管后端，真实只读请求均成功，约1.3秒、1.4秒；Django 部署检查通过。
- 2026-11-21 北京时间17:16发起的15店手动批次，于17:46:36完成，15成功、0失败；期间429等待自动恢复，6条按接收人汇总的通知记录为“飞书已接收”，不等同于人工已读。
- 之前两个15店同步批次随后均全部完成，历史失败批次没有被重跑。

未宣称全量 CI 或真实行锁并发验收通过；两个旧 custody 安全测试在修改前的独立快照基线同样失败，未扩展本 PR 处理。

## 发布与回滚

热修复包 flash-credentials-aliyun-hotfix-20261121.zip，SHA256：
f918baf7342060f0250f56c87c50a6e1eafdb36bd80af9bf9ff3517fd94f1389。

统一打包必须同时纳入公共模块、apps 启动注册、闪购和只读调用端，不只更新 API。发布后在 Docker 主机运行 backend/scripts/verify_runtime_consistency.py，并在服务内运行 python manage.py check --deploy --tag integration_credentials。

云端保留各服务原容器及 compose 快照。回滚代码必须保留当前业务数据；部分旧进程存在配置兼容问题，不能只恢复旧容器就宣布功能已恢复。本次 PR 不触发部署、业务任务、通知发送、正式登记或版本号变更。
