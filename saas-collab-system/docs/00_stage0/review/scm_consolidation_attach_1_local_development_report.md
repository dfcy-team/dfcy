# SC-CONSOLIDATION-ATTACH-1 本地开发与 MySQL 门禁报告

## 结论

本轮完成了交接凭证附件的领域底座：受控附件、上传会话、扫描/接受状态机、追加式事件账本、服务端派生绑定、幂等重放和 ORM 写入闸门。实现只提供领域服务和本地 fake/in-memory storage/scanner，不新增上传 API、路由、serializer、Web/miniapp 或真实对象存储/扫描连接。

SQLite 定向测试 8 项全部通过；隔离 MySQL 8.4 上 fresh migrate 成功，真实连接并发/约束测试 3 项全部通过。既有 `AttachmentFile` 记录没有被迁移改写。全仓 `makemigrations --check` 仍会报告既有 products 历史迁移漂移，本轮未越权修复。

## 修改范围

- `backend/apps/files/models.py`
  - 新增 `ControlledAttachment`、`AttachmentUploadSession`、`ControlledAttachmentEvent`（以及兼容别名）。
  - 附件绑定租户、supplier owner、allocation、release version，保存 SHA-256、MIME、大小、扫描引擎结果和不可变状态。
  - 上传中 SHA-256 使用 `NULL` 表示未完成内容；完成内容采用跨 MySQL/SQLite/PostgreSQL 可执行的普通唯一约束 `(tenant, sha256, business_type, business_id, business_version)`。
  - QuerySet 的 `update/bulk_update/bulk_create/delete` 及模型 `delete` 均拒绝绕过领域服务的写入；事件记录 append-only。
- `backend/apps/files/services.py`
  - 新增 upload session、finalize、scan start/result、accept/reject/quarantine、supersede 等领域动作。
  - 只接受服务端生成的 storage key；限制 1 byte–10 MiB、JPEG/PNG magic、Pillow 解码及 40M 像素上限；scanner/storage 通过协议注入，默认实现为内存 fake。
  - 每个动作写入租户全局幂等事件；同主体同 key 同 payload 返回原结果，异 payload/主体/动作返回冲突；MySQL 1205/1213 映射为可重试领域冲突。
  - 扫描结论只能来自注入 scanner；caller 声明 `passed/quarantined/engine` 会被拒绝，scanner 异常、缺失或返回非法结果统一 fail-closed 为 quarantined。
- `backend/apps/consolidation/models.py`、`backend/apps/consolidation/migrations/0004_consolidationboxallocation_evidence_ids.py`
  - `ConsolidationBoxAllocation.evidence_ids` 为排序、去重、最多 9 个正整数的 JSON 集合；迁移保守解析旧 scalar/JSON `handover_evidence_id` 回填，legacy 列仅保留首 ID 兼容。
- `backend/apps/files/models.py`
  - accepted/superseded/deleted 的不可变元数据和历史状态以数据库原记录为准；accepted 仅允许受控 supersede，禁止内存先回退状态再保存绕过。
- `backend/apps/files/migrations/0002_controlledattachment_attachmentuploadsession_and_more.py`、`0003_remove_controlledattachment_uniq_controlled_attachment_content_binding_and_more.py`
  - 仅创建附件领域表、索引、唯一/检查约束；未回填或改写旧 `AttachmentFile`。
- `backend/apps/consolidation/services.py`、`backend/apps/consolidation/migrations/0003_alter_consolidationevent_action.py`
  - 增加领域入口 `submit_consolidation_handover`：在同一事务中锁定 consolidation/allocation/evidence，校验 accepted 状态、租户/供应商、allocation 和 release version，保存完整 evidence ID 列表并追加 `HANDOVER_SUBMIT` 事件。该入口不改变 shipped 计数。
- `backend/tests/test_sc_consolidation_attach_1_local.py`
  - 覆盖 scan-gated 提交、非法 magic/quarantine、跨租户/供应商隔离、supersede、幂等冲突、scanner fail-closed、accepted 历史回退和 9 项证据集合冻结及 ORM 闸门。
- `backend/tests/test_sc_consolidation_attach_1_mysql.py`
  - 覆盖真实 MySQL 同 key finalize/scan 并发、handover submit 并发重放、唯一事件和 ORM 绕过约束。

## 迁移与约束策略

`files.0002` 创建三张新表。随后 `files.0003` 将 SHA-256 改为可空并把条件唯一改为普通唯一：MySQL 不支持部分唯一索引，使用 `NULL` 的预上传行可重复，而 finalize 后的非空 digest 在同一租户/业务版本下只能出现一次。所有状态、身份、大小、事件 hash、租户关系约束均保留数据库检查或外键层防护。`consolidation.0003` 仅扩展事件 action choice；`consolidation.0004` 新增结构化 `evidence_ids` 并以可逆 RunPython 保守回填旧 scalar/JSON 值。

定向迁移漂移检查：

```text
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
  .venv\Scripts\python.exe manage.py makemigrations files consolidation --check --dry-run --noinput
```

结果：`No changes detected in apps 'files', 'consolidation'`。全局检查仍显示 products 的既有 `0014` 字段漂移；本轮没有修改 products 迁移或业务模型。

## SQLite 验证

```text
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
  .venv\Scripts\python.exe manage.py check
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: \
  .venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_attach_1_local.py -q --create-db --nomigrations
```

结果：Django check 无问题；`8 passed in 2.76s`。MySQL 测试文件在 SQLite 上按设计跳过 3 项。

## 隔离 MySQL 8.4 验证

门禁使用一次性容器 `sc-consolidation-attach-mysql8`，仅绑定 `127.0.0.1:13311`，未挂载 pilot/sandbox volume、未读取 `.env` 或线上凭据。镜像为本机 `mysql:8.4`，digest：`sha256:c592c15aaf4a1961e15d82eb31ea5987dda862d1c4b1e93424438c0e91dc1f8d`。启动观测：MySQL `8.4.10`、字符集 `utf8mb4`、排序规则 `utf8mb4_0900_ai_ci`、事务隔离级别 `REPEATABLE-READ`。账号和密码为本次容器内临时值，报告不记录密码。

专用库 `sc_attach_gate` 从零执行：

```text
DB_ENGINE=django.db.backends.mysql DB_HOST=127.0.0.1 DB_PORT=13311 \
DB_NAME=sc_attach_gate DB_USER=<local-only> DB_PASSWORD=<redacted> \
.venv\Scripts\python.exe manage.py migrate --noinput
DB_ENGINE=django.db.backends.mysql DB_HOST=127.0.0.1 DB_PORT=13311 \
DB_NAME=sc_attach_gate DB_USER=<local-only> DB_PASSWORD=<redacted> \
.venv\Scripts\python.exe manage.py check
DB_ENGINE=django.db.backends.mysql DB_HOST=127.0.0.1 DB_PORT=13311 \
DB_NAME=sc_attach_gate DB_USER=<local-only> DB_PASSWORD=<redacted> \
.venv\Scripts\python.exe manage.py makemigrations files consolidation --check --dry-run --noinput
```

结果：全项目迁移从零完成（包含 `files.0002/0003`、`consolidation.0003/0004`），check 无问题，files/consolidation drift 为 `No changes detected`。随后真实 MySQL 测试命令：

```text
DB_ENGINE=django.db.backends.mysql DB_HOST=127.0.0.1 DB_PORT=13311 \
DB_NAME=sc_attach_gate DB_USER=<local-only> DB_PASSWORD=<redacted> \
.venv\Scripts\python.exe -m pytest tests/test_sc_consolidation_attach_1_mysql.py -q --create-db
```

结果：`3 passed in 150.64s`（使用 fresh migration test DB；另以当前模型 `--nomigrations` 回归为 `3 passed in 83.84s`）。测试线程在调用前后均执行 `close_old_connections()`，覆盖：

1. 同 key 双线程 finalize 仅生成一个 finish 事件，随后同 key 双线程 scan 仅生成一个 accept 事件，另一请求稳定回放；扫描结果由注入 fake scanner 提供，缺失/异常 adapter 不会 fail-open；
2. 同 key 双线程 handover submit 仅有一个状态转换和事件，allocation 保持 `HANDOVER_SUBMITTED`，packing consumption 仍为 `RESERVED`，不增加 shipped；
3. MySQL 唯一/检查约束和 `ControlledAttachment`、事件 QuerySet 的 ORM 绕过均被拒绝；结构化 `evidence_ids` 迁移在 fresh schema 成功。

测试结束后已停止并移除 `sc-consolidation-attach-mysql8`，临时数据库/容器写层和匿名资源均清理，确认 `13311` 无监听、无残留同名容器或 volume。

## 未覆盖项与残余风险

- 本轮不实现真实二进制 HTTP 上传、对象存储、病毒扫描供应商、附件下载/删除 API、supplier handover evidence API 或 shipment transfer API；后续 API 层必须继续调用本领域服务，不能直接写表。
- 真实 MySQL 门禁构造了同 key 并发竞争，但未专门制造可重复的 1205/1213 死锁；服务层保留映射入口，需在独立压力阶段补充故障注入证据。
- 旧 `AttachmentFile` 仍是通用历史模型，未被自动转换为 `ControlledAttachment`；业务迁移需显式审核后再建立 accepted evidence。
- 全仓 products 模型/历史迁移漂移仍未处理，不能把本轮 scoped migration 检查结果解释为全仓漂移清零。
