# SC-F2-2 本地 API、权限、DataScope 与原子幂等实现记录

## 1. 实现结论

SC-F2-2 本地后端实现已完成，当前状态：

`IMPLEMENTED_PENDING_SC_F2_2_LOCAL_CODE_REVIEW`

实现严格以 `v2-p1-remediated` 契约及
`PASS_FOR_SC_F2_2_LOCAL_API_IMPLEMENTATION` 复核结论为输入，只在架构员主机本地完成
backend、migration 和自动化测试开发。

本轮没有修改 Vue 网页端、微信小程序页面或请求层，没有连接供应链正式线上系统，
没有导入真实数据，也没有执行同步、双写、切流、发布或生产部署。

## 2. 实现基线

| 项目 | 值 |
| --- | --- |
| 分支 | `codex/scm-f2-packing-local` |
| P1 整改复核提交 | `79aceabd65a88658e45f345156bf3a91b7795eac` |
| API 契约版本 | `v2-p1-remediated` |
| 目标运行时 | Django/DRF + MySQL 8 |
| 开发日期 | 2026-07-29 |
| 开发环境 | 架构员主机本地隔离环境 |
| 生产授权 | 无 |

## 3. 已实现范围

### 3.1 原子 API 幂等

- 新增 `PackingApiIdempotencyRecord`。
- 使用非空 `scope_key`、`resource_key` 和
  `(tenant, scope_key, idempotency_key)` MySQL 唯一约束。
- 保存 actor、channel、action、request hash、HTTP status、response kind、
  JSON 冻结响应或 label snapshot。
- 同 key 不同 actor、channel、action、resource 或 payload 返回
  `IDEMPOTENCY_CONFLICT`。
- API 最外层事务覆盖领域服务、业务事件、操作日志和 HTTP 冻结记录。
- ORM 唯一校验与数据库唯一约束竞争均进入同键重放恢复路径。
- 快照保存失败会回滚领域写入、事件和日志。

### 3.2 权限与 DataScope

- 内部端只使用 5 个已冻结 `supply.packing.*` exact permission。
- scope 只读取实际授予当前 permission 的活动角色。
- ALL、OWN、CUSTOM 多维交集和多 scope 并集已实现。
- DEPARTMENT、非法 CUSTOM 键、空数组、重复、布尔值、字符串 ID 和超限配置安全失败。
- 既有批次的采购单 DataScope 使用全部历史 `PackingBatchOrder`，不按
  `active_guard` 过滤。
- 创建批次的 CUSTOM scope 同时校验 supplier 与全部 order ID。
- 当前标准端点对内部 ALL/OWN/合法 CUSTOM 只执行合法 scope 门禁。
- 内部、供应商 Web、miniapp 与 RPA/错误通道保持隔离。

### 3.3 API

已注册：

- `/api/internal/packing/`
- `/api/external/supplier/packing/`
- `/api/miniapp/supply-chain/packing/`

覆盖批次列表/创建/详情、箱新增/替换/移除、完成/取消、变更提交/审核、
批次/箱标签和当前标准。

移除箱只注册：

`POST batches/{id}/boxes/{box_id}/actions/remove/`

旧 DELETE 路径不可用。

### 3.4 确定性标签

- 仅 `in_progress|completed` 非空箱生成标签。
- 批次一箱一页，箱标签固定一页。
- QR 使用固定字段顺序的非 URL 规范 JSON。
- snapshot 不保存 tenant ID、数据库主键、Token、URL、用户或来源字段。
- 冻结 event time、布局、渲染器、字体摘要、标准、箱内容和 QR payload。
- PDF 使用固定渲染参数；CreationDate/ModDate 使用冻结 event time。
- ETag 为最终 PDF 字节 SHA-256 强 ETag。
- MySQL JSON 往返后仍保持 PDF 字节和 ETag 一致。
- 箱移除后使用原 key 仍可在当前授权通过后重放冻结 PDF。

## 4. 自动化验证

### 4.1 SQLite 本地全回归

结果：

`453 passed, 10 skipped`

10 项跳过均为明确要求 MySQL 行锁或唯一键语义的专项测试。

### 4.2 临时 MySQL 8 专项

使用无持久化卷、仅绑定本机回环端口的临时 MySQL 8 容器执行，结果：

`18 passed`

覆盖：

- API 同键并发创建只提交一条业务结果和一条 API 幂等记录；
- 领域并发创建、不同 key 活动批次竞争；
- 并发箱动作与同键箱动作重放；
- 并发变更审批只应用一次；
- ORM 批量绕过继续关闭；
- MySQL JSON 存取后的 PDF 字节级重放；
- 箱移除后的历史标签重放。

容器在测试后已停止并自动删除，未挂载或保留数据卷。

### 4.3 静态和框架检查

- `manage.py check`：通过。
- `makemigrations --check --dry-run`：无模型漂移。
- Python `compileall`：通过。
- migration 在全新 SQLite 数据库：通过。
- Git whitespace 检查：通过。

## 5. 边界保持

- 供应商能力配置 API 继续排除；只复用已审核领域能力读取。
- 前端和小程序实现未开始。
- SC-F1 `production_completed` 未被 F2 API 推进或改写。
- F3、物流、装柜、发运、照片、视频、对象存储和真实打印机仍不可达。
- 无正式线上数据库、真实微信、通知或第三方平台调用。

## 6. 下一步门禁

下一步只允许：

`SC-F2-2 本地 API、权限、DataScope 与原子幂等代码审核`

审核通过前不得进入网页端/小程序端融合、线上联调或部署。
