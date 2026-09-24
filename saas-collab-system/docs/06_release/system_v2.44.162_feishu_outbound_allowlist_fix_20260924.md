# V2.44.162 飞书出站白名单覆盖修复

## 问题

飞书候选查询被出站安全门拒绝，返回 `OAUTH_PROVIDER_UNAVAILABLE: Outbound host is not approved.`。生产部署清单已批准 `open.feishu.cn`，但数据库中较早的有效运行配置覆盖了环境白名单。

## 修复

- 出站允许主机集合改为合并根部署白名单与数据库有效运行配置白名单。
- 仍只允许精确主机名、HTTPS 和标准 443 端口；未批准域名继续拒绝。
- 不改变飞书凭据、通讯录权限、人员绑定或应用可用范围。

## 验证

```text
python -m pytest tests/test_custody_security_gate.py -q
8 passed, 2 skipped

python manage.py test apps.integrations.tests.test_feishu_api
Ran 13 tests, OK
```

