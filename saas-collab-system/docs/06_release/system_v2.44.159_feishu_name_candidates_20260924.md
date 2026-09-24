# V2.44.159 飞书姓名候选查询与 Open ID 展示修复

## 修复结论

- 修复系统用户邮箱、手机号与飞书不一致时，候选弹窗只显示“暂无数据”、无法查看 Open ID 的问题。
- 保留邮箱/手机号精确查询；精确查询无结果时，按应用可见部门分页读取飞书通讯录，并以规范化姓名生成候选。
- 系统部门与飞书部门一致的候选优先展示；姓名候选仍必须人工核对并确认，不执行自动绑定。
- 候选弹窗直接展示 Open ID、脱敏联系方式和“邮箱或手机号精确匹配 / 姓名与部门一致 / 姓名一致，需人工确认”等匹配依据。
- 无候选、通讯录权限不足或应用可用范围不覆盖目标用户时，弹窗显示具体原因，不再用空表掩盖错误。
- 通讯录遍历设置 100 个部门、1000 个用户和 20 个候选的单次上限，避免无界查询。

## 飞书开放平台前置条件

- 开通 `contact:user.base:readonly`（读取通讯录用户基础信息）。
- 开通 `contact:department.base:readonly`（读取部门基础信息）。
- 应用通讯录可用范围必须覆盖目标用户及其部门；权限或范围调整后需发布应用版本并由企业管理员审核生效。
- 若还需读取企业自定义 User ID，再开通 `contact:user.employee_id:readonly`；本功能绑定只要求 Open ID。

## 验证

```text
python manage.py test apps.integrations.tests.test_feishu_api
Ran 13 tests, OK

npm test -- --run tests/feishu-collaboration.spec.js
5 tests passed

npm run build
BUILD_OK
```

