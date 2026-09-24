# 本地极风仓库凭据托管修正

## 范围与原因

仅本地代码及隔离测试。不调用极风接口、不使用真实 Token、不向虚拟机或阿里云发布。

仓库凭据初次保存、首次授权后的 Token 托管、刷新后的 Token 托管三处发送了 metadata.warehouse_authorization_id。加密托管服务的元数据校验拒绝含 authorization 的字段名。HTTP 托管通过公共网络客户端抛出 OAuthFlowError，而保存服务此前只捕获其子类 CustodyError，导致页面误报平台请求失败。

## 最小改动

- 三处托管元数据统一改为 warehouse_binding_id；仍关联同一仓库授权记录。
- 仅在 save_warehouse_credentials 的托管保存调用处捕获 OAuthFlowError（包括 CustodyError），返回固定脱敏提示“仓库凭据加密保存失败，原配置未更改。”
- 不修改数据库字段、API 关联字段、网络错误全局处理或托管敏感词规则；无迁移。
- 保留现有事务。新增失败不残留仓库与授权，编辑失败不修改原档案与授权。

## 验证

使用隔离 SQLite 和禁止外网的测试运行器，凭据均为虚构值。实际调用托管元数据校验器检查三处 payload；模拟托管 HTTP 拒绝及认证失败，核对错误文本脱敏和新增/编辑事务回滚。修改前复现 6 failed / 17 passed。

修改后回归：test_jifeng_warehouse_credentials、test_warehouse_api_binding_closure、test_custody_service、test_custody_security_gate 共 43 passed / 3 skipped（121.63 秒）。三项跳过均为 Windows 不支持的 POSIX 文件权限检查；不计为通过。

确认没有未过期的 pending OAuth 会话后，仅重启本地 8002 后端加载修复；用户页面仍为 3001。没有迁移、重建或清理业务库。

本次测试不代表真实极风授权或库存读取通过；不以“凭据保存成功”代替“平台连通”。
