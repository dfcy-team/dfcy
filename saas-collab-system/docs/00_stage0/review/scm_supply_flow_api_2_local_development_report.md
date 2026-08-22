# SC-SUPPLY-FLOW-API-2 本地开发报告

## 本轮范围

本轮合并 ATTACH-2、CONSOLIDATION-2、SHIPMENT-2 的本地 HTTP 适配层，并完成主审 P1 整改：

- `apps.consolidation`：内部站点/集货单及箱动作、supplier Web 与 miniapp assignment/handover、受控附件 metadata 入口。
- `apps.shipping`：内部 typed shipment、箱转移与报关/发运/到港/清关/取消动作。
- `config.urls`：注册三通道路由；未修改 Web、miniapp UI 或既有领域表写入口。

所有写请求都委托现有领域服务，携带 `Idempotency-Key`，并对动作使用 `expected_version`。重放返回第一次相同的业务响应，`Idempotency-Replayed` 响应头区分是否重放；异键/异 payload 由领域幂等账本转为冲突。

## 安全约束

内部 API 逐 permission code 检查租户和 DataScope，仅接受 `ALL` 或包含五个完整维度的 `CUSTOM`（supplier、purchase order、packing batch、site、consolidation）；`OWN`、`DEPARTMENT`、缺少维度或未知键 fail-closed。按资源的当前及历史 allocation 快照计算 scope，越权对象统一 404。supplier Web 与 miniapp 只读自身 supplier assignment；miniapp token 不能访问 internal/external 路由，反之亦然。

DTO 对 supplier/miniapp 隐去内部用户、事件 before/after、完整内部 note 与 storage key。附件默认只提供受控 metadata 和状态；download-ticket 本轮明确关闭并返回 503。二进制 `content_base64` 仅在显式 `SUPPLY_FLOW_LOCAL_UPLOAD_ENABLED=true` 的本地测试开关下接受，默认关闭，未引入任意 URL 或生产对象存储。

## P1 整改

- 新增 `ConsolidationSupplierCapability`（迁移 `consolidation.0006`）：同租户/供应商唯一、版本和审计字段，`can_submit_handover` 默认 `false`。内部 `supply.consolidation.manage` 受控入口负责配置；supplier assignment 仍可按 binding 读取，但 Web 与 miniapp 的附件 upload-session、finalize 和 handover submit 写动作均要求该 capability 为 `true`，不复用 packing 的 `can_self_pack`。
- upload-session 首次响应和同键重放均返回由服务端 `SECRET_KEY` 派生的短时 HMAC token。数据库仅保存 SHA-256 摘要；重放在有效期内可稳定重建 token，过期会拒绝继续使用，明文不写入日志或持久化字段。
- download-ticket 当前明确 fail-closed，返回 `503 FEATURE_UNAVAILABLE`，不再生成可预测或泄露摘要的 ticket。supplier attachment DTO 已移除 `sha256`、`business_id`、`business_version` 等内部绑定字段。

## 文件

- `backend/apps/consolidation/models.py`, `services.py`, `migrations/0006_consolidationsuppliercapability_and_event.py`
- `backend/apps/consolidation/api_support.py`
- `backend/apps/consolidation/api_serializers.py`
- `backend/apps/consolidation/api_views.py`
- `backend/apps/consolidation/urls_internal.py`, `urls_supplier.py`, `urls_miniapp.py`
- `backend/apps/shipping/api_serializers.py`, `api_views.py`, `urls_internal.py`
- `backend/apps/files/services.py`（HMAC upload token 与 supplier capability gate）
- `backend/config/settings/base.py`, `backend/config/urls.py`
- `backend/tests/test_sc_supply_flow_api_2.py`

迁移新增仅为 `consolidation.0006` 的 capability 模型/事件 choice；迁移漂移检查中仍存在仓库既有 `products` 历史迁移差异，未越权修改。

## 验证

```text
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: python manage.py check
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: pytest tests/test_sc_supply_flow_api_2.py -q --nomigrations
DB_ENGINE=django.db.backends.sqlite3 DB_NAME=:memory: pytest tests/test_sc_supply_flow_api_2.py tests/test_sc_consolidation_attach_1_local.py tests/test_sc_consolidation_1_local.py tests/test_sc_shipment_1_local.py -q --nomigrations
```

结果：`check` 通过；API2 SQLite 定向测试 `7 passed`；合并运行 API2、attach、consolidation、shipment 四组定向回归共 `28 passed in 5.65s`。`makemigrations --check --dry-run` 仍只报告仓库既有 `products` 迁移漂移，不属于本轮授权范围；`migrate --plan` 无待执行操作。

另使用临时本地 MySQL 8.4 隔离实例完成 P1 门禁：容器 `sc-supply-flow-api2-mysql8`，仅绑定 `127.0.0.1:13314`，镜像 digest `sha256:c592c15aaf4a1961e15d82eb31ea5987dda862d1c4b1e93424438c0e91dc1f8d`；版本 `8.4.10`、字符集 `utf8mb4`、collation `utf8mb4_0900_ai_ci`、隔离级别 `REPEATABLE-READ`。专用库从零执行全量 migration（含 `consolidation.0006`），`check` 通过，`migrate --plan` 无待执行操作；随后 pytest API2（含 migrations）`7 passed in 152.92s`。测试数据库、容器均已删除，13314 端口与同名 volume 无残留；本地账号/密码仅为临时值，未写入仓库或报告。

## 未实现边界与残余风险

- 本轮没有真实二进制上传、第三方对象存储或扫描供应商；扫描接受仍须通过注入 scanner 的领域服务完成。
- shipment 仅 internal 暴露，supplier handover 不包含 shipment 写权限；集货转运由 shipment allocate 领域入口原子执行。
- 本轮 MySQL 门禁覆盖 fresh migrate、P1 capability/HMAC/DTO fail-closed、API2 关键权限/幂等/路由 smoke；尚未覆盖多线程 HTTP 并发及上传扫描器真实故障注入。上线前应在隔离 MySQL 8.4 中补充该矩阵。
