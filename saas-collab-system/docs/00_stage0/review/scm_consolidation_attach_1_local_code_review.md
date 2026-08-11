# SC-CONSOLIDATION-ATTACH-1 本地代码审核

- 日期：2026-08-08
- 结论：`PASS_FOR_NEXT_CONTRACT_GATE`
- 环境：仅架构员本机；未连接生产对象存储或扫描服务

## 1. 审核范围

审核 `files` 受控附件模型、上传会话、追加式事件、存储/扫描适配器、状态机、迁移，及 `consolidation` 最小交接提交领域入口。API、权限/DataScope 适配、Web、微信小程序和生产基础设施不在本轮。

模型路由：`luna-worker` 负责实现、迁移和测试；主代理负责边界、P1 审核、整改复核与结论。

## 2. P1 整改复核

1. `P1-001 扫描 fail-open`：已关闭。调用者不能再提交 `passed/quarantined/engine` 作为可信结果；公开领域入口只采信注入 scanner 的返回值。未注入扫描器或扫描异常时 fail-closed 为 quarantined，不能 accepted。
2. `P1-002 历史状态不可变绕过`：已关闭。保存时读取数据库原始状态；accepted/superseded/deleted 不得通过先修改内存 state 再保存来回退或篡改文件、绑定和哈希字段。supersede 只能走显式受控转换。
3. `P1-003 证据集合容量与结构`：已关闭。`ConsolidationBoxAllocation.evidence_ids` 使用排序、去重、最多九项的 JSON 集合；`consolidation.0004` 保守回填旧 scalar/JSON，legacy `handover_evidence_id` 仅保留首 ID 兼容。

## 3. 关键不变量

- 旧 `AttachmentFile` 不自动迁移为 accepted 证据。
- tenant、supplier owner、allocation 和 release version 均由服务端派生。
- storage key 全局唯一且禁止 URL；内容由服务端计算 SHA-256 并校验 JPEG/PNG 魔数、解码、大小和像素上限。
- uploaded/scanning/rejected/quarantined 不得提交交接；accepted 证据集合与 allocation 状态在同一事务中冻结。
- 上传、扫描或提交均不会增加 received、ready 或 shipped。
- 事件账本 append-only，QuerySet 直接更新、批量写和删除被领域层拒绝。

## 4. 验证结果

- Django system check：通过。
- `makemigrations files consolidation --check`：无变化。
- SQLite ATTACH-1 定向：`8 passed in 2.76s`。
- MySQL 8.4.10 fresh migrations + ATTACH-1：`3 passed in 150.64s`。
- MySQL 当前模型回归：`3 passed in 83.84s`。
- MySQL 参数：`utf8mb4 / utf8mb4_0900_ai_ci / REPEATABLE-READ`。
- 相关文件 `git diff --check`：通过，仅有工作区 CRLF 提示。
- 临时数据库、容器、匿名卷和缓存已清理；端口 `13311` 空闲。

## 5. 保留边界

- 默认 scanner/storage 仅用于本地隔离验证，不是生产实现。
- 上传 API、下载票据、exact permission、DataScope、防枚举响应与 capability 尚未编码。
- Android/iPhone 的 HEIC 转换、弱网、相机权限和真机显示仍需客户端阶段验证。
- 全仓 products 历史迁移漂移仍是最终仓库门禁前置项，本轮未越权修改。

## 6. 下一步

先执行 `SC-SHIPMENT-0` 发运聚合身份及 consolidation transfer 握手合同冻结；之后进入 `SC-CONSOLIDATION-ATTACH-2 / SC-CONSOLIDATION-2` API、权限、DataScope 与三通道 DTO 独立审核及实现。未通过这些门禁前不得开放供应商上传入口。
