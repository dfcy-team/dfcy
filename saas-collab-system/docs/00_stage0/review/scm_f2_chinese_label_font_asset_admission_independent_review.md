# SC-F2-LABEL-FONT-3 中文字体资产准入独立审核

## 1. 审核结论

| 项目 | 结论 |
| --- | --- |
| 工作包 | `SC-F2-LABEL-FONT-3` |
| 审核基线 | `24405dba34a6643abe7c40f22e1ea6e278f3c617` |
| 待审候选 | `sc-f2-label-font-v1-candidate-1` |
| 候选 manifest SHA-256 | `574b1973d19334987114d1fc0ff409a014e870548175cafb39ba2d8fcb407b82` |
| 字体二进制技术核验 | PASS |
| 来源/许可/RFN | PASS |
| 独立复现 | PASS，Regular/Bold 逐字节一致 |
| P0 | 0 |
| P1 | 2 |
| 继续生效的 P2 | `R1-P2-002` |
| 最终结论 | `REQUIRES_SC_F2_LABEL_FONT_ASSET_ADMISSION_REMEDIATION` |
| 字体进入 Git | 不允许 |
| renderer 实现 | 不允许 |
| 客户端/生产 | 不允许 |

待审字体文件没有发现来源、许可证、摘要、元数据、缺字、可重复生成或 ReportLab 基础兼容问题。但是候选 manifest 尚未满足专项基线第 7 节的最低资产合同，且 `R1-P2-001` 的预资产提交门禁已经到期但没有形成可审核的关闭决定，因此本轮不能按第 11 节授予“资产包本地实现授权”。

本报告只归档独立审核发现，不整改候选、manifest、依赖或存储策略，不把字体二进制放入 Git。

## 2. 审核对象与边界

### 2.1 提交对象

提交 `24405db` 只新增：

`docs/00_stage0/review/scm_f2_chinese_label_font_candidate_acquisition_report.md`

审核开始时 Git 跟踪的 `.ttf`、`.otf`、`.ttc`、`.woff`、`.woff2` 文件数量为 0。工作区已有的 pilot、架构文档和其他未跟踪文件不属于本轮，未暂存、未修改。

### 2.2 仓库外对象

待审候选位于：

`D:\Users\Administrator\Documents\saas协同系统\_sc_f2_font_staging\Sans2.004\derived-run-1`

独立复核目录位于：

`D:\Users\Administrator\Documents\saas协同系统\_sc_f2_font_staging\Sans2.004\admission-review`

两个目录均位于 Git 仓库根目录之外。本轮没有安装或注册 Windows 字体，没有连接正式数据库、缓存、对象存储、打印机或线上系统，也没有修改标签 renderer、API、权限、DataScope 和领域代码。

## 3. 独立来源链复核

审核未直接信任取得报告中的本地源文件，而是从 Google Fonts 不可变提交重新下载：

| 项目 | 独立复核值 |
| --- | --- |
| 不可变提交 | `2894aab31764f10f29c421bdfd2340d3b382d384` |
| 源路径 | `ofl/notosanssc/NotoSansSC[wght].ttf` |
| Git blob SHA-1 | `fb0637bafbcd804fe32152370a1225990745b4bc` |
| 源字体字节数 | 17,772,300 |
| 源字体 SHA-256 | `a3041811a78c361b1de50f953c805e0244951c21c5bd412f7232ef0d899af0da` |
| `OFL.txt` SHA-256 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |
| `METADATA.pb` SHA-256 | `3de4c75126b7b78011abb6773dd88ca3041ab512623681bd9234ef50019afc37` |

重新取得的三个文件与取得报告冻结值完全相同。重新下载目录经 Microsoft Defender 显式 Custom Scan，Engine `1.1.26060.3008`、Signature `1.455.402.0`，检测数为 0。

原始静态 CFF OTF 的淘汰决定也成立：它能够覆盖语料，但 ReportLab `4.5.1` 不支持其 PostScript outline。选择同源 TrueType variable 后静态实例化不是隐式格式替换，而是按基线作为新候选完成全量复核。

## 4. 候选完整性与独立复现

### 4.1 精确候选

| 文件 | 字节数 | SHA-256 | 结论 |
| --- | ---: | --- | --- |
| `SCF2LabelSans-Regular.ttf` | 10,596,408 | `976a1010423aeb77217358385e27cdd5ea18afbac4d83c036999d5b9cacaa0b3` | MATCH |
| `SCF2LabelSans-Bold.ttf` | 10,585,916 | `fb03fe89d24b0b73b184a68d67dafb46132bf52e8685e7c6bfcf69863326cfe4` | MATCH |
| `OFL.txt` | 4,388 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` | MATCH |
| `manifest.json` | 3,282 | `574b1973d19334987114d1fc0ff409a014e870548175cafb39ba2d8fcb407b82` | MATCH |

字体合计 `21,182,324` 字节；四个候选包文件合计 `21,189,994` 字节，即约 `20.208 MiB`。该数值只是当前未压缩候选的观测值，不是 P2-001 所要求的容量预算或批准阈值。

### 4.2 独立解析

独立检查脚本 SHA-256：

`835344fb912c14cbcf5454837e8dfe6716fc7a77ff15a7ebfd096972f67978a3`

在 Python `3.12.13`、fontTools `4.63.0`、无网络、只读输入、非特权、限资源容器中，对每张字体表执行解析并复核：

| 项目 | Regular | Bold |
| --- | --- | --- |
| outline | TrueType | TrueType |
| variable tables | 0 | 0 |
| glyph | 31,036 | 31,036 |
| cmap code point | 30,890 | 30,890 |
| weight class | 400 | 700 |
| width class | 5 | 5 |
| `fsType` | 0 | 0 |
| family | `SC F2 Label Sans` | `SC F2 Label Sans` |
| subfamily | `Regular` | `Bold` |
| PostScript | `SCF2LabelSans-Regular` | `SCF2LabelSans-Bold` |
| 字体内部版本 | `Version 2.004-H2;hotconv 1.0.118;makeotfexe 2.5.65603` | 同左 |

所有目标 name record 的跨平台值一致，面向用户的 family/full/PostScript/typographic family 均不包含 Reserved Font Name `Source`。copyright、trademark、OFL 描述和许可证 URL 仍保留。

### 4.3 从新下载源重新生成

使用取得阶段冻结的派生脚本：

| 项目 | 值 |
| --- | --- |
| 派生脚本 SHA-256 | `51ac9c6fe50e4a57794b9c895bdb8cf0afe8689604efd9aabb6050960be683eb` |
| fontTools wheel SHA-256 | `445af2eab030a16b9171ea8bdda7ebf7d96bda2df88ee182a464252f6e05e20d` |
| 容器镜像 | `python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de` |
| 轴值 | Regular `wght=400`；Bold `wght=700` |

从独立重新下载且扫描通过的源文件重新生成后，两份字体的字节数和 SHA-256 与待审候选完全相同。来源到候选的可重复生成链通过。

## 5. 许可证与 Reserved Font Name

随源许可证为 OFL-1.1，明确声明 Reserved Font Name `Source`。独立复核结论：

- 允许随软件仓库、应用、容器或发布制品再分发，但必须随副本保留 copyright 和 OFL，且不得单独售卖字体；
- 允许完整 PDF 嵌入和动态子集化；
- 允许 variable-to-static 修改，派生字体继续适用 OFL；
- 修改版面向用户的主字体名不得使用 `Source`；
- 候选名 `SC F2 Label Sans` 不包含 `Source`，同时保留上游 copyright 和 trademark 声明；
- 不得用 Adobe、Google 或 Noto 名称暗示项目背书。

该部分通过。它是工程合规判断，不替代组织法务意见。

## 6. 字符覆盖与 PDF 独立探针

### 6.1 字符覆盖

| 项目 | 独立结果 |
| --- | --- |
| corpus schema | `sc-f2-label-font-corpus-v1` |
| corpus 文件 SHA-256 | `4d28a684f034a90a10d9bc4d0e0ccde8ff41435887a1de8b4de55d0e833feb6f` |
| code point 数 | 105 |
| 清单 SHA-256 | `18817beaf1ec51db9464fa3225ae1c1d4631801a29237c87b3bc727273975232` |
| Regular 缺字 | 0 |
| Bold 缺字 | 0 |

该结果仍只证明冻结 v1 正向范围。负向字符拒绝、NFC 输入处理和业务错误映射属于 `R1-P2-002` 后续 renderer 合同，不因字体 cmap 含有某个字符而自动获准。

### 6.2 ReportLab 双进程探针

使用 ReportLab `4.5.1` 官方 wheel和冻结依赖，在两个全新无网络容器中分别生成两页 PDF：

| 项目 | 结果 |
| --- | --- |
| PDF 字节数 | 44,868 |
| 两次 SHA-256 | `f3451f37d02382a9d256aa37c8978d0dce2eb2115ee59140fc7cd7f34514653c` |
| 跨进程字节一致 | PASS |
| 单次探针 `ru_maxrss` 观测值 | 87,916 KiB |

该内存数据只覆盖两页语料探针，不能代替真实标签、最大明细、多箱和并发压力预算。

### 6.3 嵌入、提取与视觉检查

使用 pypdf `6.10.0` 独立检查：

- Regular/Bold 均以 `/TrueType`、`/FontFile2` 子集嵌入；
- 两者均包含 `/ToUnicode`；
- 第一页实际绘制只使用 Regular，第二页实际绘制只使用 Bold；
- ReportLab 资源字典含未绘制文本的默认 Helvetica resource，但内容流没有使用它绘制文字；
- 两页均可提取全部 8 个正向样本文本。

使用 Poppler `pdftoppm 26.05.0` 以 144 DPI 栅格化并逐页检查，Regular/Bold 的中文、英文、数字、单位和标点均可见，没有 tofu、黑框、缺字、重叠或页面越界。

本轮 PDF 只是字体兼容探针，不是 `packing-label-v2-cjk` 真实布局验收；未检查二维码、宽度换行、最大明细、最小字号、一箱一页和历史重放。

## 7. P1 阻断项

### SC-F2-LABEL-FONT-R3-P1-001：候选 manifest 未满足最低资产合同

基线第 7 节要求 manifest 至少冻结字体版本、嵌入权限读取结果、覆盖工具及版本和获准 renderer/layout。当前候选 manifest：

- 候选许可证路径为 `OFL.txt`，而目标资产包最低合同冻结为 `LICENSE.txt`，尚未明确最终路径映射；
- `assets[]` 没有逐资产 `font_version`；
- 只记录数值 `fs_type=0`，没有冻结可审核的 embedding rights 语义；
- `coverage` 没有检查工具、精确版本和检查脚本摘要；
- 没有 renderer/layout 授权字段；当前应显式记录“无获准消费者、等待门禁”，而不是省略；
- 状态仍为 `REPOSITORY_OUTSIDE_CANDIDATE_PENDING_INDEPENDENT_ASSET_ADMISSION_REVIEW`，下一门禁仍指向本次审核。

影响：

- manifest 脱离取得报告后不能独立满足资产合同；
- 运行时或后续审核无法区分字段缺失与明确“未授权”；
- 不能把该 manifest 直接提升为获准资产包 manifest。

关闭条件：

1. 修订候选 manifest schema，并逐项补齐上述字段；
2. 冻结许可证最终相对路径；若采用 `LICENSE.txt`，必须证明其字节与上游 `OFL.txt` 完全相同并更新 manifest；
3. 对未获准 renderer/layout 使用明确空集合和阻断状态，不得提前填入已授权版本；
4. 保留源 commit、源文件、OFL、派生脚本和每个候选的完整摘要；
5. 更新 manifest 后重新计算其字节数和 SHA-256；
6. 因 manifest 是候选包组成部分，修订后的精确四文件集合必须重新快速复核。

### SC-F2-LABEL-FONT-R3-P1-002：P2-001 预资产提交门禁到期但未关闭

`R1-P2-001` 状态为 `ACCEPTED_DEFERRED_WITH_PRE_ASSET_COMMIT_GATE`。本阶段出口会授予资产包本地实现权限，因此该门禁现已到期。

当前证据：

- `backend/requirements.txt` 仍为 `reportlab>=4.2,<5.0`，没有确定性 renderer 的精确锁；
- fontTools、ReportLab、Pillow、PDF 检查和栅格化工具只有仓库外 wheel/本机工具证据，没有受控锁文件和同一解析合同；
- 只得到当前候选 `20.208 MiB`、探针 PDF 44,868 字节和单进程 87,916 KiB 的观测值；
- 没有字体单文件、资产包、容器镜像增量、代表性/上限 PDF、首次加载、稳态和并发内存的批准阈值；
- 没有普通 Git、Git LFS、发布制品三选一决定；
- 没有离线构建、备份、摘要校验、漂移处理和回滚合同；
- 没有 CI、Windows 和 Linux 权威环境的同一依赖解析证据；
- 没有规范化 manifest、资产排序、bundle digest 算法和固定向量。

影响：

- 资产进入 Git/LFS/制品的目标和恢复路径不确定；
- 相同字体可能在不同环境由不同依赖解释或输出不同 PDF；
- 无法冻结可用于业务快照的真实 `font_bundle_digest`；
- 不满足资产提交前强门禁，因此不能授予本地实现权限。

关闭条件：

1. 单独形成并审核 P2-001 关闭决定；
2. 冻结所有生产和验收依赖的精确版本、平台 wheel/制品 SHA-256 与锁文件；
3. 给出字体、资产包、镜像增量、代表性/上限 PDF、首次/稳态/并发内存预算和失败阈值；
4. 明确选择 Git、Git LFS 或发布制品，并冻结离线构建、备份、校验、漂移和回滚规则；
5. 提供 CI、Windows、Linux 的同一解析证据；
6. 冻结规范化 manifest 与 bundle digest 算法，并以固定向量保护。

## 8. P2 状态

### R1-P2-001

原状态：`ACCEPTED_DEFERRED_WITH_PRE_ASSET_COMMIT_GATE`

本轮状态：`DUE_AND_BLOCKING`，对应 `R3-P1-002`。关闭前禁止字体二进制进入 Git/LFS/发布制品和本地 renderer 实现。

### R1-P2-002

状态保持：

`ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE`

它不否定字体候选本身，但继续阻断 renderer 实现。用户不支持字符、资产故障、稳定错误码、事务回滚、同 key 重试和历史重放失败语义仍须在下一合同审核中冻结。

## 9. 审核矩阵

| 审核项 | 结果 |
| --- | --- |
| 仓库/生产隔离 | PASS |
| 权威不可变来源 | PASS |
| 独立重新下载摘要 | PASS |
| Defender 显式扫描 | PASS |
| OFL/RFN/修改/嵌入用途 | PASS |
| Regular/Bold 精确文件 | PASS |
| 独立解析全部字体表 | PASS |
| 从新下载源重新生成 | PASS |
| v1 corpus 105/105 | PASS |
| ReportLab 注册和双进程 PDF | PASS |
| FontFile2/ToUnicode/文本提取 | PASS |
| 基础视觉栅格检查 | PASS |
| manifest 最低字段 | FAIL，`R3-P1-001` |
| P2-001 依赖/预算/存储/digest | FAIL，`R3-P1-002` |
| P2-002 renderer 错误合同 | DEFERRED，继续阻断实现 |
| 字体进入 Git | NOT AUTHORIZED |
| renderer/客户端/生产 | NOT AUTHORIZED |

## 10. 整改与下一步

下一步应执行：

`修复 SC-F2-LABEL-FONT-R3-P1-001 至 P1-002，并补充 P2-001 关闭决定`

整改提交不得混入字体二进制或 renderer 代码。整改后先执行：

`SC-F2-LABEL-FONT-3 P1 整改复核`

只有修订 manifest 和 P2-001 关闭合同复核通过后，才可授予“复制审核批准的精确字体文件进入已批准存储目标”的本地权限。该权限仍不关闭 P2-002，不授权 renderer、客户端融合或生产发布。
