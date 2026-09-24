# V2.44.158 飞书用户候选查询与身份确认绑定

## 交付范围

- 身份映射页直接展示当前租户已配置的系统用户，未绑定用户也会出现。
- 每个系统用户可按其已配置邮箱、手机号查询飞书用户候选。
- 候选弹窗展示飞书姓名、部门、脱敏邮箱/手机号和 Open ID。
- 只有管理员人工选择并确认后才创建或更新绑定；姓名不触发自动绑定。
- 确认绑定时后端重新查询并验证候选，拒绝客户端注入候选列表外的 Open ID。
- 同一租户内，同一飞书 Open ID 不允许绑定多个系统用户。

## 飞书开放平台前置条件

- 应用需具备通过邮箱/手机号获取用户 ID 的通讯录权限。
- 如需展示姓名和部门，需具备用户基础信息及部门只读权限。
- 应用可用范围需覆盖目标人员。

## 验证

```text
python manage.py test apps.integrations.tests.test_feishu_api
Ran 10 tests, OK

npm test -- --run tests/feishu-collaboration.spec.js
4 tests passed

npm run build
BUILD_OK
```
