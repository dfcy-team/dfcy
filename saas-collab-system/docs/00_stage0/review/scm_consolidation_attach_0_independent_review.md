# SC-CONSOLIDATION-ATTACH-0 独立审核

- 日期：2026-08-08
- 审核对象：`scm_consolidation_attach_0_contract.md`
- 结论：`APPROVED_FOR_LOCAL_IMPLEMENTATION`

## 1. 现状判断

仓库现有 `apps.files.AttachmentFile` 只有 tenant、文件名/路径/类型/大小、上传者、业务类型/ID和私有标记。它缺少服务端内容哈希、业务版本、扫描/隔离状态、不可变事件、受控下载、幂等和防 ORM 绕过，不能直接满足供应商交接证据准入。产品图片上传中的少量魔数检查也不是通用供应链附件安全聚合。

合同选择扩展 files 领域而不是让 consolidation 保存二进制或任意 URL，边界正确；上传完成与业务提交分离、扫描 fail-closed、服务端反查绑定以及双端兼容门禁符合本系统融合要求。

## 2. P1 审核项及关闭结果

1. `P1-001` owner 伪造：owner、tenant、business object/version 全由服务端派生，上传 DTO 不接受，关闭。
2. `P1-002` 扫描前提交：uploaded/scanning/quarantined 不可提交，扫描不可用不得 fail-open，关闭。
3. `P1-003` 旧发布版本重绑：业务绑定不可变，旧版本证据不得静默复用，关闭。
4. `P1-004` 私有对象越权下载：应用层逐次授权、短时票据、404 防枚举、禁止 storage key 外泄和下载审计已冻结，关闭。
5. `P1-005` 微信双端格式差异：仅准入 JPEG/PNG，HEIC 转换后仍执行服务端魔数、解码和像素验证，关闭。
6. `P1-006` 删除覆盖历史：提交后保留，更正使用新资产、supersede 和 append-only 事件，关闭。

## 3. P2 决定

- `P2-001 OCR/AI 自动识别`：延期，不得把识别结果当收货事实。
- `P2-002 视频/PDF/Office`：延期，首期仅 JPEG/PNG。
- `P2-003 跨租户内容去重`：拒绝，避免 hash 侧信道和数据治理问题。
- `P2-004 EXIF 原件保留`：默认剥离；独立审批后方可加密保留。
- `P2-005 断点续传`：接口可预留但首期非必需；弱网使用有界重试和幂等。

## 4. 编码准入

六项 P1 已在合同文本中关闭，允许进入 `SC-CONSOLIDATION-ATTACH-1` 本地模型、存储抽象、扫描状态机和 MySQL 门禁。

以下仍不准入：交接证据上传 API、供应商 Web/小程序入口、生产对象存储或扫描账号、自动收货/ready/shipped、任意 URL、公共桶或长期下载链接。

ATTACH-1 完成独立代码审核和 MySQL 并发、ORM 绕过、恶意文件门禁后，才能申请 ATTACH-2 API 阶段。
