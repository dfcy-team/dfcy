# V2.44.156 飞书凭据保存修复

## 问题

飞书协同“应用连接”保存 App Secret 等调用信息时，凭据托管服务返回 400，系统界面显示 `OAUTH_PROVIDER_ERROR: Platform rejected the request.`。

根因是飞书接口把 `secret_kind` 作为凭据托管元数据键。托管服务按安全契约拒绝键名中含 `secret`、`token`、`credential` 等敏感标记的元数据，导致凭据尚未写入即失败。

## 修复

- 将非敏感用途标签由 `secret_kind` 改为 `value_role`，保留字段角色值，不放宽托管服务安全规则。
- 增加飞书接口断言，确保三类凭据均使用合规元数据且明文不进入响应或业务表。
- 增加真实凭据托管 sidecar 合约测试，验证新元数据可保存、旧违规键仍被拒绝且错误响应不泄露明文。

## 验证

```text
python -m pytest apps/integrations/tests/test_feishu_api.py tests/test_custody_service.py -q
12 passed, 1 skipped
```

跳过项为 Windows 环境不支持的 POSIX 文件权限检查，与本次改动无关。
