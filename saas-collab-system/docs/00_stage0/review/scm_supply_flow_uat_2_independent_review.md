# SC-SUPPLY-FLOW-UAT-2 凭据与执行基线独立审核

- 日期：2026-08-09
- 审核对象：`scm_supply_flow_uat_2_credential_execution_contract.md`
- 代码基线：`ca1240d`
- 结论：`APPROVED_FOR_LOCAL_CREDENTIAL_TOOLING_DEVELOPMENT`

## 1. 审核结论

合同把账号激活、凭据交付、人工验收和退出吊销分成独立门禁，未把 UAT-1 的 unusable 占位账号描述成可直接登录账号。固定账号白名单、单账号单角色、最小权限和 supplier binding 可以复用现有 UAT 数据矩阵，不需要建立第二套权限体系。

本轮只批准开发本地凭据工具，不批准直接生成口令或启动人工 UAT，符合“先冻结安全合同、再实现、再独立审核、最后执行”的顺序。

## 2. 安全边界复核

- 明文口令不进入参数、环境变量、Git、日志、报告或业务字段；
- 激活工具默认 dry-run，并复用 UAT-1 的本地 settings、数据库名和 loopback 门禁；
- 临时凭据最长 8 小时，到期、失败或验收结束必须吊销；
- 仓库外凭据文件必须满足当前用户独占 ACL/`0600`，失败时回滚；
- 交付元数据只保留不可逆批次摘要和状态，不保存可逆秘密；
- HTTP、数据库、前端和小程序均限制在本机，生产附件及外部平台保持关闭；
- 证据目录位于仓库外，Git 只接收脱敏索引。

## 3. P1/P2 结论

未发现未关闭 P1。UAT-2 工具实现必须用测试关闭以下潜在绕过，否则不得进入人工验收：

1. 非 UAT 用户、inactive tenant、超级管理员/staff/RPA 激活；
2. 非白名单 settings、远程数据库、非 loopback 服务或 marker 不匹配；
3. 口令经 stdout 捕获、异常、日志、JSON 元数据或文件权限失败泄露；
4. 重复激活延长有效期、过期账号仍能认证、部分失败未回滚；
5. 吊销遗漏账号、Token/Session 或误伤非 UAT tenant。

Windows ACL 的实现和复核是平台专项 P2：若不能稳定证明当前用户独占权限，则首期工具只能采用“交互式逐账号一次性显示且不落盘”模式，禁止用普通文本文件替代。

## 4. 准入决定

批准进入 `SC-SUPPLY-FLOW-UAT-2-1 本地短期账号激活、吊销与凭据元数据工具开发`。编码范围限 management command、独立 UAT credential tooling、定向测试和开发报告；不得修改账号模型、认证 API、业务状态机、权限/DataScope 语义、客户端或部署配置。
