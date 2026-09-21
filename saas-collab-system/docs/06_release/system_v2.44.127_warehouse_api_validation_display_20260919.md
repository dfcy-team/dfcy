# V2.44.127 仓库 API 校验状态显示修复

## 版本登记

- 登记版本：`V2.44.127`（候选，未部署）
- 目标父版本：`v2.44.126-deployed`
- 发布前必须再次核对虚拟机运行版本、双账本、主分支 SHA 与最新 deployed 标签一致；若 `V2.44.126` 未成功部署或序号已被占用，停止发布并重新编号。

## 问题与修复

- 仓库档案列表序列化未传入请求上下文，导致授权数据范围无法按当前用户解析，已验证授权被错误显示为“未配置”。
- 仓库 API 接入弹窗完成授权、刷新或只读校验后，列表未监听变更事件，页面继续展示旧状态。
- 列表接口现在携带请求上下文；弹窗状态变化后会重新加载仓库列表。

## 变更边界

- 后端：`backend/apps/masterdata/views.py`。
- 前端：`frontend/src/views/masterdata/WarehouseMasterList.vue`。
- 回归：`backend/tests/test_subject_api_access.py`、`frontend/tests/warehouse-api-binding-closure.spec.js`。
- 无数据库迁移，无新菜单、路由或权限；菜单与路由数量保持 `104 / 136`。
- 不修改仓库授权、凭据、Token、接入配置、同步任务或库存事实，仅修复已有状态的读取和刷新显示。

## 验证记录

- 前端仓库 API 接入、表单与弹窗定向测试：`42 passed`。
- 后端仓库授权、凭据与数据范围定向测试：`34 passed`。
- 本地后端健康检查：HTTP `200`。
- 本地有效授权 `THCS` 的列表序列化结果为 `api_validation_status=verified`；没有授权的仓库保持 `unconfigured`。

## 发布与回滚

- 仅允许从成功部署的 `v2.44.126-deployed` 创建干净候选，移植上述精确改动并重新执行完整门禁。
- 通过受控 GitHub Actions 构建不可变镜像、部署和验收；部署成功后才允许登记双账本并创建 `v2.44.127-deployed` 标签。
- 回滚到 `v2.44.126-deployed` 对应镜像；本版本无数据库变更，不执行数据回滚。
