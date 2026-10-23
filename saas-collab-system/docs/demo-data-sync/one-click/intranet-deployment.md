# 独立内网虚拟机部署审阅包

2026-10-23 用户选择另一台内网虚拟机承载同步服务。192.168.2.10:8443 仍为原业务实例，本方案不修改该实例数据库、端口或运行配置。用户后续提供目标入口 192.168.2.22:3001；从当前开发机只读检测，3001 和默认 SSH 22 均拒绝 TCP 连接（10061）。有效 SSH 入口、操作系统与证书尚待确定；本文为部署准备，未执行远端安装、迁移或启用。最终入口须配置受信任 HTTPS，不将 HTTP 地址视为允许明文传输凭据。

## 运行边界

新机承载同一候选提交的管理页面、Django API 和单个快照 worker，API 与 worker 共用独立 saas_collab_sync_ MySQL 管理库及私有快照目录。各开发端继续使用个人电脑上的 demo_local_runtime.py 和独立 saas_collab_demo_ 数据库。新机不直连生产 MySQL，不启动业务 Celery/beat，不使用生产 Redis、Django 签名密钥或数据库账号。

新机数据库与快照必须使用持久存储，不沿用合成验收的 tmpfs。容量预算包含管理库、并发采集临时文件、已发布快照、备份及保留周期；按受控小范围试采量测算后设告警。开发端旧库也需配置保留策略，不自动删除 active/previous 或模板库。

建议部署单 API 实例、单快照 worker，HTTPS 入口仅向获准内网网段开放。backend 不直接暴露外网，TLS 反向代理设置 Host 与 X-Forwarded-Proto=https，Django 使用 config.settings.demo_sync_service。前端构建 VITE_USE_MOCK=false、VITE_API_BASE_URL 为空，与 API 同源。健康检查须经受信任 HTTPS 或在隔离网络正确携带代理协议头，不能把重定向当健康成功。

## 管理员准备项

1. 提供新机地址、SSH 受控连接、操作系统、部署目录和服务管理方式；核对不存在将被覆盖的同名实例、数据库和端口。
2. 准备固定候选 SHA 与 CI 结果、独立复核、完整变更清单；容器部署须冻结镜像 digest，经审查后生成专属部署定义，不能套用旧业务 Compose 启动整套业务 worker。
3. 新建独立 MySQL 库和最小权限用户，准备备份／恢复位置。使用单独签名密钥和组织规定的秘密注入方式；参考 intranet.env.example，秘密不进入 Git、镜像、PR 或浏览器。
4. 通过既有审批流程创建生产只读专用 client，限定租户、出口 IP、必要资源及依赖。源地址必须是可信 HTTPS 域名，若使用私有 CA 则注入只读 CA 文件；不关闭证书校验。生产只读 client 密钥及 HMAC 盐只注入内网 worker 所在受控服务环境。
5. 创建受控服务账号及其私有目录。快照目录不是 MEDIA_ROOT、静态目录、公开共享盘；Linux 权限 0700，服务账号独占。预先创建目录属于运维配置步骤，预检不会代为创建或修改权限。

## 安装与预检顺序

在新机独立实例中安装经过审查的同提交制品及依赖，注入配置但保持同步和 worker 开关关闭。先检查迁移计划，再在该独立库运行迁移和权限同步；迁移后确认无待执行节点。权限同步对 administrator 的标准赋权行为须事先审核，不自动给所有开发者授予管理权限。

```sh
# 已选定新机专用环境，禁止在现有业务实例执行
export DJANGO_SETTINGS_MODULE=config.settings.demo_sync_service
python manage.py check
python manage.py migrate --plan
# 审核精确计划、确认独立目标及备份后执行
python manage.py migrate --noinput
python manage.py sync_permissions
python manage.py check_permission_manifest --check apps/permissions/permission_manifest.json
python manage.py check_demo_sync_service --allow-disabled
```

预检仅检查角色、实际连接的 MySQL 库、迁移状态、目录隔离及配置，不访问生产 HTTP，不执行迁移或任何数据库写入。通过不等于生产 client 已审批或真实数据已验收。Windows 原生运行时，工具不能自动证明目录 ACL 私密性，会返回 ARTIFACT_ACL_REQUIRES_OPERATOR_VALIDATION；不能用 --allow-disabled 绕过目录权限检查，需按现场平台另行审查。

内网管理租户与源 client 授权租户必须按已有绑定合同配置；为开发者创建内部账号，仅赋 view/run/download 及菜单权限，并由具备 manage 的管理员创建其负责的环境、店铺／仓库和资源范围。完成配置复核后启用两个开关，import 保持关闭。

```sh
python manage.py check_demo_sync_service
# API 使用项目既有 Gunicorn 运行约定，并经 HTTPS 反向代理接入。
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 2 --timeout 60 --access-logfile - --error-logfile -
# 独立服务进程，以既有服务管理器监督，初期仅一个
python manage.py work_demo_snapshots --poll-seconds 5
```

命令示例不安装 systemd、开防火墙或自动发布。新机具体运行定义、账号及重启策略需在取得主机资料后按现场平台冻结审核。

## 联调与放行标准

先以合成源完成一次新机 HTTPS 登录、权限隔离、自动采集、下载和本地一键导入／回滚。再使用批准 client、明确接收开发者、单店铺／仓库和小日期窗口做受控真实联调，验证实际源资源及依赖授权、源请求量、金额／日期／数量口径、脱敏字段和关联约束；日志只留聚合结果与有限异常样本，不记录明文凭据或经营明细。

开发端一次性配置干净模板、租户／账号映射、内网开发者 JWT 与 CA、固定本地签名密钥、持久私有目录和本机 MySQL。实际更新期间验证业务写入 503、登录续期可用、失败不切库、重复任务拒绝、旧测试修改保留于旧库。完成后才登记“新机实际部署验收通过”。

暂停时先停用环境／client 或关闭同步和 worker；停止快照 worker。代码回退使用原制品，保留新增表和审计；开发端通过回滚入口切回上一库。不自动删表、删库、清理已下载副本或恢复生产数据库。
