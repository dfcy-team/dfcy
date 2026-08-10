# SC-CONSOLIDATION-ATTACH-0 供应商交接凭证与附件安全合同

- 日期：2026-08-08
- 状态：`FROZEN_APPROVED_FOR_LOCAL_IMPLEMENTATION`
- 上游：`SC-CONSOLIDATION-0/1`
- 环境：仅本机合同冻结；不连接生产对象存储，不开放上传入口

## 1. 操作者与目标

供应商通过 Web 或微信小程序为本人所属的散货箱分配提交交接照片；内部采购、物流或收货人员在既有 SaaS 权限和 DataScope 下核验。目标是让“谁、何时、为哪个发布版本和物理箱提交了什么证据”可验证、可追踪、不可用任意 URL 冒充。

本能力标记为 `[U 通用]` 受控私有附件核心；微信 Android/iPhone 拍照、压缩与 HEIC 转换属于 `[P 部分通用]` 客户端适配。

## 2. 权威边界

- `files` 附件聚合是文件元数据、扫描状态和存储引用的权威源。
- `consolidation` 只保存已经准入的 `evidence_id` 与提交事件，不保存二进制、客户端路径或外部 URL。
- packing/consolidation 的 tenant、supplier、allocation、box、发布版本由服务端反查，客户端不得声明这些权威字段。
- 对象存储只保存私有二进制，不承担业务授权；数据库授权失败时不得仅凭 storage key 下载。

## 3. 最小附件聚合

新增受控资产 `ControlledAttachment`（可扩展现有 files app，但不得直接复用现有弱模型作为已准入证据）：

- 身份：`id/attachment_no`、`tenant_id`、`owner_type`、`owner_id`。
- 业务绑定：`business_type=consolidation_handover`、`business_id=allocation_id`、`business_version=released_version`。
- 文件：原始文件名的安全显示值、规范扩展名、服务端检测的 `media_type`、`byte_size`、`sha256`、不可猜测 `storage_key`。
- 安全：`scan_status`、`scan_engine/version`、`scanned_at`、`rejection_code`。
- 生命周期：`uploading -> uploaded -> scanning -> accepted|rejected|quarantined -> superseded|deleted`。
- 审计：`created_by_type/id/channel/at`、`accepted_at`、`superseded_by`、保留策略版本。

约束：

- `(tenant, sha256, business_type, business_id, business_version)` 可用于同内容重放识别，但不得跨 tenant 去重或暴露命中情况。
- `storage_key` 全局唯一；上传成功后内容字段和业务绑定不可修改，纠错通过追加新资产并 supersede。
- `accepted` 必须同时具备非空 sha256、可信 MIME、合法大小、扫描通过和完整业务绑定。
- QuerySet `update/bulk_update/bulk_create/delete` 不得绕过领域服务；状态历史和安全事件 append-only。

## 4. 文件准入策略

首期只允许真实图片：JPEG、PNG；HEIC/HEIF 由客户端或受控服务转换为 JPEG 后上传，服务端仍按魔数解码验证，不信任文件名或 Content-Type。默认单文件上限 10 MiB、最小 1 byte、每次交接最多 9 张；具体数值以配置版本记录。

必须执行：

- 规范化文件名，移除路径、控制字符和活动内容；存储 key 不使用原始文件名。
- 校验魔数、解码能力、像素上限和压缩炸弹；拒绝 SVG、HTML、脚本、可执行文件和多态文件。
- 计算服务端 SHA-256；客户端 hash 只能作传输提示。
- 上传至隔离区后扫描；扫描失败、超时或引擎不可用均不得变为 accepted。
- accepted 前不得被业务提交或普通用户下载；quarantined 仅安全管理员可处置。
- EXIF 默认剥离定位和设备隐私信息；若业务确需保留原始 EXIF，必须另行审批、加密和限制读取。

## 5. 上传与提交工作流

1. 客户端请求上传会话；服务端重新鉴权 tenant、supplier binding、allocation 所属供应商、released 状态和 capability。
2. 服务端签发短时、单对象、单用途上传凭据与 upload token；不得接受客户端自选 storage key。
3. 客户端上传后调用 finalize；服务端读取对象实际大小、计算 hash、检测媒体并进入扫描。
4. 扫描通过后资产变为 accepted；客户端轮询或读取状态。
5. `submit-handover` 只接收 accepted 的 evidence IDs；服务端再次核对 tenant、owner、allocation、box 和 released_version，并在同一业务事务内写 allocation 状态及 append-only 事件引用。

上传、finalize、submit-handover 是三个独立幂等作用域。相同键、主体、通道、动作、资源和请求 hash 重放原结果；任一不同返回 409。上传完成不自动提交交接，提交交接仍需供应商人工确认。

## 6. 权限、DataScope 与防枚举

- 外部供应商不分配内部 Permission；使用有效 supplier binding 与 `supply.consolidation.handover.submit` capability，只能访问自己的 allocation 附件。
- 内部查看随 `supply.consolidation.view` 的完整合法 DataScope；收货核验随 `supply.consolidation.receive` 重新鉴权，view 不替代 receive。
- 附件详情和下载对越权、跨租户、跨供应商对象统一返回 404；不得暴露附件是否存在、hash 是否重复或扫描细节。
- 下载使用短时一次性或短时签名 URL，经应用层重新授权后签发；响应禁止公开缓存，并记录下载审计。
- DTO 不返回 storage key、磁盘路径、扫描引擎内部信息、上传者内部用户 ID 或其他供应商信息。

## 7. 状态与业务规则

- 只有集货单 released 且 allocation 为允许交接的状态时才可创建上传会话，最终状态集合由 consolidation 状态机冻结。
- 只有 accepted 且绑定当前 release version 的证据可提交；旧发布版本证据不能静默复用。
- 首期至少 1 张 accepted 图片才允许首次 submit-handover；追加或更正只能产生新版本/新事件，不覆盖原证据。
- `handover_submitted` 后证据进入法定/业务保留，不允许供应商删除；撤回必须由受控异常流程追加原因和事件。
- 收货人员看到的是提交时冻结的 evidence 引用集合；后续 supersede 不改写历史事件。

## 8. API 合同边界

拟定路由（本阶段不实现）：

- `POST .../assignments/{allocation_id}/attachments/upload-sessions/`
- `POST .../attachments/{attachment_id}/actions/finalize/`
- `GET .../attachments/{attachment_id}/status/`
- `GET .../attachments/{attachment_id}/download-ticket/`
- `POST .../assignments/{allocation_id}/actions/submit-handover/`

所有写请求要求 `Idempotency-Key`；submit-handover 还要求 allocation `expected_version`、当前 `release_version`、非空 `evidence_ids` 和服务端允许的 `handover_method/reference`。

## 9. 微信小程序兼容门禁

- Android/iPhone 分别验证相机、相册、权限拒绝、后台切换、弱网重试、取消、进度和重复点击。
- 统一处理 EXIF 方向、长图/超大像素、JPEG/PNG；iPhone HEIC 必须显式转换或明确拒绝并给出可操作提示。
- 不依赖本地临时路径持久存在；失败重试沿用同一 upload idempotency key，不重复创建业务证据。
- 页面只展示缩略图和安全状态；原图下载需重新授权。地址换行、安全区、中文字体及键盘遮挡沿用既有双端基线。

## 10. 审计、保留与隐私

审计覆盖会话签发、上传完成、扫描结果、accepted/rejected/quarantined、提交、下载票据、下载、supersede 和受控删除。日志不得包含二进制、完整签名 URL、token、storage key、原始 EXIF、完整联系电话或 hash 查询结果。

保留期限必须配置化并由业务/法务在生产前批准；租户删除、主体请求删除与物流凭证保留冲突时走审批和法律保留标记。备份、对象存储、CDN、扫描服务和日志需遵守同一地域、加密、访问和删除政策。

## 11. 错误与降级

- 400：格式、数量、版本或媒体校验失败。
- 401/403：认证、capability 或内部 permission/DataScope 失败。
- 404：对象不存在或不可见。
- 409：版本、状态、幂等或已提交冲突。
- 413：文件过大。
- 422：内容与声明不符、像素/解码/业务规则失败。
- 423：扫描中或隔离中。
- 503：对象存储或扫描服务不可用；不得 fail-open。

后台扫描支持有界重试和死信队列；超时保持 scanning/quarantined，人工可以重扫但不能手工直接改 accepted。

## 12. 验收与停止条件

本地门禁至少覆盖：2 tenant、3 supplier、跨供应商/跨租户下载、同键并发 finalize/submit、旧发布版本、伪造 MIME、损坏图片、超大像素、扫描超时/恶意、ORM 绕过、历史 supersede、Android/iPhone 上传重试。

守护指标：零跨租户/跨供应商泄漏、零未扫描证据提交、零任意 URL、零重复交接事件、零上传动作提前增加 received/shipped。任一失败即停止开放 API 或客户端入口。

## 13. 明确不在本阶段

- 生产对象存储、CDN、扫描厂商选择与账号配置。
- 视频、PDF、Office、压缩包或任意文件上传。
- OCR、AI 图片识别、自动收货或自动异常判断。
- shipment/customs 单证、财务凭证及其他公司货物附件。
- Web/微信小程序页面编码和线上发布。

## 14. 后续波次

1. `SC-CONSOLIDATION-ATTACH-0-R1`：独立安全与边界审核、P1 整改。
2. `SC-CONSOLIDATION-ATTACH-1`：本地模型、存储适配接口、扫描状态机和 MySQL 门禁。
3. `SC-CONSOLIDATION-ATTACH-2`：API、权限、DataScope、三通道 DTO 和幂等实现。
4. `SC-CONSOLIDATION-ATTACH-3`：微信小程序 Android/iPhone 真机上传门禁。
