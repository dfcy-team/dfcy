# SC-F2 中文标签字体资产立项基线 P1 整改复核报告

## 1. 复核结论

| 项目 | 结论 |
| --- | --- |
| 复核工作包 | `SC-F2-LABEL-FONT-1-R1-RECHECK` |
| 整改提交 | `cbca927012108567f3751282e2321f33f84310b9` |
| 原审核提交 | `c12f1b5c90e3` |
| 分支 | `codex/scm-f2-packing-local` |
| P0 | 0 |
| 已关闭原 P1 | 3 |
| 未关闭原 P1 | 1 |
| 新增阻断项 | `SC-F2-LABEL-FONT-R2-P1-001` |
| P2 门禁 | 2 项均有效 |
| 最终结论 | `REQUIRES_SC_F2_LABEL_FONT_BASELINE_REMEDIATION` |
| 字体资产取得授权 | 不通过 |
| renderer 实现授权 | 无 |
| 生产授权 | 无 |

整改提交的事务策略、二进制取得规程、许可证用途和 P2 门禁均达到基线要求；语料内容及提交对象摘要也可重算。但语料的 LF 行尾合同没有 Git 属性保护，在本仓库当前 `core.autocrlf=true` 环境中无法保证跨检出一致，因此 `R1-P1-003` 尚不能关闭。

## 2. 复核范围

- `docs/00_stage0/review/scm_f2_chinese_label_font_asset_project_baseline.md`
- `docs/00_stage0/review/assets/scm_f2_label_font_corpus_v1.json`
- `docs/00_stage0/review/scm_f2_chinese_label_font_asset_p1_remediation_report.md`
- `docs/00_stage0/review/scm_f2_chinese_label_font_asset_independent_review.md`
- `backend/apps/packing/api_idempotency.py`
- Git 提交、属性和行尾配置

本轮只读复核整改材料，没有下载、复制、安装或解析字体，没有修改整改对象、业务代码或环境配置，没有连接正式系统。

## 3. 提交与隔离核验

`cbca92701210` 只包含：

| 状态 | 文件 |
| --- | --- |
| A | `docs/00_stage0/review/assets/scm_f2_label_font_corpus_v1.json` |
| A | `docs/00_stage0/review/scm_f2_chinese_label_font_asset_p1_remediation_report.md` |
| M | `docs/00_stage0/review/scm_f2_chinese_label_font_asset_project_baseline.md` |

核验结果：

- 字体二进制新增：0；
- 业务代码修改：0；
- 正式系统连接：0；
- 原有无关工作区修改未进入整改提交；
- Git diff whitespace：通过。

## 4. 原 P1 逐项复核

### 4.1 R1-P1-001：首次渲染与事务回滚

**复核结果：通过**

基线已明确区分首次生成和历史重放：

- 首次真实 PDF 渲染和强 ETag 计算必须在最外层事务提交前完成；
- 只有真实渲染成功才允许提交事件、日志和幂等快照；
- PDF 仅以内存字节返回，不进入数据库；
- 明确禁止“事务内预检、提交后真实渲染”；
- 历史重放 renderer 失败不得改写冻结记录；
- 注入异常、字体缺失、摘要漂移、缺字、PDF 保存和 ETag 异常均有实现期测试门禁。

当前代码仍在事务退出后调用 renderer，但本阶段是合同整改，不是代码实现；基线已正确冻结后续必须采用的改造方案。

状态：`CLOSED_BY_RECHECK`

### 4.2 R1-P1-002：字体二进制取得与解析安全

**复核结果：通过**

基线第 7.1 节已按顺序冻结：

- 权威 HTTPS 和不可变版本；
- 仓库外暂存且禁止系统安装；
- 原始/最终 URL、HTTP、时间、大小和摘要；
- 下载、条目、解包总量和压缩比上限；
- 路径穿越、重复路径、链接和 reparse point 拒绝；
- 摘要、安全扫描、隔离解析的先后顺序；
- 无网络、非特权、只读和受资源限制的解析进程；
- 资产审核通过前禁止进入仓库。

状态：`CLOSED_BY_RECHECK`

### 4.3 R1-P1-003：机器可判定字符范围

**复核结果：部分通过，未关闭**

从整改提交对象直接读取并复算：

| 项目 | 结果 |
| --- | --- |
| JSON | 可解析 |
| UTF-8 BOM | 无 |
| 提交对象行尾 | LF |
| NFC 规范化样本 | 全部一致 |
| 正向 code point | 105 |
| 正向清单 | 与样本重建结果一致 |
| 清单 SHA-256 | `18817beaf1ec51db9464fa3225ae1c1d4631801a29237c87b3bc727273975232` |
| 语料文件 blob SHA-256 | `4d28a684f034a90a10d9bc4d0e0ccde8ff41435887a1de8b4de55d0e833feb6f` |
| 负向原因 | 6 个且唯一 |

内容合同本身通过，但跨检出可复现性未通过：

- 本仓库 `core.autocrlf=true`；
- 仓库根和应用根均无 `.gitattributes`；
- `git check-attr` 显示该 JSON 的 `text`、`eol` 和 `working-tree-encoding` 全部 unspecified；
- `git ls-files --eol` 显示 `i/lf w/lf attr/`，即索引和当前工作树碰巧为 LF，但没有属性约束；
- Git 已在此前暂存时明确警告“LF will be replaced by CRLF the next time Git touches it”。

因此，Windows 新检出或 Git 再处理后，文件可能变为 CRLF，违反 JSON 内冻结的 `"line_endings": "LF"`。当前文件通过不能替代跨检出保障。

状态：`REOPENED_AS_SC_F2_LABEL_FONT_R2_P1_001`

### 4.4 R1-P1-004：许可证实际用途

**复核结果：通过**

基线已逐项覆盖仓库、应用制品、容器、PDF 静态嵌入、动态子集化、修改义务、Reserved Font Name、声明保留、variable-to-static 和修改后改名。并明确：

- 上游许可证保留原始字节和摘要；
- SPDX 或 `EmbeddingRights` 不能单独作为通过证据；
- 修改资产必须重新走来源、许可、摘要、覆盖和命名审核。

状态：`CLOSED_BY_RECHECK`

## 5. 新增/遗留 P1

### SC-F2-LABEL-FONT-R2-P1-001：LF 语料合同未受 Git 属性保护

**优先级：P1**

**整改要求**

1. 在最小作用域增加 `.gitattributes`，至少冻结：

   `scm_f2_label_font_corpus_v1.json text eol=lf`

2. 属性文件建议放在 `docs/00_stage0/review/assets/.gitattributes`，避免改变无关文件；
3. 对语料执行 Git 规范化后重新暂存；
4. 验证 `git check-attr text eol` 返回 `text: set`、`eol: lf`；
5. 验证 `git ls-files --eol` 显示索引/工作树均为 LF 且包含 `eol=lf` 属性；
6. 在 `core.autocrlf=true` 的独立检出验证 UTF-8 无 BOM、无 CRLF、JSON 可解析、105 个 code point 和清单摘要一致；
7. 把行尾属性检查加入语料合同自检或 CI，防止后续属性被移除。

关闭本项不需要修改语料业务内容或摘要算法。

## 6. P2 门禁复核

### R1-P2-001

状态：

`ACCEPTED_DEFERRED_WITH_PRE_ASSET_COMMIT_GATE`

复核：有效。明确允许仓库外取得候选，但精确依赖、大小预算、Git/LFS/制品策略和跨环境证据完成前，禁止字体文件进入 Git、禁止 renderer 实现。

### R1-P2-002

状态：

`ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE`

复核：有效。明确阻断 renderer 实现，直到用户不支持字符、服务端资产故障、安全错误消息、同 key 重试、历史重放失败和 SC-F2-2 错误分类兼容全部冻结。

## 7. 风险统计

| 级别 | 数量 | 结论 |
| --- | ---: | --- |
| P0 | 0 | 无生产、数据或发布越界 |
| P1 | 1 | 阻断字体资产取得授权 |
| P2 | 2 | 已设置前置强门禁，不视为关闭 |

## 8. 下一步

下一步只允许：

`修复 SC-F2-LABEL-FONT-R2-P1-001 并执行快速复核`

修复前继续禁止：

- 下载或复制字体；
- 创建运行时字体资产目录；
- 字体文件进入 Git；
- renderer 和 API 实现；
- 客户端标签融合；
- 正式环境连接或生产可用声明。

快速复核通过后才可给出 `PASS_FOR_SC_F2_LABEL_FONT_ASSET_ACQUISITION`；该结论仍只允许按既定规程在仓库外取得候选，不解除两项 P2 门禁。
