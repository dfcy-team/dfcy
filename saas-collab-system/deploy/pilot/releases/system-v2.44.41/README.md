# V2.44.41 开发 B 达人数据增量导入（租户 1）

本目录只提供数据迁移与验收脚本，不改变应用菜单、路由、导航 CSS、权限目录或业务源码。V2.44.41 已于 2026-08-24 在虚拟机租户 1（`pilot`）完成 dry-run、受控增量导入、只读验收和幂等性复跑。

## 发布结果（2026-08-24）

- 导入前备份：`/home/dfcy01/releases/influencers-tenant1-import-20260824/pre-influencers-import.sql.gz`，SHA-256 `dd4539133dd4f9897031e4463bfc92596f99fc6b0d7a7b01682e54a4f1e3d3a9`，`gzip -t` 通过。
- 正式导入：达人 24,122、达人档案 24,122、开发 B 建联任务 196、建联目标 850、样品履约 866、样品明细 1,176、履约状态 1,777、店铺商品 829、SKU 价格快照 25,358。
- 原租户 1 任务 `DRJL480356` 和 `DRJL005573` 均保留；导入后任务总数为 198。
- 自然键重复、孤儿外键和跨租户关联均为 0；名称乱码和空名称均为 0。
- 1,662 个唯一旧 SKU 在当前基础档案中无对应编码，对应 3,812 条价格快照保留业务数据且 `sku_id` 为空，未猜测或误连其他商品。
- 幂等性复跑新增数全部为 0；根页和达人页 HTTPS 状态均为 200。
- 验收报告：`devb-v24441-dry-run-names.json`、`devb-v24441-apply.json`、`devb-v24441-idempotency.json`、`devb-v24441-verify.json`，保存于同一虚拟机发布目录。

## 交接包与范围

交接包为 `D:\开发B达人模块\20260824\influencers-module-incremental-20260824`，来源 V2.44.31。脚本只读取其 `influencers_*` 数据快照，并将数据合并到目标租户，不复制整库。交接包数据文件 SHA-256：

`d09c99912f4ccc10f7c5e09fead47b5860c547b0f677f55ac6b7ea63b814bc5b`

用户已确认当前运用均在租户 1，店铺 ID、SPU、新旧 SKU 编码沿用一致；脚本仍按自然键解析，绝不把源环境主键直接写入目标。

## 安全边界

- 默认 `migrate-devb-influencers.py` 为只读 dry-run；只有同时提供 `--apply` 和完全匹配的 `--confirm-tenant-code` 才允许写入。
- 目标租户只能由 `tenants_tenant.code` 唯一解析；源 `tenant_id` 仅用于 staging 过滤，目标写入统一替换为解析后的租户 ID。
- 用户/负责人通过登录用户名映射；平台通过租户内平台编码（可用映射文件改名）；店铺通过租户内店铺编码并校验其 `platform_id` 对应的租户内平台编码；达人平台字段写入解析后的目标平台编码，不把平台主键当作跨环境映射；SPU 通过租户内 `spu_code` 或 `legacy_spu_code`；SKU 先按新 `sku_code`、再按旧 `legacy_sku_code`。无法唯一匹配的记录跳过并报告，不猜测绑定。
- 目标主键永不写入；所有插入列显式排除 `id`，使用自然键 `INSERT ... ON DUPLICATE KEY UPDATE id=id`，保留目标已有记录（包括原有测试建联任务）。
- 不包含 `DELETE`、`TRUNCATE`、`DROP`、清表或关闭外键检查的正式库操作；每个批次独立提交，异常时回滚当前连接中的未提交事务。
- 日志/报告不输出达人联系方式、账号等敏感明文，仅输出计数、原因和有限样例。

## 1. 建立 staging（不触碰正式表）

在可访问数据库的受控主机上设置数据库凭据和数据文件。脚本会校验数据包 SHA-256；目标数据库和 staging 数据库必须不同。已经有非空 staging 表时脚本会拒绝运行，应改用新的 staging 库名，不得清空旧库。

迁移脚本允许 staging 与正式库使用不同主机、端口、账号和密码。通用 `DB_HOST/DB_PORT/DB_USER/DB_PASSWORD` 仍向后兼容；设置了 `STAGE_DB_*` 或 `TARGET_DB_*` 时，角色专用值优先。目标库实际 schema 名为小写时必须按数据库返回的精确大小写传入，不能把 `saas_collab_pilot` 改成大写；账号需分别使用 staging 的 `INFLUENCERS_MIGRATOR` 和正式库现有应用账号。

```bash
# 下面 DB_* 仅供建 staging 脚本使用；它必须拥有创建/写入 staging 的受控权限。
export DB_HOST=127.0.0.1
export DB_PORT=3306
export DB_USER='staging 建库受控账号'
export DB_PASSWORD='从凭据系统注入'
export TARGET_DB=saas_collab_pilot
export STAGE_DB=saas_collab_influencers_stage_20260824
export DATA_DUMP=/secure/influencers_data_34.sql.gz

bash prepare-staging-devb-influencers.sh
```

源 SQL 只被改写为明确的 staging 库限定名。源主键和源外键只存在 staging，后续由迁移脚本重新解析。

## 2. 准备映射文件

映射文件为 UTF-8 CSV，首行为对应表头，不要提交到 Git 或放入聊天记录。推荐先用全量显式映射；只有人工确认过的源账号 ID 才可使用 `--source-admin-ids` 便利参数。

`user-map.csv`

```csv
source_id,target_username
47,root
```

`store-map.csv`

```csv
source_store_id,target_store_code
13,TK-KJ-3-PH
```

`platform-map.csv`（源/目标编码相同可省略该文件）

```csv
source_platform_code,target_platform_code
tiktok,tiktok
```

`spu-map.csv`

```csv
source_spu_id,target_spu_code
123,101080028
```

`target_store_code` 必须是在租户 1 的店铺档案中唯一存在的编码；不能只凭相同的数字主键推断。若交接包的送样归属快照已经含唯一 `shop_abbr`，可以在人工核对后用 `--derive-store-map` 自动候选，但仍会对目标店铺编码做唯一校验。

## 3. dry-run（必须先审查报告）

迁移阶段使用角色专用环境变量，密码不会出现在命令行参数中：

```bash
export STAGE_DB_HOST=192.168.2.10
export STAGE_DB_PORT=3306
export STAGE_DB_USER=INFLUENCERS_MIGRATOR
export STAGE_DB_PASSWORD='由凭据系统注入'
export TARGET_DB_HOST=192.168.2.10
export TARGET_DB_PORT=23306
export TARGET_DB_USER='正式库应用账号'
export TARGET_DB_PASSWORD='由凭据系统注入'
```

也可以显式传入 `--stage-db-host/--stage-db-port/--stage-db-user/--stage-db-password` 与对应的 `--target-db-*` 参数；角色参数优先于通用 `--db-*` 参数。不要把密码写进 shell 历史。

```bash
python migrate-devb-influencers.py \
  --stage-db "$STAGE_DB" \
  --target-db "$TARGET_DB" \
  --tenant-code tenant1 \
  --user-map-file /secure/user-map.csv \
  --store-map-file /secure/store-map.csv \
  --platform-map-file /secure/platform-map.csv \
  --spu-map-file /secure/spu-map.csv \
  --report /secure/devb-v24441-dry-run.json
```

dry-run 会读取 staging 和目标库，但不会执行目标 INSERT，也不会修改任何数据。审查报告中的 `skipped`、`issues`、目标自然键冲突以及未匹配的用户/店铺/SPU/SKU；所有必需负责人或店铺无法映射时，应补齐映射后重新 dry-run。

## 4. 受控 apply

只有 dry-run 报告已由业务负责人确认，且数据库已完成可恢复备份，才允许执行：

```bash
python migrate-devb-influencers.py \
  --stage-db "$STAGE_DB" \
  --target-db "$TARGET_DB" \
  --tenant-code tenant1 \
  --user-map-file /secure/user-map.csv \
  --store-map-file /secure/store-map.csv \
  --platform-map-file /secure/platform-map.csv \
  --spu-map-file /secure/spu-map.csv \
  --report /secure/devb-v24441-apply.json \
  --apply --confirm-tenant-code tenant1
```

导入顺序是达人、档案/联系与限制、店铺商品关联、SKU 价格、建联任务/目标、送样/送样明细、履约状态历史、导入批次。派生归属快照、联盟/视频空表不直接导入，应按目标版本的刷新任务重建。重复执行不会因为相同自然键新增重复记录，也不会清除目标已有数据；送样明细在旧 SKU 为空时使用“送样 + 商品/站点 + 商品名 + 数量”的稳定备用键去重。

店铺商品关联的 `product_name` 会按目标租户、映射店铺和平台商品 ID 批量读取 `listings_platformproductdetail`，按平台标题、关联 SKU 商品名、关联 SPU 商品名的顺序回填；目标均无可用名称时才使用源值。源值含 Unicode 替换字符、连续问号或明显乱码时置空，并在报告的 `issues` 中记录计数。SKU 价格快照的 `variant_name` 优先使用目标 SKU 商品名，其次使用目标 SPU 商品名；目标名称目录一次批量加载，不逐行查询。

## 5. 只读验收

只验收正式库时使用 `TARGET_DB_*`。如需同时读取 staging 的源租户计数，追加 `--stage-db "$STAGE_DB"`；脚本会使用 `STAGE_DB_*` 连接，仍不执行任何写入：

```bash
python verify-devb-influencers.py \
  --target-db "$TARGET_DB" \
  --tenant-code tenant1 \
  --stage-db "$STAGE_DB" \
  --source-tenant-id 1 \
  --report /secure/devb-v24441-verify.json
```

验收脚本检查租户范围内各权威表数量、达人/任务/送样/商品关联的自然键重复、父子孤儿和跨租户商品关联。若需确认 V2.44.37 基线中保留的测试任务，可重复传入：

```bash
  --baseline-task-no baseline-task-001 \
  --baseline-task-no baseline-task-002
```

任一重复、孤儿或基线任务缺失都会返回非零退出码；脚本保持只读。

## 静态验证

```bash
python validate-release.py
```

当前验证结果：两个 Python 脚本 `py_compile` 通过，staging 脚本 Git Bash `-n` 通过，禁止清表/删除/关闭外键与目标主键直写检查通过。虚拟机连接、正式导入和部署必须由主流程在完成差异复核及授权后执行。
