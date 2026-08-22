# SC-F2-LABEL-FONT-3 P1 整改报告

## 1. 整改结论

| 项目 | 结果 |
| --- | --- |
| 整改基线 | `1101966e0e97a7aef7531bd6a518f6b84b60fa53` |
| 整改项 | `SC-F2-LABEL-FONT-R3-P1-001` 至 `P1-002` |
| P1-001 | `REMEDIATED_PENDING_RECHECK` |
| P1-002 | `REMEDIATED_PENDING_RECHECK` |
| P2-001 关闭决定 | `CLOSE_WITH_NORMAL_GIT_AND_TOOLCHAIN_LOCK_V1` |
| 字体二进制进入 Git | 0 |
| renderer/API/领域代码修改 | 0 |
| 正式系统连接 | 0 |
| 当前结论 | `READY_FOR_SC_F2_LABEL_FONT_3_P1_REMEDIATION_RECHECK` |

本轮完成候选 manifest v2、许可证最终路径、精确工具链锁、容量预算、普通 Git 存储决定、bundle digest 固定向量、跨 Windows/Linux 证据和受控核验脚本。整改不自行关闭审核项；P1 和 P2-001 均等待下一轮独立复核。

## 2. P1-001 整改

### 2.1 仓库外候选 v2

新候选位于：

`D:\Users\Administrator\Documents\saas协同系统\_sc_f2_font_staging\Sans2.004\derived-candidate-v2`

原 `derived-run-1` 候选保留不变，用于审计对比。v2 没有修改 Regular/Bold 字体字节，只把上游 `OFL.txt` 以字节不变方式冻结为目标路径 `LICENSE.txt`，并升级 manifest。

| 文件 | 字节数 | SHA-256 |
| --- | ---: | --- |
| `SCF2LabelSans-Regular.ttf` | 10,596,408 | `976a1010423aeb77217358385e27cdd5ea18afbac4d83c036999d5b9cacaa0b3` |
| `SCF2LabelSans-Bold.ttf` | 10,585,916 | `fb03fe89d24b0b73b184a68d67dafb46132bf52e8685e7c6bfcf69863326cfe4` |
| `LICENSE.txt` | 4,388 | `1c05c68c34f9708415aada51f17e1b0092d2cea709bf4a94cd38114f9e73d7d9` |
| `manifest.json` | 5,113 | `e00920a6188621eb80c551a1c380ede83b46f29b23fb6e4ef79c7efcb83dcf46` |

候选包 ID：

`sc-f2-label-font-v1-candidate-2`

manifest schema：

`sc-f2-label-font-candidate-manifest-v2`

### 2.2 manifest 补齐项

v2 manifest 已补齐：

- 权威 source URL、commit、blob、源字节数和 SHA-256；
- `LICENSE.txt` 与上游 `OFL.txt` 的路径映射、blob、字节数和 SHA-256；
- 每个字体的 family、subfamily、full name、PostScript、font version、weight/width class；
- `fsType`、`INSTALLABLE_EMBEDDING`、允许子集化和非 bitmap-only 语义；
- 覆盖工具、仓库路径、脚本 SHA-256、fontTools 精确版本和 wheel SHA-256；
- corpus schema、文件摘要、105 个 code point 和清单摘要；
- 逐字体缺字数量；
- bundle digest schema、规范化规则和期望摘要；
- renderer/layout 明确空集合；
- `BLOCKED_PENDING_R3_RECHECK_AND_R1_P2_002` 授权状态；
- 下一门禁 `SC-F2-LABEL-FONT-3_P1_REMEDIATION_RECHECK`。

因此字段“缺失”和“明确未授权”不再混淆。

### 2.3 v2 独立验证

Windows 和 Linux 均对四文件精确集合执行：

- 无额外文件/缺失文件；
- 相对路径不越界；
- 文件字节数和 SHA-256；
- 全部字体表解析；
- family/subfamily/full/PostScript/version/weight/width；
- `fsType` 和嵌入语义；
- OFL Reserved Font Name；
- corpus 规范、正向样本重建、NFC case 和负向样本数量；
- 105/105 cmap；
- 规范化 bundle digest；
- renderer/layout 空授权。

两端结果均为 PASS，bundle digest 均为：

`0f1fe3ff8595b042eac0aa505c1bbc0c423822e3261e25bc7f6423f696f43ba2`

## 3. P1-002 与 P2-001 整改

### 3.1 关闭决定

新增：

`docs/00_stage0/review/scm_f2_chinese_label_font_p2_001_closure_decision.md`

决定为：

`CLOSE_WITH_NORMAL_GIT_AND_TOOLCHAIN_LOCK_V1`

当前状态为 `REMEDIATED_PENDING_SC_F2_LABEL_FONT_3_RECHECK`。独立复核通过后才正式生效。

### 3.2 普通 Git 策略

选择普通 Git，目标路径：

`backend/apps/packing/assets/fonts/sc-f2-label-font-v1/`

原因：

- 单字体小于 12 MiB；
- 四文件包约 20.21 MiB，小于 24 MiB；
- 完整 clone 可离线构建；
- 不依赖 Git LFS、发布下载、CDN 或系统字体；
- Git mirror、不可变提交和版本化目录可统一备份与回滚。

新增字体目录 `.gitattributes`，将字体扩展名标记为 binary，并明确没有 LFS filter。

### 3.3 工具链锁

新增机器可判定锁：

`docs/00_stage0/review/assets/scm_f2_label_font_toolchain_lock_v1.json`

冻结：

- Python `3.12.13`；
- Linux 权威容器 image digest；
- Windows Python executable SHA-256；
- fontTools、ReportLab、Pillow Linux/Windows、charset-normalizer、pypdf 的版本、文件名、大小和 SHA-256；
- Windows Poppler `pdftoppm 26.05.0` 和 executable SHA-256；
- 三个受控脚本路径和 SHA-256；
- 候选 manifest、包大小、bundle digest；
- 所有预算和实测证据；
- Windows/Linux 同一解析和同一 PDF 证据；
- 普通 Git、离线构建、校验、备份、漂移、回滚和升级规则。

当前 `reportlab>=4.2,<5.0` 只服务 v1 兼容路径，明确不得作为 v2 确定性依据。

### 3.4 bundle digest

新增固定向量：

`docs/00_stage0/review/assets/scm_f2_label_font_bundle_digest_vector_v1.json`

算法输入按 path 排序，包含 Regular、Bold 和 LICENSE 的 path/bytes/SHA-256；manifest 排除以避免自引用。规范化 JSON 为 UTF-8、排序 key、紧凑分隔符、无 BOM、无末尾 LF。

固定向量：

- 规范化字节数：434；
- SHA-256：`0f1fe3ff8595b042eac0aa505c1bbc0c423822e3261e25bc7f6423f696f43ba2`。

新增自动化测试复算固定向量及受控脚本摘要。

### 3.5 容量与性能

| 项目 | 观测 | 上限 | 结果 |
| --- | ---: | ---: | --- |
| 最大单字体 | 10,596,408 B | 12,582,912 B | PASS |
| 四文件包 | 21,191,825 B | 25,165,824 B | PASS |
| image inspect 增量 | 12,808,973 B | 16,777,216 B | PASS |
| 两页 PDF | 44,883 B | 131,072 B | PASS |
| 100 页 PDF | 137,608 B | 524,288 B | PASS |
| 两页最大时延 | 50.525 ms | 2,000 ms | PASS |
| 100 页时延 | 423.098 ms | 5,000 ms | PASS |
| 100 页 Python allocation peak | 10,964,943 B | 16,777,216 B | PASS |
| 100 页 max RSS | 88,408 KiB | 131,072 KiB | PASS |
| 容器内存上限 | 256 MiB | 256 MiB | PASS |

任何超限都必须安全失败并重新审核预算/工具链版本。

### 3.6 跨环境

Windows amd64 和 Linux amd64 均使用 Python `3.12.13` 与锁定依赖：

- bundle verifier：两端 PASS；
- bundle digest：两端相同；
- 两页 PDF：两端均 44,883 字节；
- PDF SHA-256：两端均 `c3c6689a66411a2bf2dfc903285e7061d38b5e30c8560801cbb252618992a624`；
- PDF 跨平台逐字节一致；
- FontFile2、ToUnicode、实际绘制字体和文本提取检查 PASS。

## 4. 仓库内整改文件

| 文件 | 用途 |
| --- | --- |
| `backend/apps/packing/assets/fonts/.gitattributes` | 字体二进制属性；明确不使用 LFS filter |
| `backend/scripts/verify_sc_f2_font_bundle.py` | 资产包完整性和字体合同验证 |
| `backend/scripts/probe_sc_f2_font_pdf.py` | 跨平台 PDF、预算和确定性探针 |
| `backend/scripts/inspect_sc_f2_probe_pdf.py` | PDF 嵌入、ToUnicode 和文本提取检查 |
| `backend/tests/test_sc_f2_font_bundle_digest_contract.py` | 固定向量和脚本摘要测试 |
| `docs/00_stage0/review/assets/.gitattributes` | 新增 JSON 证据 LF 保护 |
| `docs/00_stage0/review/assets/scm_f2_label_font_bundle_digest_vector_v1.json` | bundle digest 固定向量 |
| `docs/00_stage0/review/assets/scm_f2_label_font_toolchain_lock_v1.json` | 精确依赖、预算、跨环境和存储锁 |
| `docs/00_stage0/review/scm_f2_chinese_label_font_p2_001_closure_decision.md` | P2-001 关闭决定 |
| 本报告 | 整改归档 |

仓库内没有新增字体二进制、候选 manifest 或 LICENSE；它们仍只存在于仓库外等待复核。

## 5. 验证结果

| 检查 | 结果 |
| --- | --- |
| 固定向量和脚本摘要测试 | `2 passed` |
| Linux candidate v2 verifier | PASS |
| Windows candidate v2 verifier | PASS |
| Windows/Linux bundle digest 一致 | PASS |
| Windows/Linux PDF 字节一致 | PASS |
| pypdf 嵌入和文本提取 | PASS |
| 100 页预算探针 | PASS |
| Docker 文件层预算 | PASS |
| Defender 新下载 Windows wheel | 0 detections |
| Git 跟踪字体二进制 | 0 |
| 正式系统连接 | 0 |

## 6. 仍生效的边界

- P1-001/P1-002 和 P2-001 等待独立复核，不自行标记 CLOSED；
- P2-002 继续阻断 renderer 实现；
- 复核提交不得包含字体二进制；
- 复核通过后只允许创建精确四文件资产的独立普通 Git 提交；
- 不授权客户端融合、客户验收、生产部署或切流。

## 7. 下一步

执行：

`SC-F2-LABEL-FONT-3 P1 整改复核`
