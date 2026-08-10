# SC-F2 中文标签字体资产立项基线 P1 整改报告

## 1. 整改结论

| 项目 | 结果 |
| --- | --- |
| 工作包 | `SC-F2-LABEL-FONT-1-R1` |
| 整改依据 | `c12f1b5c90e3` 独立审核 |
| 整改范围 | `R1-P1-001` 至 `R1-P1-004`、`R1-P2-001` 至 `R1-P2-002` |
| P1 自查 | 4 项均已形成基线整改 |
| P2 | 2 项均已冻结前置强门禁 |
| 当前结论 | `P1_REMEDIATED_PENDING_RECHECK` |
| 字体资产取得授权 | 无，等待复核 |
| renderer 实现授权 | 无 |
| 生产授权 | 无 |

本轮只修订专项基线并新增机器可判定语料，没有下载、复制、安装或入库字体，没有创建运行时字体资产目录，没有修改标签、幂等、API 或领域代码。

## 2. 变更对象

| 文件 | 用途 |
| --- | --- |
| `docs/00_stage0/review/scm_f2_chinese_label_font_asset_project_baseline.md` | 冻结 P1 整改和 P2 门禁 |
| `docs/00_stage0/review/assets/scm_f2_label_font_corpus_v1.json` | 冻结 v1 正向、规范化和负向验收语料 |
| 本报告 | 建立审核项到整改证据的映射 |

整改后文件摘要：

| 文件 | SHA-256 |
| --- | --- |
| 专项基线 | `26852cbf79f74d163847610e995e3f643547d1f95a3085d1ec9c6741d3fdd8f1` |
| v1 语料 JSON | `4d28a684f034a90a10d9bc4d0e0ccde8ff41435887a1de8b4de55d0e833feb6f` |

以上是提交前工作树摘要；复核应以本轮提交中的实际文件重新计算，不依赖手工抄录。

## 3. P1 整改映射

### 3.1 R1-P1-001：首次渲染与事务回滚

已在基线第 9.1 节冻结：

- 首次请求在最外层 `transaction.atomic()` 退出前真实生成完整 PDF 并计算 ETag；
- PDF 字节仅保存在内存，不持久化；
- 字体、缺字、布局、子集化、PDF 保存和 ETag 任一异常均回滚事件、日志和幂等记录；
- 禁止用“事务内预检、事务提交后真实渲染”规避原子要求；
- 历史重放零业务写入，renderer 失败不得修改历史记录；
- 实现阶段必须覆盖首次异常回滚与重放异常零写入。

整改状态：`REMEDIATED_PENDING_RECHECK`

### 3.2 R1-P1-002：字体二进制取得安全

已在基线第 7.1 节冻结顺序化取得规程：

- HTTPS 权威域名和不可变 release/tag/commit；
- 仓库外暂存，禁止系统安装和直接覆盖资产目录；
- 原始/最终 URL、HTTP、UTC 时间、大小和下载摘要；
- 256 MiB 下载、128 个归档条目、64 MiB 单条目、512 MiB 解包总量和 100:1 压缩比上限；
- 路径穿越、绝对路径、重复规范路径、链接和 reparse point 拒绝；
- 摘要先于扫描，扫描先于隔离解析；
- 无网络、非特权、只读输入、受资源限制的独立解析进程；
- 资产审核通过前禁止复制进仓库。

整改状态：`REMEDIATED_PENDING_RECHECK`

### 3.3 R1-P1-003：机器可判定字符范围

已新增 `sc-f2-label-font-corpus-v1`：

| 项目 | 冻结值 |
| --- | --- |
| Unicode 规范化 | NFC |
| 正向 code point | 105 个 |
| code point 清单摘要 | `18817beaf1ec51db9464fa3225ae1c1d4631801a29237c87b3bc727273975232` |
| 正向样本 | 固定字段、业务编号、三类商品、度量、中西文和中文标点 |
| 规范化样本 | combining acute 到预组字符 |
| 负向样本 | 控制字符、零宽、变体选择符、私用区、CJK 扩展 B、Emoji |

清单摘要算法固定为：Unicode scalar 数值升序去重，每行 ASCII `U+XXXX` 或 `U+XXXXXX`，每行及文件末尾均为 LF，再计算 SHA-256。

语料自校验：

`corpus=valid count=105 digest=18817be... normalization=valid`

零缺字只证明该冻结语料，不扩张为 GB18030 或全部 CJK 承诺。

整改状态：`REMEDIATED_PENDING_RECHECK`

### 3.4 R1-P1-004：许可证实际用途

已在基线第 6.3 节冻结逐用途许可证审核：

- 原始字体进入仓库的再分发；
- 应用制品和容器镜像分发；
- PDF 静态嵌入和动态子集化；
- 子集化是否构成修改及对应义务；
- Reserved Font Name 或类似保留名称；
- LICENSE、copyright notice 和 attribution 保留；
- variable-to-static、裁剪、转换和其他修改；
- 修改资产的强制改名和内部名称标识。

许可证必须保留上游原始字节和摘要；内部 `EmbeddingRights` 或单独填写 SPDX 均不足以通过。

整改状态：`REMEDIATED_PENDING_RECHECK`

## 4. P2 门禁决定

### 4.1 R1-P2-001：依赖与大文件存储

状态：

`ACCEPTED_DEFERRED_WITH_PRE_ASSET_COMMIT_GATE`

允许复核通过后在仓库外按安全规程取得候选文件，但在精确依赖、大小预算、Git/LFS/制品策略、离线构建和跨环境依赖证据完成审核前，禁止字体文件进入 Git，禁止 renderer 实现。

### 4.2 R1-P2-002：API 错误映射

状态：

`ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE`

允许仓库外候选取得，但 renderer 合同审核前必须冻结用户不支持字符、服务端资产完整性故障、安全消息、同 key 重试、历史重放失败及 SC-F2-2 错误分类兼容。

## 5. 自查结果

| 检查 | 结果 |
| --- | --- |
| JSON 可解析 | 通过 |
| UTF-8 无 BOM | 通过 |
| JSON 使用 LF | 通过 |
| 正向样本 NFC 后 code point 重算 | 105，与清单一致 |
| code point 清单摘要复算 | 一致 |
| 规范化样本复算 | 一致 |
| 4 项 P1 均有明确基线章节 | 通过 |
| 2 项 P2 均有状态和前置门禁 | 通过 |
| Git diff whitespace | 通过 |
| 字体文件新增 | 0 |
| 业务代码修改 | 0 |
| 正式系统连接 | 0 |

## 6. 复核重点

复核必须验证：

1. 首次真实渲染必须发生在事务提交前，而不是只做预检；
2. 资产取得顺序、容量上限、路径安全、扫描和隔离解析均可执行；
3. 语料 code point 集合和摘要可由正向样本独立重建；
4. 负向样本原因唯一且不进入 renderer；
5. 许可证审核覆盖仓库、制品、容器和 PDF 子集化；
6. P2-001 确实阻断资产入 Git，P2-002 确实阻断 renderer 实现；
7. 复核通过也不关闭 `SC-F2-2-R2-P2-002`，不授权客户端或生产。

## 7. 下一步出口

下一步执行：

`SC-F2 中文标签字体资产立项与审核基线 P1 整改复核`

复核只能给出：

- `PASS_FOR_SC_F2_LABEL_FONT_ASSET_ACQUISITION`
- `REQUIRES_SC_F2_LABEL_FONT_BASELINE_REMEDIATION`

第一项只授权按基线第 7.1 节在仓库外取得并审查候选资产，不授权字体进入 Git、renderer 开发、客户端融合或生产使用。
