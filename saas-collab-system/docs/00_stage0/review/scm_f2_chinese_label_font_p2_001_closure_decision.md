# SC-F2-LABEL-FONT-R1-P2-001 关闭决定

## 1. 决定

| 项目 | 冻结值 |
| --- | --- |
| 门禁 | `SC-F2-LABEL-FONT-R1-P2-001` |
| 原状态 | `ACCEPTED_DEFERRED_WITH_PRE_ASSET_COMMIT_GATE` |
| 关闭决定 | `CLOSE_WITH_NORMAL_GIT_AND_TOOLCHAIN_LOCK_V1` |
| 当前状态 | `REMEDIATED_PENDING_SC_F2_LABEL_FONT_3_RECHECK` |
| 生效条件 | `SC-F2-LABEL-FONT-3 P1 整改复核`通过 |
| renderer 实现 | 不授权 |
| 客户端/生产 | 不授权 |

本决定关闭“依赖与大文件存储”设计悬而未决问题，但不自行宣布审核通过。独立复核确认本决定、锁文件、预算证据和候选 manifest v2 一致后，P2-001 才正式关闭并允许以单独资产提交复制审核批准的精确四文件包。

`SC-F2-LABEL-FONT-R1-P2-002` 继续保持 `ACCEPTED_DEFERRED_WITH_PRE_RENDERER_CONTRACT_GATE`，因此即使 P2-001 关闭，也不得实现中文 v2 renderer。

## 2. 存储选择

选择：

`NORMAL_GIT`

目标路径：

`backend/apps/packing/assets/fonts/sc-f2-label-font-v1/`

不选择 Git LFS 或运行时发布制品下载，理由如下：

- Regular 和 Bold 单文件均小于 12 MiB；
- 经整改的四文件候选包为 21,191,825 字节，低于 24 MiB 冻结上限；
- 普通 Git 完整克隆天然包含离线构建所需的精确字体、许可证和 manifest；
- 不引入 LFS 服务、pointer hydration、发布页下载、CDN、系统字体或网络 fallback；
- Git mirror、不可变提交和已有备份流程可以统一保留资产历史；
- 回滚只需重新部署先前不可变应用提交及其版本化字体包。

所有字体扩展名在 `backend/apps/packing/assets/fonts/.gitattributes` 中标记为 binary，不配置 LFS filter。字体变更不得原位覆盖已准入目录；必须创建新的版本化 bundle 路径并重新执行取得与准入审核。

## 3. 精确工具链锁

机器可判定锁文件：

`docs/00_stage0/review/assets/scm_f2_label_font_toolchain_lock_v1.json`

权威生成环境：

- Linux amd64；
- Python `3.12.13`；
- `python@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de`；
- 安装期间 `--no-index --no-deps`；
- 仅使用 SHA-256 复核通过的 wheel；
- 验证执行期间 `--network none`、只读输入、非特权、限 CPU/内存/PID。

冻结 Python 依赖：

| 依赖 | 版本 | 平台 | SHA-256 |
| --- | --- | --- | --- |
| fontTools | 4.63.0 | any | `445af2eab030a16b9171ea8bdda7ebf7d96bda2df88ee182a464252f6e05e20d` |
| ReportLab | 4.5.1 | any | `06fce8cb56c83307cfa4909cdf4e6a2ddbb44e5d6ef4d2edca896d7e9769f091` |
| Pillow | 12.3.0 | Linux cp312 amd64 | `78cb2c6865a35ab8ff8b75fd122f6033b92a62c82801110e48ddd6c936a45d91` |
| Pillow | 12.3.0 | Windows cp312 amd64 | `a2b55dd6b2a4c4b7d87ffa56bdb33fdc5fdb9a462173861a7bc097f17d91cb09` |
| charset-normalizer | 3.4.9 | any | `68e5f26a1ad57ded6d1cfb85331d1c1a195314756471d97758c48498bb4dcdf5` |
| pypdf | 6.10.0 | any | `90005e959e1596c6e6c84c8b0ad383285b3e17011751cedd17f2ce8fcdfc86de` |

Windows 视觉栅格审计冻结为 workspace dependency bundle `26.727.11326` 内的 `pdftoppm 26.05.0`，可执行文件 SHA-256 为：

`742cbbd9a00931ad16c6618410bc40471375d639a45c61c1d86f3dcfc54b6388`

当前 `backend/requirements.txt` 中 `reportlab>=4.2,<5.0` 只保留 v1 兼容路径，不是 v2 权威解析合同。后续 v2 renderer 在任何代码实现前必须解析为本锁中的精确版本；不允许用范围约束替代。

## 4. 受控脚本

| 脚本 | SHA-256 | 用途 |
| --- | --- | --- |
| `backend/scripts/verify_sc_f2_font_bundle.py` | `23c0ab79c4b45396343d90cf286e38820419671f5c7eb8eaa79e83749cc54427` | 文件集、摘要、字体表、元数据、OFL、corpus 和 bundle digest |
| `backend/scripts/probe_sc_f2_font_pdf.py` | `c06eb57a591cf30e4344687f14d8885dffa4bbdcef08d9e3eee09cd3d4087fa0` | 跨平台确定性 PDF、时延和内存探针 |
| `backend/scripts/inspect_sc_f2_probe_pdf.py` | `31789c7837adbb86e39cf8cc96fd4033d06397c984d46158103bdc835784b32b` | FontFile2、ToUnicode、实际绘制字体和文本提取 |

锁文件中的脚本摘要由自动化测试复算，防止“文档锁值”和实际脚本漂移。

## 5. bundle digest

算法 schema：

`sc-f2-label-font-bundle-digest-v1`

输入只包含 Regular、Bold 和 `LICENSE.txt`，manifest 自身排除以避免自引用。每条记录包含：

- `path`；
- `bytes`；
- `sha256`。

规范化规则：

- 按 path 字典序排列资产；
- JSON key 字典序；
- UTF-8、无 BOM；
- 分隔符为 `,` 和 `:`，不含多余空白；
- 无末尾 LF。

固定向量：

`docs/00_stage0/review/assets/scm_f2_label_font_bundle_digest_vector_v1.json`

规范化载荷长度为 434 字节，期望 SHA-256：

`0f1fe3ff8595b042eac0aa505c1bbc0c423822e3261e25bc7f6423f696f43ba2`

该摘要是候选字体包真实文件摘要，不覆盖 v1 的 `SHA-256("Helvetica|Helvetica-Bold")` 历史逻辑值。

## 6. 容量和性能预算

| 项目 | 观测值 | 上限 |
| --- | ---: | ---: |
| 最大单字体 | 10,596,408 B | 12,582,912 B |
| 四文件包 | 21,191,825 B | 25,165,824 B |
| Docker image inspect 增量 | 12,808,973 B | 16,777,216 B |
| COPY layer 未压缩显示 | 21.2 MB | 25,165,824 B |
| 两页探针 PDF | 44,883 B | 131,072 B |
| 100 页探针 PDF | 137,608 B | 524,288 B |
| 两页 Linux 时延 | 50.525 ms | 2,000 ms |
| 两页 Windows 时延 | 29.378 ms | 2,000 ms |
| 100 页 Linux 时延 | 423.098 ms | 5,000 ms |
| 100 页 Python allocation peak | 10,964,943 B | 16,777,216 B |
| 100 页进程 max RSS | 88,408 KiB | 131,072 KiB |
| 验证容器内存限制 | 256 MiB | 256 MiB |

上限是资产和字体探针准入预算。真实 `packing-label-v2-cjk` 最大明细、多箱、并发 worker 和 Django 基线仍须在 renderer 阶段测量；若超过本预算，必须安全失败并重新审核工具链/预算版本，不能静默放宽。

## 7. 跨环境证据

Windows amd64 和 Linux amd64 均使用 Python `3.12.13`、fontTools `4.63.0`、ReportLab `4.5.1` 及平台对应的锁定 Pillow `12.3.0`：

| 检查 | Windows | Linux |
| --- | --- | --- |
| 候选 manifest v2 | PASS | PASS |
| corpus | 105/105 | 105/105 |
| bundle digest | `0f1fe3...43ba2` | `0f1fe3...43ba2` |
| 两页 PDF 字节数 | 44,883 | 44,883 |
| 两页 PDF SHA-256 | `c3c6689a...92a624` | `c3c6689a...92a624` |
| PDF 跨平台逐字节一致 | PASS | PASS |

CI 必须复用 Linux 权威镜像 digest 和锁定 wheel，以 `--no-index --no-deps` 解析；不得依赖 runner 全局包。

## 8. 离线构建、校验、备份和回滚

1. 仅从完整 Git clone 构建；禁止构建时下载字体。
2. 资产提交前和镜像构建前运行 bundle verifier。
3. v2 健康门禁再次校验文件集、大小、SHA-256、元数据、corpus 和 bundle digest。
4. 任一漂移、额外文件、缺失文件、路径越界或解析失败均安全失败。
5. Git mirror 和不可变提交保存已准入版本；发布备份沿用同一应用提交。
6. 回滚时部署先前不可变应用提交及其版本化字体包，不原位修改当前包。
7. 升级时创建新 bundle version，重新执行权威取得、准入、renderer 和最终审核。

## 9. 生效边界

独立复核通过后，P2-001 只允许下一步创建“精确四文件字体资产的独立普通 Git 提交”。它不授权：

- 修改 `backend/apps/packing/labels.py`；
- 启用 `packing-label-v2-cjk`；
- 关闭 P2-002；
- 客户端融合；
- 生产部署或切流。
