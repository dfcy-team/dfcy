# SC-F2-LABEL-FONT-R1-P2-002 renderer 合同门禁独立审核

## 1. 审核结论

| 项目 | 结论 |
| --- | --- |
| 审核对象 | `03a16b24e046ed78cb2c97672f3c099513609b48` |
| 审核门禁 | `SC-F2-LABEL-FONT-R1-P2-002` |
| P0 | 0 |
| P1 | 0 |
| P2 | 0 |
| 审核结果 | `PASS_FOR_SC_F2_LABEL_FONT_4_LOCAL_RENDERER_IMPLEMENTATION` |
| 合同状态 | `AUTHORIZED_FOR_SC_F2_LABEL_FONT_4_LOCAL_IMPLEMENTATION` |
| 客户端融合授权 | 否 |
| 客户验收授权 | 否 |
| 部署、切流或生产授权 | 否 |

冻结提交边界正确，合同内容足以约束下一阶段本地 renderer 实现，未发现需要整改的 P0、P1 或 P2 问题。`SC-F2-LABEL-FONT-R1-P2-002` 至此关闭，但关闭范围严格限于允许进入 `SC-F2-LABEL-FONT-4` 本机开发和测试。

继承自 SC-F2-2 的客户端前置事项 `SC-F2-2-R2-P2-002` 仅转为“本地 renderer 合同已满足”；它仍不得被解释为客户端接入或客户验收门禁已关闭。客户端融合必须等待 SC-F2-LABEL-FONT-4 实现审核及后续专项出口。

## 2. 审核边界

本轮只审核以下新增或调整内容：

- renderer 机器合同及其中文基线；
- 受控合同 verifier 和最小合同测试；
- 两个 `.gitattributes` 中对应机器文件的 LF 规则。

冻结提交没有修改 `backend/apps/packing/labels.py`、`backend/apps/packing/api_idempotency.py`、API、模型、迁移、客户端或部署文件。工作树中的其他未提交文件不属于本轮审核，也未进入冻结提交。

## 3. 逐项复核

### 3.1 资产与版本隔离

- 四文件字体资产的文件名、大小、逐文件 SHA-256 和 bundle digest 均被机器合同精确冻结；
- 候选 manifest 保持不可变，renderer 授权由独立合同覆盖层承担；
- 只允许 `packing-label-v2-cjk`、`sc-f2-reportlab-v2-cjk` 和批准字体 bundle digest 的精确三元组；
- v1 的 `packing-label-v1`、`sc-f2-reportlab-v1` 和 Helvetica digest 保持不变；
- 未知版本组合必须安全失败，不允许系统字体或网络字体回退。

结论：通过。

### 3.2 Unicode、NFC 与字体覆盖

- NFC 在快照、哈希、幂等语义比较和布局之前执行；
- 允许范围被规范化为 21,275 个 code point，并冻结清单摘要 `20345144f1e52cd7047c38c24d16740c3ec64b56c06f96ef262feb9d5553d368`；
- Regular/Bold 已有 fontTools `4.63.0` 全量 cmap 证据，结果均为 21,275/21,275、缺字 0；
- C0/C1、format、variation selector、private use、surrogate、未分配字符、残余 combining mark、非 ASCII separator、Emoji 和未准入 CJK 扩展均明确拒绝；
- 6 个负向 corpus 的内部 reason 被冻结，公共响应不泄露字符、code point 或原文。

结论：通过。

### 3.3 布局与容量

- A4 portrait、一箱一页、box sequence 升序、单请求最多 100 箱；
- 单箱 24 个 item line slot、商品名最多两行、正文不得低于 9 pt；
- 宽度使用冻结字体和字号下的 ReportLab `stringWidth`，无空格文本按 code point 断行；
- 禁止静默裁切、省略和小于下限的自动缩放，v1 的 `text[:95]` 不得进入 v2；
- QR 固定 144 pt 且必须通过边界与重叠检查；
- 布局超限必须在任何事件、日志或幂等记录提交前失败。

结论：通过。

### 3.4 公共错误合同

本轮没有新增公共错误码，保持 SC-F2-2 已冻结集合：

| 场景 | HTTP | code | 稳定 message |
| --- | ---: | --- | --- |
| 不支持字符 | 422 | `BUSINESS_RULE_VIOLATION` | `Label content contains unsupported characters.` |
| 布局超限 | 422 | `BUSINESS_RULE_VIOLATION` | `Label content exceeds the supported layout limits.` |
| 资产或 renderer 故障 | 500 | `INTERNAL_ERROR` | `Label rendering is temporarily unavailable.` |

失败响应统一为安全 JSON、`data=null`，且不携带 PDF 下载头、ETag、幂等重放头或批次版本头。资产路径、异常、堆栈、商品名和原始文本不得进入响应或普通日志。

结论：通过。

### 3.5 原子性、幂等与历史重放

- 授权、permission、DataScope、供应商绑定和能力检查仍先于首次执行及历史重放；
- 首次字符、布局、资产、PDF 或 ETag 失败必须回滚最外层事务；
- 失败时 `PackingEvent`、`OperationLog`、`PackingApiIdempotencyRecord` 和领域状态增量均为 0；
- 不保存失败幂等记录，因此输入或资产修复后允许同 key 作为新请求再次执行；
- 不允许“事务内预检、提交后真实渲染”，真实 PDF 与强 ETag 必须在提交前生成；
- 历史重放 renderer 故障返回安全 500、零写入、保留原记录并告警；修复后同 key 必须恢复原 PDF、ETag、文件名和批次版本。

结论：通过。

### 3.6 可观测性与安全

- 服务故障指标固定为 `packing_label_renderer_failure_total`；
- 指标只允许 phase、reason class 和版本/字体摘要等低基数维度；
- 用户文本 422 不触发资产告警，资产或 renderer 500 必须触发告警；
- tenant 名称、商品名、原文、本机路径和异常消息禁止进入指标维度或普通日志。

结论：通过。

## 4. 机器复核结果

在冻结提交上执行受控 verifier，结果：

```text
result=PASS
gate_state=FROZEN_PENDING_INDEPENDENT_REVIEW
accepted_scope_codepoints=21275
positive_codepoints=105
negative_samples=6
asset_bundle_digest=0f1fe3ff8595b042eac0aa505c1bbc0c423822e3261e25bc7f6423f696f43ba2
v1_preserved=true
renderer_code_changed=false
contract_sha256=bf172abea5dc531314a72770770a56bd374ca4ef871e43070147d588fac91952
verifier_sha256=0b3a678de2240794814f9812d3fdd9602de484eb26fc4db1253dfbdd049b0ca2
```

最小合同测试通过；冻结提交只包含 6 个预期门禁文件，未包含 renderer、API、模型、迁移或客户端实现。

## 5. 出口与下一阶段约束

本审核只产生以下出口：

`PASS_FOR_SC_F2_LABEL_FONT_4_LOCAL_RENDERER_IMPLEMENTATION`

下一阶段必须按本合同实现，并补齐合同基线第 9 节列出的强制测试。任何公共错误码、支持字符范围、布局容量、版本三元组、幂等写入顺序或历史重放语义变更，都必须先修订合同并重新独立审核。

在 SC-F2-LABEL-FONT-4 实现、代码审核、整改复核和最终归档完成前，不得进入客户端融合、客户验收、部署、切流或生产运行。
