# V2.44.54 基础档案安全删除增量发布包

本包以虚拟机当前 V2.44.53 达人模块版本 `37eaa4a3344be9d3a3c6897e6e4936972a429c40` 为父基线，叠加基础档案安全删除提交 `cb022ea3bee8a79e45800632a898afe62d54524a`。

## 范围

- 平台档案、国家信息、店铺档案、仓库档案、供应商档案增加删除入口；
- 后端按当前租户重新定位记录，并检查反向关联和国家/站点编码文本关联；
- 有关联数据返回 HTTP 409，只允许使用原停用流程；
- 无关联数据才允许物理删除，并写入操作日志；
- 分类、属性、颜色沿用既有安全删除入口；
- 不修改菜单、路由、导航 CSS 和权限目录；不执行数据库迁移。

## 发布顺序

1. 将本目录复制到 `/home/dfcy01/releases/system-v2.44.54-cb022ea-20260902`。
2. 将 `v24454-source.tar.gz` 放入该目录并执行 `sha256sum -c source-sha256.txt`。
3. 解压源码，使应用目录为 `reviewed-source/saas-collab-system`。
4. 执行 `./release-v24454.sh --precheck-only`，核对账本、运行镜像、revision、源码哈希和 Compose。
5. 执行 `./release-v24454.sh` 构建、测试、滚动更新并自动运行部署后复核。
6. 技术复核通过后创建 `v2.44.54-deployed`，同步两个受控 mirror 的 canonical ref，再执行 `python3 register-v24454.py`。

## 回滚

执行 `./rollback-v24454.sh` 只会把 backend、Celery、Celery Beat 和 frontend 恢复到 V2.44.53；custody 与 Redis 不重建。该版本无数据库迁移，不需要数据库回滚。
