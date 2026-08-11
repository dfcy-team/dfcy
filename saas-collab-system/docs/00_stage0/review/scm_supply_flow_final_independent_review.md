# SC-SUPPLY-FLOW 最终独立本地审核

- 日期：2026-08-08
- 结论：`APPROVED_FOR_SCOPED_LOCAL_COMMIT_AFTER_USER_REVIEW`
- 审核环境：架构员本机，生产零连接

## 1. 审核结论

散货从采购完工后的路线确认、部分装箱、多批次、多次发货、区域集货、供应商交接证据、拼柜发运、报关、发货、到岸、到仓到清货的本地业务链已形成可执行闭环。柜货仍沿既有柜货路线，本轮没有把散货与柜货状态机混写。

模型、迁移、领域服务、API、权限/DataScope、内部 Web 和供应商微信小程序之间的状态名称、版本和 ID 语义已经一致。只有 shipment dispatch 增加 shipped；附件、交接、集货收货、ready 和消费权转移均不会提前记发货。

## 2. 安全与隔离复核

- internal exact permission 与 supplier binding/capability 分离；OWN/DEPARTMENT 在多供应商聚合域 fail-closed。
- CUSTOM scope 必须在单一配置中完整覆盖 site、consolidation、supplier、order、batch 和 shipment 维度，残缺范围不拼接。
- Web supplier 与 MiniApp token 通道互斥；跨 tenant、跨 supplier 和范围外对象按 404 防枚举。
- 附件只接受服务端派生绑定，扫描 fail-closed；下载票据、生产二进制上传和真实对象存储仍关闭。
- HMAC 上传 token 不存明文，幂等重放可在有效期内重建；supplier DTO 不返回 hash、storage key 或内部业务绑定。
- 其他公司货物明细没有进入本系统权威数据模型。

## 3. 迁移与门禁复核

- migration graph 叶节点包含 consolidation.0006、files.0003、shipping.0002、permissions.0026 和 products.0014，依赖顺序可解析。
- products.0014 只有两个 package_volume DecimalField 精度 AlterField，无 drop、rename 或数据清空。
- 当前 Django check 通过；makemigrations check 输出 No changes detected。
- 最终报告记录的正常迁移矩阵：SQLite 86 passed、MySQL 8.4 86 passed。
- Web 定向 3 passed 且 build 通过；小程序 29 passed 且 validate 通过。
- git diff --check 退出 0；本地临时端口 13308-13315 均空闲。

## 4. 提交边界风险

当前 Git 根工作区包含大量其他阶段、其他模块和未跟踪文件，不能执行 `git add -A`、目录级宽泛暂存或整个工作区提交。供应链提交必须使用逐文件白名单，至少区分：

1. F2 multi/packing/purchasing 投影与迁移；
2. consolidation、controlled attachment、shipping 领域及权限迁移；
3. API2/config 路由；
4. Web 与 MiniApp 客户端；
5. 测试和审核归档；
6. products.0014 迁移门禁修复。

配置共享文件 `backend/config/settings/base.py`、`backend/config/urls.py`、`frontend/src/router/index.js`、`frontend/src/router/menu.js`、`miniapp/app.json`、`miniapp/config/index.js` 可能包含并行阶段修改，提交前必须按补丁块复核，不能整文件盲目归属供应链。

## 5. 未准入事项

- 正式部署、生产数据迁移和生产账号连接；
- 生产对象存储、病毒扫描和下载票据；
- 货代、报关、船司或承运商 API；
- 自动报关、自动发货、自动清货或财务动作；
- Android/iPhone 真机最终验收和正式微信发布。

## 6. 下一门禁

用户完成本次源码与归档复核后，方可进入“供应链精确白名单暂存、独立本地提交与提交后基线确认”。提交前不得处理或夹带上述无关 dirty 变更。
