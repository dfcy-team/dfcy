# SC-F2-LABEL-FONT-R1-P2-002 renderer 合同门禁基线

## 1. 基线结论

| 项目 | 冻结值 |
| --- | --- |
| 门禁 | `SC-F2-LABEL-FONT-R1-P2-002` |
| 原状态 | `ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE` |
| 本基线状态 | `FROZEN_PENDING_INDEPENDENT_REVIEW` |
| 机器合同 | `sc-f2-label-renderer-contract-v1` |
| v2 layout | `packing-label-v2-cjk` |
| v2 renderer | `sc-f2-reportlab-v2-cjk` |
| 字体包 | `sc-f2-label-font-v1` |
| 字体 bundle digest | `0f1fe3ff8595b042eac0aa505c1bbc0c423822e3261e25bc7f6423f696f43ba2` |
| 当前 renderer 代码修改 | 0 |
| 客户端/生产授权 | 无 |

本基线只冻结下一阶段的实现合同。独立审核通过前仍不得修改 `backend/apps/packing/labels.py`、`api_idempotency.py` 或启用 v2 renderer。

机器合同：

`docs/00_stage0/review/assets/scm_f2_label_renderer_contract_v1.json`

受控 verifier：

`backend/scripts/verify_sc_f2_label_renderer_contract.py`

## 2. 不可变资产与授权覆盖层

已准入四文件资产包保持原位不可变。其候选 manifest 中 renderer/layout 授权集合为空，这是资产取得阶段的历史事实，不能为了实现阶段原位改写，否则会改变已审核文件摘要。

本合同作为独立授权覆盖层，在独立审核通过后只授权以下精确组合进入本地实现：

| 字段 | 冻结值 |
| --- | --- |
| `layout_version` | `packing-label-v2-cjk` |
| `renderer_version` | `sc-f2-reportlab-v2-cjk` |
| `font_bundle_digest` | `0f1fe3ff...43ba2` |
| family | `SC F2 Label Sans` |
| Regular | `SCF2LabelSans-Regular` |
| Bold | `SCF2LabelSans-Bold` |

未知版本三元组必须安全失败。v1 的 `packing-label-v1`、`sc-f2-reportlab-v1` 和 `SHA-256("Helvetica|Helvetica-Bold")` 语义不得改变；旧快照不得读取当前活动字体。

## 3. Unicode 与 NFC 合同

### 3.1 执行顺序

所有可见业务文本按以下顺序处理：

1. 完成当前授权、permission、DataScope、供应商绑定和能力检查；
2. 按字段取得将进入快照的字符串；
3. 执行 NFC；
4. 按冻结字符策略分类；
5. 校验批准字体 cmap；
6. 执行宽度、换行和页面容量预检；
7. 使用规范化后的同一份快照进入最外层事务与真实渲染。

NFC 必须发生在快照哈希、幂等语义比较和布局前。禁止只在绘制时临时规范化，否则快照文本和实际 PDF 会不一致。

### 3.2 支持范围

冻结范围包含：

- 可打印 ASCII；
- Latin-1 可打印字符，但仍排除非 ASCII 分隔符和格式控制；
- `U+4E00` 至 `U+9FEF` 的 CJK Unified Ideographs；
- `U+FF01` 至 `U+FF5E` 的全角 ASCII 形式；
- 业务所需的中英文引号、破折号、省略号、项目符号、摄氏度、中文逗号/句号/书名号/方括号和人民币符号。

分类后获准范围共 21,275 个 code point，规范化清单 SHA-256 为：

`20345144f1e52cd7047c38c24d16740c3ec64b56c06f96ef262feb9d5553d368`

fontTools `4.63.0` 对 Regular/Bold 逐字符复核均为 21,275/21,275，缺字 0。

冻结拒绝：

- C0/C1 控制字符；
- zero-width、bidi 和其他 format 字符；
- variation selector；
- private use；
- 未分配和 surrogate；
- NFC 后仍存在的 combining mark；
- 非 ASCII 分隔符；
- Emoji；
- CJK Extension A/B 及其他未列入范围字符。

冻结 v1 corpus 的 6 个负向样本必须返回各自内部 reason，但公共响应不得返回字符、code point 或原始文本。

若字符不在业务支持范围，属于 422 用户业务文本错误；若字符属于冻结允许范围但批准字体 cmap 缺失，属于 500 资产完整性故障，不能归咎于用户。

## 4. 排版合同

| 项目 | 冻结值 |
| --- | --- |
| 页面 | A4 portrait，595.2756 × 841.8898 pt |
| 页面关系 | 一箱一页；批次按 box sequence 升序 |
| 单请求最大箱数 | 100 |
| 单箱 item area | 24 个文本 line slot |
| 商品名最多换行 | 2 行 |
| 最小正文字号 | 9 pt |
| 宽度计算 | 冻结字体和字号下的 ReportLab `stringWidth` |
| 无空格串 | 按 Unicode code point 断行 |
| 自动缩小 | 禁止低于 9 pt |
| 静默裁切/省略 | 禁止 |
| QR | 固定 144 pt，必须与正文和边距不重叠 |

商品名或合计 line slot 超限必须在事件、日志和幂等记录提交前返回稳定 422。现有 v1 的 `text[:95]` 只能保留在 v1 路径，不能复用于 v2。

## 5. 公共 API 错误合同

本轮不新增公共错误码，因此不需要改变 SC-F2-2 已冻结错误码集合。

| 场景 | HTTP | code | 稳定 message |
| --- | ---: | --- | --- |
| NFC 后含不支持字符 | 422 | `BUSINESS_RULE_VIOLATION` | `Label content contains unsupported characters.` |
| 内容超出冻结布局上限 | 422 | `BUSINESS_RULE_VIOLATION` | `Label content exceeds the supported layout limits.` |
| 字体、manifest、版本分派或 renderer 故障 | 500 | `INTERNAL_ERROR` | `Label rendering is temporarily unavailable.` |

失败响应统一为 JSON：

```json
{
  "success": false,
  "code": "<上表冻结值>",
  "message": "<上表稳定消息>",
  "data": null
}
```

失败响应不得包含 `Content-Disposition`、`ETag`、`Idempotency-Replayed` 或 `X-Packing-Batch-Version`。不得回显完整商品名、原始不支持文本、code point、本机路径、字体内部异常或堆栈。

## 6. 服务故障分类

以下全部映射为安全 500，而不是 400/409/422：

- 四文件缺失或出现额外文件；
- 大小、SHA-256 或 bundle digest 漂移；
- LICENSE/manifest 不匹配；
- 字体解析或注册失败；
- 允许范围内出现资产缺字；
- 子集化、二维码、PDF 绘制或保存失败；
- ETag 计算失败；
- 未知 layout/renderer/font digest 组合。

不得自动回退到 Helvetica、操作系统字体、网络字体或其他 bundle。v2 健康门禁失败只标记 v2 不就绪，不得破坏 v1 历史重放。

## 7. 首次失败、同 key 重试与历史重放

### 7.1 首次请求

字符、布局、资产或 renderer 任一失败都必须使最外层事务回滚：

- `PackingEvent` 增量 0；
- `OperationLog` 增量 0；
- `PackingApiIdempotencyRecord` 增量 0；
- 领域状态增量 0；
- PDF 不入库。

不允许“事务内预检、提交后真实渲染”。必须使用将要保存的同一快照，在事务提交前生成真实 PDF 和强 ETag。

### 7.2 同 key 修复后重试

- 用户文本失败后，因为没有幂等记录，修复业务文本后允许用同一 key 作为新请求执行；
- 资产故障后，因为没有幂等记录，修复资产后允许相同 payload 和同一 key 再次执行；
- 失败响应不得写成可重放的成功或失败幂等快照。

### 7.3 历史重放

命中已存在成功记录后 renderer 失败：

- 返回安全 500；
- 既有记录不得更新或删除；
- 事件、日志、幂等记录和领域状态增量均为 0；
- 触发资产/renderer 告警；
- 资产修复后，同一 key 必须按冻结快照恢复原 PDF 字节、ETag、文件名和批次版本。

当前授权和能力检查仍先于历史重放，不得因已有记录绕过撤权。

## 8. 可观测性

服务故障指标冻结为：

`packing_label_renderer_failure_total`

只允许维度：

- `phase=FIRST|REPLAY`；
- `reason_class`；
- `layout_version`；
- `renderer_version`；
- `font_bundle_digest`。

禁止 tenant 名称、商品名、原始文本、本机路径和异常消息进入指标维度或普通日志。用户文本 422 不触发服务资产告警；500 必须触发。

## 9. 实现期强制测试

SC-F2-LABEL-FONT-4 至少覆盖：

1. NFC 与负向 reason 优先级；
2. 21,275 个允许字符对 Regular/Bold 的 cmap 全覆盖；
3. 中英文宽度、换行、无空格串、24 line slot、100 箱和一箱一页；
4. v1 固定向量在 v2 合入前后逐字节不变；
5. v2 同快照跨进程 PDF 和 ETag 一致；
6. v1/v2/未知版本三元组分派；
7. 首次字符、资产、PDF 和 ETag 异常全事务回滚；
8. 同 key 在输入或资产修复后的重试；
9. 历史重放失败零写入及修复恢复；
10. 安全 JSON 错误信封和 PDF header 缺失；
11. FontFile2、ToUnicode、文本提取、视觉回归；
12. 真实 MySQL 原子幂等；
13. 锁定 Linux 的最大标签、100 页、并发和内存门禁。

## 10. 本轮边界与出口

基线提交不得包含 renderer、API、模型、迁移或客户端实现。独立审核只能给出：

- `PASS_FOR_SC_F2_LABEL_FONT_4_LOCAL_RENDERER_IMPLEMENTATION`
- `REQUIRES_SC_F2_LABEL_RENDERER_CONTRACT_REMEDIATION`

即使通过，也只授权本机 SC-F2-LABEL-FONT-4 开发和测试；不授权客户端融合、客户验收、部署、切流或生产可用声明。
