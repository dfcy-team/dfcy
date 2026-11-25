# 凭据恢复与闪购排队热修复交接（2026-11-25）

基于未合并的 #634（fix/shopee-ads-renewal-recovery-20261124，4657324528fbda11e95958057ec5ab2cfbadf9d0）。本次无数据库迁移。

## 行为

- 已需人工恢复的续期不再提示仍在自动恢复提交；原不确定交换保护继续生效。
- 闪购发现商城授权无法自动恢复时进入既有失败处理。未写入任务结束并释放同店占用，正常续期等待继续保留业务重试预算。
- 回执查询按非秘密操作元数据筛选，仅完整解密、验证匹配记录，仍拒绝目标密文损坏与重复回执。
- provider 保留云端此前已有的 sync_tasks 调度归属支持，使交付源码与实测生产补丁一致。

## 部署范围与证据

2.44.532 上已发布并验证：credential-recovery-terminal-r1-20261125、custody-operation-contract-r1-20261125、custody-operation-lookup-fast-r1-20261125。后续并发发布的 2.44.533 已只读核对保留全部三条历史及 28 处目标源码。当前 API、托管健康，15 个相关服务运行正常，凭据及闪购队列就绪。

操作回执接口源码已存在于上游 #627，但云端侧车漏部署导致 HTTP 404。此次已补齐侧车；后续统一发版必须同时更新 production-custody-sidecar-1 的 custody_service.py 和 file_custody.py，不能只更新 SaaS 后端。

用户重新授权 SPKJ1PH2 后，原 04:00 批次 15/15、06:00 批次 14/14 自动完成；平台只读回查两场活动均启用且有商品。验证没有再次换令牌、没有重新提交批次。每次侧车切换恢复任务服务前，加密库内容快照一致。保留了同期费用页面静态热修复。

约 1.1 万历史文件上，候选读取耗时 726/678 ms，CPU 721/678 ms，不匹配解密次数为 0。真实后端完整查询实测 7501 → 5452 ms，完整调用包含配置与网络校验成本，不能等同于服务内读取耗时。

验证：140 passed、4 skipped（Windows POSIX 条件），源码对齐后另有 24 项针对性回归通过。扩展检查 18 passed、2 skipped、3 failed，三个失败已在未修改基线相同配置下复现：

- test_http_custody_legacy_replacement.py::test_old_reference_can_only_be_replaced_after_confirmed_absence[]
- test_custody_security_gate.py::test_file_custody_is_rejected_outside_local_debug_mode
- test_custody_security_gate.py::test_non_standard_port_is_allowed_only_for_exact_custody_endpoint

下一实际自动续期周期及生产数据库再次提交失败未主动制造；有限提交恢复和不重复交换通过故障注入回归验证。通用店铺身份诊断入口缺少 shop_id 的限制未在本次放宽，当前闪购业务已独立回查。

## 制品

shopee-credential-recovery-aliyun-hotfix-20261125.zip，SHA256：4b5d0c04114f5f8cd3b035a7c25aafdfc45f3849766aa8952c67508e24e1c663。

完整线上更新记录快照随包交付，本 PR 不复制含同期其他发布内容的整份历史；统一发布时保留已发布记录。控制器为已执行封存记录，不原样重放。新 PR 待审阅，不合并、不分配版本、不正式登记台账。
