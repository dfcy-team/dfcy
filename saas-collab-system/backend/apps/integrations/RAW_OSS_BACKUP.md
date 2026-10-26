# 新增 RAW OSS 与配对备份候选

开发基线：VM V306，`19b37da766b0f3251dc738369721820a1209f847`。
本候选未分配发布版本、未部署。发布通道应先合入届时已登记基线并复测，完成版本登记和虚拟机验收后，再安排阿里云发布。

## 范围

启用 `RAW_PAYLOAD_STORAGE_ALIAS=raw_oss` 后，普通页面、Webhook 和联盟订单检查点通过统一 RAW 写入函数保存：gzip 内容先上传并回读校验，数据库保存空 payload、storage alias、object key 和 payload hash。上传或校验失败时不回退为数据库大 payload；联盟检查点在上传后再次检查租约。

历史 inline、广告共享 RAW、raw_local 引用保留原状，读取保持兼容。本次没有历史迁移、数据库清理、schema migration、自动定时任务或生命周期删除。关闭写入开关只影响之后的新记录；已经存在的 OSS 引用仍需保留存储配置和读取凭据。

## 部署配置与验收前提

所有实际写入 RAW 的 backend/Celery 服务必须使用同一登记代码及配置。现有设置支持：

```text
RAW_PAYLOAD_STORAGE_ALIAS=raw_oss
RAW_PAYLOAD_STORAGE_NAMESPACE=<环境固定命名空间>
RAW_OSS_BUCKET=<RAW 原始桶>
RAW_OSS_REGION=us-west-1
RAW_OSS_ENDPOINT=https://oss-us-west-1-internal.aliyuncs.com
RAW_OSS_CREDENTIAL_FILE=<容器内只读凭据文件绝对路径>
```

虚拟机不在阿里云内网时使用对应公网 HTTPS endpoint；实际容器必须进行 SDK 联通验收。凭据文件按现有 PrivateRawOSSStorage 格式提供，不进入 Git、镜像、日志或本说明。

RAW、独立备份及隔离恢复桶应为私有桶、阻止公共访问、AES256。写入代码使用禁止覆盖请求头；桶版本控制必须保持从未开启，不能以“暂停”替代。候选不创建桶、不改变 RAM。各桶权限采用所需前缀下 GET/PUT，不授予 List/Delete。备份与恢复目标桶和凭据需要单独配置，不能复用原始桶作为备份位置。

## 形成同一恢复点

先用现有数据库备份流程取得一致性备份，再将这份文件恢复到独立数据库。额外 Django 数据库别名（示例 `raw_snapshot`）必须由隔离操作环境显式配置；命令拒绝 `default` 以及与 default 同地址/库名的连接。

`--snapshot-confirmed` 是操作人员对“该隔离数据库来自指定备份文件”的确认，不会自动恢复数据库，也不能仅凭文件哈希证明数据库恢复操作。数据库恢复之后停止对隔离库的写入，清单、打包及验收均在同一恢复点上进行。完整 inline/shared 数据随数据库备份保存；外部 RAW 按引用清单单独复制，不扫描或列举桶。

```sh
python manage.py raw_oss_backup manifest --database raw_snapshot --snapshot-confirmed --database-backup /backup/db.dump --output /backup/refs.jsonl
python manage.py raw_oss_backup pack --database raw_snapshot --snapshot-confirmed --database-backup /backup/db.dump --manifest /backup/refs.jsonl --namespace <固定命名空间> --output /backup/package
python manage.py raw_oss_backup verify --package /backup/package
```

清单附带 `.snapshot.json` 绑定数据库文件与清单哈希。打包再次比对隔离数据库引用。包内包括 `database.bin`、`refs.jsonl`、`object_index.jsonl`、`metadata.json`、`objects/`；对象按原 alias/key 保存，按 alias/key 去重。校验包括数据库及索引哈希、压缩字节哈希、解压后的规范 JSON/hash、租户/命名空间、计数及完整路径集合。引用去重与路径索引使用磁盘 SQLite，单个 RAW 压缩/解压上限均为 32 MiB；默认保留 10 GiB 可用空间。

## 独立桶上传与取回

备份配置 JSON 只含 `bucket`、`region`、`endpoint`、`credential_file` 四个字段，后者为受保护凭据文件路径。上传前配置中的 raw_oss 仍指向原始桶；`--source-bucket` 必须与之匹配。冻结已验证本地包，上传期间禁止并发修改。

```sh
python manage.py raw_oss_backup publish --package /backup/package --source-bucket <RAW原始桶> --backup-config /secure/backup-config.json
python manage.py raw_oss_backup fetch --backup-id <返回的32位ID> --backup-config /secure/backup-config.json --output /recovery/package
```

保存返回的 backup_id 到受控备份登记中。工具不列举桶，无法自行找回遗失的 ID。文件按 8 MiB 分块上传并回读，索引上限 32 MiB，`complete.json` 最后写入；失败上传不产生完成标志，不自动清理已写入块。取回校验全部文件后才公布目标目录，任何损坏均失败。上传失败或索引超过上限需要人工处理，不能报告备份完成。

## 隔离恢复验收

从独立备份桶取回包，以包内 `database.bin` 通过既有数据库工具恢复到新的隔离数据库。设置 raw_oss 为独立恢复桶，raw_local 为新的空恢复目录，保持原命名空间及对象 key；绝不能把恢复配置指向正式库、正式 RAW 桶或正式本地目录。`--isolated-target-confirmed` 为操作人员确认，工具只自动比较 OSS 桶名，无法识别任意数据库别名或本地路径背后的物理隔离关系。

```sh
python manage.py raw_oss_backup restore-objects --package /recovery/package --source-bucket <RAW原始桶> --isolated-target-confirmed
python manage.py raw_oss_backup verify-database --package /recovery/package --database-backup /recovery/package/database.bin --database raw_snapshot --snapshot-confirmed
```

恢复对象先校验完整包，再逐个写入并回读，不覆盖对象。部分恢复失败应换用新的隔离目标或人工核对现有对象，不能盲目重跑后声称成功。最终验收须阻断原 RAW 桶访问，仅凭独立备份恢复，再核对引用数量，并通过实际 loader 校验所有 inline/shared/external RAW 的类型和内容哈希。成功返回 `database_reference_matches` 和 `loader_checked_rows` 才能登记此阶段完成；仍需业务抽样回放验收。

## 保留报告

```sh
python manage.py raw_oss_backup retention --packages /backup/package1 /backup/package2
```

固定 30 天，仅报告已提供的本地包清单中过期项和无效包，不删除文件或 OSS 对象、不设置桶生命周期、不定时执行。需要由备份登记维护 ID 和包路径；本候选没有历史 RAW 迁移入口。
